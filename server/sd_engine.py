"""
Stable Diffusion v1.5 LCM engine for RK3588.
Text encoder / U-Net / VAE decoder all run on NPU via rknnlite.
"""

import base64
import io
import json
import logging
import os
import threading
import time
from typing import List, Optional, Union

import numpy as np
import torch
from diffusers.pipelines.pipeline_utils import DiffusionPipeline
from diffusers.pipelines.stable_diffusion import StableDiffusionPipelineOutput
from diffusers.schedulers import LCMScheduler
from PIL import Image
from rknnlite.api import RKNNLite
from transformers import CLIPTokenizer

from config import (
    SD_CLIP_TOKENIZER,
    SD_DEFAULT_GUIDANCE_SCALE,
    SD_DEFAULT_HEIGHT,
    SD_DEFAULT_STEPS,
    SD_DEFAULT_WIDTH,
    SD_SCHEDULER_CONFIG,
    SD_TEXT_ENCODER_DIR,
    SD_UNET_DIR,
    SD_VAE_DECODER_DIR,
)

logger = logging.getLogger(__name__)

VAE_SCALE_FACTOR = 8


# ============================================================
# Thin rknnlite wrapper (adapted from run_rknn-lcm.py)
# ============================================================
class RKNN2Model:
    def __init__(self, model_dir: str, data_format: str = "nchw"):
        logger.info(f"Loading RKNN model {model_dir}")
        self.data_format = data_format.lower()
        config_path = os.path.join(model_dir, "config.json")
        rknn_path = os.path.join(model_dir, "model.rknn")
        if not os.path.exists(rknn_path):
            raise FileNotFoundError(f"RKNN model not found: {rknn_path}")
        self.config = json.load(open(config_path)) if os.path.exists(config_path) else {}
        self.rknnlite = RKNNLite()
        self.rknnlite.load_rknn(rknn_path)
        self.rknnlite.init_runtime(core_mask=RKNNLite.NPU_CORE_0_1_2)
        self.modelname = model_dir.rstrip("/").split("/")[-1]
        logger.info(f"  {self.modelname} loaded")

    def __call__(self, **kwargs) -> List[np.ndarray]:
        def _prep(x):
            if isinstance(x, np.ndarray):
                if x.dtype in (np.float16, np.float64):
                    x = x.astype(np.float32, copy=False)
                if x.ndim == 4:
                    if self.data_format == "nhwc" and x.shape[1] in (1, 3, 4):
                        x = x.transpose(0, 2, 3, 1)
                    elif self.data_format == "nchw" and x.shape[-1] in (1, 3, 4):
                        x = x.transpose(0, 3, 1, 2)
                x = np.ascontiguousarray(x)
            return x

        inputs = [_prep(v) for v in kwargs.values()]
        return self.rknnlite.inference(inputs=inputs, data_format=self.data_format)

    def release(self):
        self.rknnlite.release()


