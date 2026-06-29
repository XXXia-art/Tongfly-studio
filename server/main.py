import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from config import HOST, PORT
from models import VlmChatRequest, VlmDescribeRequest, VlmResponse, SdGenerateRequest, SdResponse
from vlm_engine import vlm_engine
from sd_engine import sd_engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting inference server...")
    # Preload models on startup to make first requests faster.
    try:
        vlm_engine.load()
    except Exception as exc:
        logger.error(f"Failed to preload VLM: {exc}")
    try:
        sd_engine.load()
    except Exception as exc:
        logger.error(f"Failed to preload SD: {exc}")
    yield
    logger.info("Shutting down inference server...")


app = FastAPI(
    title="Tongfly Studio Inference Server",
    description="Server-side inference for Qwen2-VL and Stable Diffusion v1.5",
    version="0.1.0",
    lifespan=lifespan,
)

# Allow cross-origin requests from any origin so local PC frontend can connect.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "vlm_ready": vlm_engine.model is not None,
        "sd_ready": sd_engine.pipe is not None,
    }


@app.post("/api/vlm/chat", response_model=VlmResponse)
def vlm_chat(req: VlmChatRequest):
    try:
        response = vlm_engine.chat(req.text)
        return VlmResponse(response=response)
    except Exception as exc:
        logger.exception("VLM chat failed")
        raise HTTPException(status_code=500, detail=f"VLM inference error: {exc}")


@app.post("/api/vlm/describe", response_model=VlmResponse)
def vlm_describe(req: VlmDescribeRequest):
    try:
        response = vlm_engine.describe(req.question, req.image_base64)
        return VlmResponse(response=response)
    except Exception as exc:
        logger.exception("VLM describe failed")
        raise HTTPException(status_code=500, detail=f"VLM inference error: {exc}")


@app.post("/api/sd/generate", response_model=SdResponse)
def sd_generate(req: SdGenerateRequest):
    try:
        image_base64 = sd_engine.generate(
            prompt=req.prompt,
            negative_prompt=req.negative_prompt or "",
            width=req.width,
            height=req.height,
            num_inference_steps=req.num_inference_steps,
            guidance_scale=req.guidance_scale,
        )
        return SdResponse(image_base64=image_base64)
    except Exception as exc:
        logger.exception("SD generation failed")
        raise HTTPException(status_code=500, detail=f"SD inference error: {exc}")


if __name__ == "__main__":
    uvicorn.run("main:app", host=HOST, port=PORT, log_level="info")
