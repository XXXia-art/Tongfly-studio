import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from config import HOST, PORT
from models import (
    VlmChatRequest,
    VlmDescribeRequest,
    VlmResponse,
    SdGenerateRequest,
    SdResponse,
)

from vlm_engine import vlm_engine
from sd_engine import sd_engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)

# ============================================================
# 🔒 RK3588 全局锁（关键：防止NPU/显存并发炸）
# ============================================================
vlm_lock = threading.Lock()
sd_lock = threading.Lock()


# ============================================================
# 生命周期加载
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting RK3588 inference server...")

    # preload VLM
    try:
        vlm_engine.load()
        logger.info("VLM loaded")
    except Exception as e:
        logger.error(f"VLM preload failed: {e}")

    # preload SD（可选，也可以延迟加载）
    try:
        sd_engine.load()
        logger.info("SD loaded")
    except Exception as e:
        logger.error(f"SD preload failed: {e}")

    yield

    logger.info("Shutting down server...")


# ============================================================
# FastAPI
# ============================================================
app = FastAPI(
    title="RK3588 Inference Server",
    description="VLM + Stable Diffusion (RKNN + RKLLM)",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# Health check
# ============================================================
@app.get("/health")
def health():
    return {
        "status": "ok",
        "vlm_ready": vlm_engine.vision is not None and vlm_engine.llm is not None,
        "sd_ready": getattr(sd_engine, "pipe", None) is not None,
    }


# ============================================================
# VLM chat（加锁）
# ============================================================
@app.post("/api/vlm/chat", response_model=VlmResponse)
def vlm_chat(req: VlmChatRequest):
    try:
        with vlm_lock:
            response = vlm_engine.chat(req.text)
        return VlmResponse(response=response)

    except Exception as e:
        logger.exception("VLM chat failed")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# VLM describe（加锁）
# ============================================================
@app.post("/api/vlm/describe", response_model=VlmResponse)
def vlm_describe(req: VlmDescribeRequest):
    try:
        with vlm_lock:
            response = vlm_engine.describe(req.question, req.image_base64)
        return VlmResponse(response=response)

    except Exception as e:
        logger.exception("VLM describe failed")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# SD generate（RK3588关键：必须串行）
# ============================================================
@app.post("/api/sd/generate", response_model=SdResponse)
def sd_generate(req: SdGenerateRequest):
    try:
        with sd_lock:
            # RK3588 SD 不支持 negative_prompt（避免无效参数）
            image_base64 = sd_engine.generate(
                prompt=req.prompt,
                width=req.width,
                height=req.height,
                num_inference_steps=req.num_inference_steps,
                guidance_scale=req.guidance_scale,
            )

        return SdResponse(image_base64=image_base64)

    except Exception as e:
        logger.exception("SD generation failed")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        log_level="info",
        workers=1,   # 🔥 RK3588必须单worker
    )