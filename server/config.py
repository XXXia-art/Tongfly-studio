import os
from pathlib import Path


def _find_model_weight_dir():
    """Search upward from this file for a directory named model-weight that
    contains both VLM and SD subdirectories."""
    start = Path(__file__).resolve().parent
    for parent in [start, *start.parents]:
        candidate = parent / "model-weight"
        if (candidate / "VLM").exists() and (candidate / "SD").exists():
            return candidate
    # Fallback: one level above server/ (legacy layout when server lived next to model-weight)
    return start.parent / "model-weight"


MODEL_WEIGHT_DIR = Path(os.getenv("MODEL_WEIGHT_DIR", str(_find_model_weight_dir())))

VLM_MODEL_PATH = os.getenv("VLM_MODEL_PATH", str(MODEL_WEIGHT_DIR / "VLM"))
SD_MODEL_PATH = os.getenv(
    "SD_MODEL_PATH", str(MODEL_WEIGHT_DIR / "SD" / "v1-5-pruned-emaonly.safetensors")
)

VLM_DEVICE = os.getenv("VLM_DEVICE", "cuda:0")
SD_DEVICE = os.getenv("SD_DEVICE", "cuda:1")

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# SD generation defaults
SD_DEFAULT_WIDTH = int(os.getenv("SD_DEFAULT_WIDTH", "512"))
SD_DEFAULT_HEIGHT = int(os.getenv("SD_DEFAULT_HEIGHT", "512"))
SD_DEFAULT_STEPS = int(os.getenv("SD_DEFAULT_STEPS", "25"))
SD_DEFAULT_GUIDANCE_SCALE = float(os.getenv("SD_DEFAULT_GUIDANCE_SCALE", "7.5"))

# VLM generation defaults
VLM_MAX_NEW_TOKENS = int(os.getenv("VLM_MAX_NEW_TOKENS", "256"))
VLM_DO_SAMPLE = os.getenv("VLM_DO_SAMPLE", "true").lower() in ("1", "true", "yes")
