import logging
import threading
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from vlm_engine import vlm_engine
from sd_engine import sd_engine

logging.basicConfig(level=logging.INFO)

app = FastAPI()

vlm_lock = threading.Lock()
sd_lock = threading.Lock()
model_memory_lock = threading.Lock()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def preload_vlm():
    logging.info("Preloading VLM on startup ...")
    try:
        with model_memory_lock:
            sd_engine.release()
            vlm_engine.load()
        logging.info("VLM preload complete")
    except Exception:
        logging.exception("VLM preload failed")


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
        "sd": sd_engine.pipe is not None,
    }


@app.post("/vlm/chat")
def vlm_chat(req: dict):
    try:
        with model_memory_lock:
            ensure_vlm_active()
            with vlm_lock:
                return {"result": vlm_engine.chat(req["text"])}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/sd/generate")
def sd_generate(req: dict):
    try:
        with model_memory_lock:
            ensure_sd_active()
            with sd_lock:
                img = sd_engine.generate(
                    req["prompt"],
                    req.get("width", 512),
                    req.get("height", 512),
                    req.get("steps", 4),
                    req.get("guidance", 7.5),
                )
        return {"image": img}
    except Exception as e:
        raise HTTPException(500, str(e))


if __name__ == "__main__":

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        workers=1,
        log_config=None
    )
