import base64
import io
import logging
import os
import shutil
from pathlib import Path

from diffusers import StableDiffusionPipeline
from PIL import Image
import torch

from config import (
    SD_DEVICE,
    SD_MODEL_PATH,
    SD_DEFAULT_WIDTH,
    SD_DEFAULT_HEIGHT,
    SD_DEFAULT_STEPS,
    SD_DEFAULT_GUIDANCE_SCALE,
)

logger = logging.getLogger(__name__)


def _ensure_clip_cache():
    """Populate the local HuggingFace cache with CLIP ViT-L/14 files generated
    from the openai-clip package so that diffusers can load SD v1.5 offline."""
    local_dir = Path(__file__).resolve().parent / "clip_local"
    if not local_dir.exists():
        raise RuntimeError(
            f"{local_dir} does not exist. Run `python prepare_clip_local.py` first."
        )

    cache_dir = Path.home() / ".cache" / "huggingface" / "hub"
    repo_folder = cache_dir / "models--openai--clip-vit-large-patch14"
    snapshot_hash = "local"
    snapshot_dir = repo_folder / "snapshots" / snapshot_hash
    refs_file = repo_folder / "refs" / "main"

    snapshot_dir.mkdir(parents=True, exist_ok=True)
    refs_file.parent.mkdir(parents=True, exist_ok=True)
    refs_file.write_text(snapshot_hash)

    for name in ["config.json", "vocab.json", "merges.txt", "tokenizer_config.json"]:
        src = local_dir / name
        dst = snapshot_dir / name
        if not dst.exists() or dst.stat().st_size != src.stat().st_size:
            shutil.copy2(src, dst)


class SDEngine:
    def __init__(self):
        self.pipe = None
        self.device = SD_DEVICE
        self.model_path = SD_MODEL_PATH

    def load(self):
        if self.pipe is not None:
            return
        logger.info(f"Loading SD from {self.model_path} to {self.device} ...")
        _ensure_clip_cache()
        config_path = Path(__file__).resolve().parent / "sd_v1_config.yaml"
        self.pipe = StableDiffusionPipeline.from_single_file(
            self.model_path,
            torch_dtype=torch.float16,
            use_safetensors=True,
            original_config=str(config_path),
            local_files_only=True,
        )
        self.pipe = self.pipe.to(self.device)
        # Enable memory efficient attention if available.
        if hasattr(self.pipe.unet, "set_attn_processor"):
            try:
                from diffusers.models.attention_processor import AttnProcessor2_0

                self.pipe.unet.set_attn_processor(AttnProcessor2_0())
            except Exception:
                pass
        logger.info("SD loaded.")

    def generate(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = SD_DEFAULT_WIDTH,
        height: int = SD_DEFAULT_HEIGHT,
        num_inference_steps: int = SD_DEFAULT_STEPS,
        guidance_scale: float = SD_DEFAULT_GUIDANCE_SCALE,
    ) -> str:
        self.load()
        with torch.no_grad():
            image = self.pipe(
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=width,
                height=height,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
            ).images[0]
        buffered = io.BytesIO()
        image.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode("utf-8")


sd_engine = SDEngine()
