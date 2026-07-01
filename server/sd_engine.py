import os
import json
import threading
import glob
import numpy as np
import base64
import io
from PIL import Image
from rknnlite.api import RKNNLite


SERVER_DIR = os.path.dirname(__file__)
WORKSPACE_DIR = os.path.abspath(os.path.join(SERVER_DIR, "..", ".."))
SD_DIR = os.environ.get("TONGFLY_SD_DIR", os.path.join(WORKSPACE_DIR, "SD"))


def resolve_model_path(env_name, candidates, pattern):
    env_path = os.environ.get(env_name)
    if env_path:
        return env_path

    for path in candidates:
        if os.path.exists(path):
            return path

    matches = glob.glob(os.path.join(SD_DIR, pattern), recursive=True)
    return matches[0] if matches else candidates[0]


class RKNNModel:
    def __init__(self, path):
        self.rknn = RKNNLite()
        self.rknn.load_rknn(path)
        self.rknn.init_runtime(core_mask=RKNNLite.NPU_CORE_1_2)

    def __call__(self, x):
        return self.rknn.inference([x])

    def release(self):
        self.rknn.release()


class SDEngine:
    def __init__(self):
        self.pipe = None
        self.lock = threading.Lock()
        self.unet = None
        self.vae = None
        self.text = None
        self.loading = False
        self.last_error = None

    def load(self):
        if self.pipe:
            return

        self.loading = True
        self.last_error = None
        try:
            unet_path = resolve_model_path(
                "TONGFLY_SD_UNET",
                [os.path.join(SD_DIR, "unet", "unet.rknn"), os.path.join(SD_DIR, "unet.rknn")],
                os.path.join("unet", "**", "*.rknn"),
            )
            vae_path = resolve_model_path(
                "TONGFLY_SD_VAE",
                [os.path.join(SD_DIR, "vae_decoder", "vae_decoder.rknn"), os.path.join(SD_DIR, "vae.rknn")],
                os.path.join("vae_decoder", "**", "*.rknn"),
            )
            text_path = resolve_model_path(
                "TONGFLY_SD_TEXT",
                [os.path.join(SD_DIR, "text_encoder", "text_encoder.rknn"), os.path.join(SD_DIR, "text.rknn")],
                os.path.join("text_encoder", "**", "*.rknn"),
            )

            for path in (unet_path, vae_path, text_path):
                if not os.path.exists(path):
                    raise FileNotFoundError(f"Missing SD dependency: {path}")

            self.unet = RKNNModel(unet_path)
            self.vae = RKNNModel(vae_path)
            self.text = RKNNModel(text_path)
            self.pipe = True
        except Exception as exc:
            self.last_error = str(exc)
            self.release()
            raise
        finally:
            self.loading = False

    def generate(self, prompt, width, height, steps, guidance):
        self.load()

        with self.lock:
            latents = np.random.randn(1, 4, height//8, width//8).astype(np.float32)

            text_emb = self.text(prompt)

            for _ in range(steps):
                noise = self.unet(latents)[0]
                latents = latents - noise * guidance

            img = self.vae(latents)[0]
            img = (img * 255).clip(0, 255).astype(np.uint8)

            im = Image.fromarray(img[0])
            buf = io.BytesIO()
            im.save(buf, format="PNG")

            return base64.b64encode(buf.getvalue()).decode()

    def release(self):
        with self.lock:
            for model in (self.unet, self.vae, self.text):
                if model:
                    model.release()
            self.unet = None
            self.vae = None
            self.text = None
            self.pipe = None


sd_engine = SDEngine()