# ============================================================
# LCM pipeline (adapted from run_rknn-lcm.py)
# ============================================================
class RKNN2LatentConsistencyPipeline(DiffusionPipeline):
    def __init__(
        self,
        text_encoder: RKNN2Model,
        unet: RKNN2Model,
        vae_decoder: RKNN2Model,
        scheduler: LCMScheduler,
        tokenizer: CLIPTokenizer,
    ):
        super().__init__()
        self.register_modules(tokenizer=tokenizer, scheduler=scheduler)
        self.safety_checker = None
        self.text_encoder = text_encoder
        self.unet = unet
        self.vae_decoder = vae_decoder
        self.vae_scale_factor = VAE_SCALE_FACTOR

    # ---- helpers -----------------------------------------------------------

    @staticmethod
    def _numpy_to_pil(images: np.ndarray) -> List[Image.Image]:
        if images.ndim == 3:
            images = images[None, ...]
        images = (images * 255).round().astype("uint8")
        if images.shape[-1] == 1:
            return [Image.fromarray(image.squeeze(), mode="L") for image in images]
        return [Image.fromarray(image) for image in images]

    @staticmethod
    def _denormalize(images: np.ndarray) -> np.ndarray:
        return np.clip(images / 2 + 0.5, 0, 1)

    def _postprocess(self, image: np.ndarray, output_type: str = "pil"):
        if output_type == "latent":
            return image
        do_denormalize = [True] * image.shape[0]
        image = np.stack(
            [
                self._denormalize(image[i]) if do_denormalize[i] else image[i]
                for i in range(image.shape[0])
            ],
            axis=0,
        )
        image = image.transpose((0, 2, 3, 1))
        if output_type == "pil":
            return self._numpy_to_pil(image)
        return image

    def _encode_prompt(self, prompt: Union[str, List[str]], num_images_per_prompt: int):
        if isinstance(prompt, str):
            batch_size = 1
        else:
            batch_size = len(prompt)

        text_inputs = self.tokenizer(
            prompt,
            padding="max_length",
            max_length=self.tokenizer.model_max_length,
            truncation=True,
            return_tensors="np",
        )
        prompt_embeds = self.text_encoder(input_ids=text_inputs.input_ids.astype(np.int32))[0]
        prompt_embeds = np.repeat(prompt_embeds, num_images_per_prompt, axis=0)
        return prompt_embeds

    def _prepare_latents(self, batch_size, num_channels, height, width, dtype, generator):
        shape = (
            batch_size,
            num_channels,
            height // self.vae_scale_factor,
            width // self.vae_scale_factor,
        )
        if isinstance(generator, np.random.RandomState):
            latents = generator.randn(*shape).astype(dtype)
        elif isinstance(generator, torch.Generator):
            latents = torch.randn(*shape, generator=generator).numpy().astype(dtype)
        else:
            latents = np.random.randn(*shape).astype(dtype)
        latents = latents * self.scheduler.init_noise_sigma
        return latents

    @staticmethod
    def _get_guidance_scale_embedding(w, embedding_dim=512, dtype=np.float32):
        w = w * 1000.0
        half_dim = embedding_dim // 2
        emb = np.log(10000.0) / (half_dim - 1)
        emb = np.exp(np.arange(half_dim, dtype=dtype) * -emb)
        emb = w[:, None].astype(dtype) * emb[None, :]
        emb = np.concatenate([np.sin(emb), np.cos(emb)], axis=1)
        if embedding_dim % 2 == 1:
            emb = np.pad(emb, [(0, 0), (0, 1)])
        return emb

    # ---- main call ---------------------------------------------------------

    def __call__(
        self,
        prompt: Union[str, List[str]] = "",
        height: int = SD_DEFAULT_HEIGHT,
        width: int = SD_DEFAULT_WIDTH,
        num_inference_steps: int = SD_DEFAULT_STEPS,
        guidance_scale: float = SD_DEFAULT_GUIDANCE_SCALE,
        num_images_per_prompt: int = 1,
        generator: Optional[Union[np.random.RandomState, torch.Generator]] = None,
        output_type: str = "pil",
    ):
        if isinstance(prompt, str):
            batch_size = 1
        else:
            batch_size = len(prompt)

        if generator is None:
            generator = np.random.RandomState()

        # 1. Text encoding
        t0 = time.time()
        prompt_embeds = self._encode_prompt(prompt, num_images_per_prompt)
        logger.info(f"  SD text encode: {time.time() - t0:.1f}s")

        # 2. Set timesteps
        self.scheduler.set_timesteps(num_inference_steps)
        timesteps = self.scheduler.timesteps

        # 3. Latents
        latents = self._prepare_latents(
            batch_size * num_images_per_prompt,
            self.unet.config.get("in_channels", 4),
            height,
            width,
            prompt_embeds.dtype,
            generator,
        )

        # 4. Guidance scale embedding (LCM)
        bs = batch_size * num_images_per_prompt
        w = np.full(bs, guidance_scale - 1.0, dtype=prompt_embeds.dtype)
        w_embedding = self._get_guidance_scale_embedding(w, dtype=prompt_embeds.dtype)

        # 5. Denoising loop
        t_denoise = time.time()
        for _i, t in enumerate(timesteps):
            timestep = np.array([t], dtype=np.int64)
            noise_pred = self.unet(
                sample=latents,
                timestep=timestep,
                encoder_hidden_states=prompt_embeds,
                timestep_cond=w_embedding,
            )[0]
            latents, denoised = self.scheduler.step(
                torch.from_numpy(noise_pred), t, torch.from_numpy(latents), return_dict=False
            )
            latents, denoised = latents.numpy(), denoised.numpy()
        logger.info(f"  SD denoise ({num_inference_steps} steps): {time.time() - t_denoise:.1f}s")

        # 6. Decode
        t_decode = time.time()
        denoised = denoised / self.vae_decoder.config.get("scaling_factor", 0.18215)
        image = np.concatenate(
            [self.vae_decoder(latent_sample=denoised[i : i + 1])[0] for i in range(denoised.shape[0])]
        )
        image = self._postprocess(image, output_type=output_type)
        logger.info(f"  SD decode: {time.time() - t_decode:.1f}s")

        return StableDiffusionPipelineOutput(images=image, nsfw_content_detected=None)

    def release(self):
        self.text_encoder.release()
        self.unet.release()
        self.vae_decoder.release()


# ============================================================
# Top-level SD engine
# ============================================================
class SDEngine:
    def __init__(self):
        self.pipe: Optional[RKNN2LatentConsistencyPipeline] = None
        self._lock = threading.Lock()

    def load(self):
        if self.pipe is not None:
            return
        logger.info("Loading SD LCM pipeline …")

        if not os.path.exists(SD_SCHEDULER_CONFIG):
            raise FileNotFoundError(f"scheduler config not found: {SD_SCHEDULER_CONFIG}")
        scheduler_config = json.load(open(SD_SCHEDULER_CONFIG))
        scheduler = LCMScheduler.from_config(scheduler_config)

        if not os.path.exists(SD_CLIP_TOKENIZER):
            raise FileNotFoundError(f"CLIP tokenizer not found: {SD_CLIP_TOKENIZER}")
        tokenizer = CLIPTokenizer.from_pretrained(SD_CLIP_TOKENIZER)

        self.pipe = RKNN2LatentConsistencyPipeline(
            text_encoder=RKNN2Model(SD_TEXT_ENCODER_DIR, data_format="nchw"),
            unet=RKNN2Model(SD_UNET_DIR, data_format="nhwc"),
            vae_decoder=RKNN2Model(SD_VAE_DECODER_DIR, data_format="nhwc"),
            scheduler=scheduler,
            tokenizer=tokenizer,
        )
        logger.info("SD pipeline ready")

    def generate(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = SD_DEFAULT_WIDTH,
        height: int = SD_DEFAULT_HEIGHT,
        num_inference_steps: int = SD_DEFAULT_STEPS,
        guidance_scale: float = SD_DEFAULT_GUIDANCE_SCALE,
    ) -> str:
        """Generate image and return base64-encoded PNG."""
        self.load()
        with self._lock:
            result = self.pipe(
                prompt=prompt,
                height=height,
                width=width,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
                generator=np.random.RandomState(),
                output_type="pil",
            )
            img = result.images[0]
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode("utf-8")

    def release(self):
        if self.pipe:
            self.pipe.release()


sd_engine = SDEngine()
