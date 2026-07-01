import os
import json
import threading
import numpy as np
import base64
import io
from PIL import Image
from rknnlite.api import RKNNLite


class RKNNModel:
    def __init__(self, path):
        self.rknn = RKNNLite()
        self.rknn.load_rknn(path)
        self.rknn.init_runtime(core_mask=RKNNLite.NPU_CORE_1_2)

    def __call__(self, x):
        return self.rknn.inference([x])


class SDEngine:
    def __init__(self):
        self.pipe = None
        self.lock = threading.Lock()

    def load(self):
        if self.pipe:
            return

        base = os.path.dirname(__file__)

        self.unet = RKNNModel(os.path.join(base, "unet.rknn"))
        self.vae = RKNNModel(os.path.join(base, "vae.rknn"))
        self.text = RKNNModel(os.path.join(base, "text.rknn"))

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


sd_engine = SDEngine()