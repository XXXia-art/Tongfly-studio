import argparse
import base64
import io
import json
import logging
import os
import time
import threading

import numpy as np
import torch
from PIL import Image
from diffusers.schedulers import LCMScheduler
from transformers import CLIPTokenizer
from rknnlite.api import RKNNLite

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# ============================================================
# RKNN MODEL WRAPPER
# ============================================================
class RKNN2Model:
    def __init__(self, model_dir, data_format="nchw"):
        self.data_format = data_format.lower()

        config_path = os.path.join(model_dir, "config.json")
        rknn_path = os.path.join(model_dir, "model.rknn")

        self.config = json.load(open(config_path)) if os.path.exists(config_path) else {}

        self.rknn = RKNNLite()
        self.rknn.load_rknn(rknn_path)
        self.rknn.init_runtime(core_mask=RKNNLite.NPU_CORE_0_1_2)

        logger.info(f"Loaded RKNN: {model_dir}")

    def __call__(self, **kwargs):
        def prep(x):
            if isinstance(x, np.ndarray):
                if x.dtype != np.float32:
                    x = x.astype(np.float32)

                if x.ndim == 4:
                    if self.data_format == "nhwc" and x.shape[1] in (1, 3, 4):
                        x = x.transpose(0, 2, 3, 1)
                    elif self.data_format == "nchw" and x.shape[-1] in (1, 3, 4):
                        x = x.transpose(0, 3, 1, 2)

                x = np.ascontiguousarray(x)
            return x

        inputs = [prep(v) for v in kwargs.values()]
        return self.rknn.inference(inputs=inputs, data_format=self.data_format)

    def release(self):
        self.rknn.release()


# ============================================================
# RK3588 SD PIPELINE (LCM)
# ============================================================
class RKNN2LatentConsistencyPipeline:
    def __init__(self, text_encoder, unet, vae_decoder, scheduler, tokenizer):
        self.text_encoder = text_encoder
        self.unet = unet
        self.vae = vae_decoder
        self.scheduler = scheduler
        self.tokenizer = tokenizer
        self.vae_scale_factor = 8

    # ---------------- prompt ----------------
    def encode_prompt(self, prompt):
        inputs = self.tokenizer(
            prompt,
            padding="max_length",
            max_length=self.tokenizer.model_max_length,
            return_tensors="np",
        )
        return self.text_encoder(input_ids=inputs.input_ids.astype(np.int32))[0]

    # ---------------- latents ----------------
    def prepare_latents(self, batch, ch, h, w, dtype, gen):
        shape = (batch, ch, h // self.vae_scale_factor, w // self.vae_scale_factor)

        if isinstance(gen, np.random.RandomState):
            latents = gen.randn(*shape).astype(dtype)
        else:
            latents = np.random.randn(*shape).astype(dtype)

        return latents * self.scheduler.init_noise_sigma

    # ---------------- decode ----------------
    def decode(self, latents):
        latents = latents / self.vae.config.get("scaling_factor", 0.18215)

        outs = [
            self.vae(latent_sample=latents[i:i+1])[0]
            for i in range(latents.shape[0])
        ]
        return np.concatenate(outs, axis=0)

    # ---------------- main ----------------
    def __call__(self, prompt, height, width, num_inference_steps, guidance_scale, generator):
        batch = 1 if isinstance(prompt, str) else len(prompt)

        prompt_embeds = self.encode_prompt(prompt)

        self.scheduler.set_timesteps(num_inference_steps)
        timesteps = self.scheduler.timesteps

        latents = self.prepare_latents(
            batch,
            self.unet.config.get("in_channels", 4),
            height,
            width,
            prompt_embeds.dtype,
            generator,
        )

        w = np.full((batch,), guidance_scale - 1, dtype=prompt_embeds.dtype)
        w_emb = self._guidance_embedding(w, dtype=prompt_embeds.dtype)

        for t in timesteps:
            timestep = np.array([t], dtype=np.int64)

            noise_pred = self.unet(
                sample=latents,
                timestep=timestep,
                encoder_hidden_states=prompt_embeds,
                timestep_cond=w_emb,
            )[0]

            latents, denoised = self.scheduler.step(
                torch.from_numpy(noise_pred),
                t,
                torch.from_numpy(latents),
                return_dict=False,
            )

            latents = latents.numpy()
            denoised = denoised.numpy()

        image = self.decode(denoised)

        image = image.transpose(0, 2, 3, 1)
        image = image / 2 + 0.5
        image = np.clip(image, 0, 1)

        return {"images": self.to_pil(image)}

    @staticmethod
    def to_pil(image):
        image = (image * 255).astype(np.uint8)
        return [Image.fromarray(image[0])]

    @staticmethod
    def _guidance_embedding(w, embedding_dim=512, dtype=np.float32):
        w = w * 1000
        half = embedding_dim // 2
        emb = np.log(10000.0) / (half - 1)
        emb = np.exp(np.arange(half, dtype=dtype) * -emb)
        emb = w[:, None] * emb[None, :]
        emb = np.concatenate([np.sin(emb), np.cos(emb)], axis=1)
        return emb


# ============================================================
# SD ENGINE (same style as your VLMEngine)
# ============================================================
class SDEngine:
    def __init__(self):
        self.pipe = None
        self.lock = threading.Lock()

    def load(self, model_path, tokenizer_path):
        logger.info("Loading RK3588 SD Engine...")

        scheduler = LCMScheduler.from_config(
            json.load(open(os.path.join(model_path, "scheduler/scheduler_config.json")))
        )

        tokenizer = CLIPTokenizer.from_pretrained(tokenizer_path)

        self.pipe = RKNN2LatentConsistencyPipeline(
            text_encoder=RKNN2Model(os.path.join(model_path, "text_encoder"), "nchw"),
            unet=RKNN2Model(os.path.join(model_path, "unet"), "nhwc"),
            vae_decoder=RKNN2Model(os.path.join(model_path, "vae_decoder"), "nhwc"),
            scheduler=scheduler,
            tokenizer=tokenizer,
        )

    def generate(self, model_path, tokenizer_path, prompt, size, steps, guidance):
        self.load(model_path, tokenizer_path)

        h, w = map(int, size.split("x"))

        with self.lock:
            result = self.pipe(
                prompt=prompt,
                height=h,
                width=w,
                num_inference_steps=steps,
                guidance_scale=guidance,
                generator=np.random.RandomState(),
            )

        img = result["images"][0]

        buf = io.BytesIO()
        img.save(buf, format="PNG")

        return base64.b64encode(buf.getvalue()).decode()


# ============================================================
# CLI (same style as your VLM entry)
# ============================================================
def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--prompt", required=True)
    parser.add_argument("-i", required=True)
    parser.add_argument("-o", required=True)
    parser.add_argument("--tokenizer", required=True)

    parser.add_argument("--size", default="512x512")
    parser.add_argument("--steps", type=int, default=4)
    parser.add_argument("--guidance", type=float, default=7.5)

    args = parser.parse_args()

    engine = SDEngine()

    img_b64 = engine.generate(
        args.i,
        args.tokenizer,
        args.prompt,
        args.size,
        args.steps,
        args.guidance,
    )

    os.makedirs(args.o, exist_ok=True)
    out_path = os.path.join(args.o, "out.png")

    with open(out_path, "wb") as f:
        f.write(base64.b64decode(img_b64))

    print("saved:", out_path)


if __name__ == "__main__":
    main()