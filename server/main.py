import logging
import threading
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from vlm_engine import vlm_engine
from sd_engine import sd_engine

logging.basicConfig(level=logging.INFO)

vlm_lock = threading.Lock()
sd_lock = threading.Lock()
model_memory_lock = threading.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info("Preloading VLM on startup ...")
    try:
        with model_memory_lock:
            sd_engine.release()
            vlm_engine.load()
        logging.info("VLM preload complete")
    except Exception:
        logging.exception("VLM preload failed")
    yield
    logging.info("Releasing models on shutdown ...")
    with model_memory_lock:
        sd_engine.release()
        vlm_engine.release()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def ensure_vlm_active():
    if vlm_engine.vision is not None:
        return
    logging.info("Switching active model to VLM ...")
    sd_engine.release()
    vlm_engine.load()


def ensure_sd_active():
    if sd_engine.pipe is not None:
        return
    logging.info("Switching active model to SD ...")
    vlm_engine.release()
    sd_engine.load()


@app.get("/health")
def health():
    return {
        "vlm": vlm_engine.vision is not None,
        "vlm_loading": vlm_engine.loading,
        "vlm_error": vlm_engine.last_error,
        "sd": sd_engine.pipe is not None,
        "sd_loading": sd_engine.loading,
        "sd_error": sd_engine.last_error,
    }


def run_vlm_chat(req: dict):
    try:
        text = req.get("text")
        if not text:
            raise HTTPException(400, "Missing text")
        with model_memory_lock:
            ensure_vlm_active()
            with vlm_lock:
                result = vlm_engine.chat(text)
        return {"result": result, "response": result}
    except Exception as e:
        logging.exception("VLM chat failed")
        raise HTTPException(500, str(e))


def run_vlm_describe(req: dict):
    try:
        question = req.get("question") or req.get("text") or "请描述当前画面。"
        with model_memory_lock:
            ensure_vlm_active()
            with vlm_lock:
                result = vlm_engine.describe(question, req.get("image_base64"))
        return {"result": result, "response": result}
    except Exception as e:
        logging.exception("VLM describe failed")
        raise HTTPException(500, str(e))


def run_sd_generate(req: dict):
    try:
        with model_memory_lock:
            ensure_sd_active()
            with sd_lock:
                img = sd_engine.generate(
                    req["prompt"],
                    req.get("width", 512),
                    req.get("height", 512),
                    req.get("steps", req.get("num_inference_steps", 4)),
                    req.get("guidance", req.get("guidance_scale", 7.5)),
                )
        return {"image": img, "image_base64": img}
    except Exception as e:
        logging.exception("SD generate failed")
        raise HTTPException(500, str(e))


@app.post("/vlm/chat")
@app.post("/api/vlm/chat")
def vlm_chat(req: dict):
    return run_vlm_chat(req)


@app.post("/vlm/describe")
@app.post("/api/vlm/describe")
def vlm_describe(req: dict):
    return run_vlm_describe(req)


@app.post("/sd/generate")
@app.post("/api/sd/generate")
def sd_generate(req: dict):
    return run_sd_generate(req)


if __name__ == "__main__":

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        workers=1,
        log_config=None,
        access_log=False,
    )
