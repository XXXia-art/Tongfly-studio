import os
from pathlib import Path

# ============================================================
# VLM (Qwen2-VL 2B) — Vision via rknnlite, LLM via ctypes+librkllmrt.so
# ============================================================
QWEN2VL_DIR = Path(os.getenv("QWEN2VL_DIR", "/home/elf/QWEN2-VL"))
VLM_VISION_MODEL = os.getenv(
    "VLM_VISION_MODEL",
    str(QWEN2VL_DIR / "qwen2_vl_2b_vision_rk3588.rknn"),
)
VLM_LLM_MODEL = os.getenv(
    "VLM_LLM_MODEL",
    str(QWEN2VL_DIR / "Qwen2-VL-2B-Instruct.rkllm"),
)
RKLLM_LIB = os.getenv("RKLLM_LIB", "/home/elf/librkllmrt.so")

# VLM generation params
VLM_MAX_NEW_TOKENS = int(os.getenv("VLM_MAX_NEW_TOKENS", "256"))
VLM_MAX_CONTEXT_LEN = int(os.getenv("VLM_MAX_CONTEXT_LEN", "512"))

# ============================================================
# SD (Stable Diffusion v1.5 LCM) — all three components via rknnlite
# ============================================================
SD_DIR = Path(os.getenv("SD_DIR", "/home/elf/SD"))
SD_TEXT_ENCODER_DIR = os.getenv(
    "SD_TEXT_ENCODER_DIR", str(SD_DIR / "text_encoder")
)
SD_UNET_DIR = os.getenv("SD_UNET_DIR", str(SD_DIR / "unet"))
SD_VAE_DECODER_DIR = os.getenv(
    "SD_VAE_DECODER_DIR", str(SD_DIR / "vae_decoder")
)
SD_SCHEDULER_CONFIG = os.getenv(
    "SD_SCHEDULER_CONFIG", str(SD_DIR / "scheduler" / "scheduler_config.json")
)
SD_CLIP_TOKENIZER = os.getenv(
    "SD_CLIP_TOKENIZER", str(SD_DIR / "clip_tokenizer")
)

# SD generation defaults (LCM: fewer steps, lower resolution)
SD_DEFAULT_WIDTH = int(os.getenv("SD_DEFAULT_WIDTH", "256"))
SD_DEFAULT_HEIGHT = int(os.getenv("SD_DEFAULT_HEIGHT", "256"))
SD_DEFAULT_STEPS = int(os.getenv("SD_DEFAULT_STEPS", "4"))
SD_DEFAULT_GUIDANCE_SCALE = float(os.getenv("SD_DEFAULT_GUIDANCE_SCALE", "8.5"))

# ============================================================
# Server
# ============================================================
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
