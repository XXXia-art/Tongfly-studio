import base64
import ctypes
import logging
import threading
import os
import numpy as np
import cv2
from rknnlite.api import RKNNLite

logger = logging.getLogger(__name__)

SERVER_DIR = os.path.dirname(__file__)
WORKSPACE_DIR = os.path.abspath(os.path.join(SERVER_DIR, "..", ".."))
QWEN_DIR = os.environ.get("TONGFLY_QWEN_DIR", os.path.join(WORKSPACE_DIR, "QWEN2-VL"))

VISION_MODEL = os.environ.get(
    "TONGFLY_VISION_MODEL",
    os.path.join(QWEN_DIR, "qwen2_vl_2b_vision_rk3588.rknn"),
)
LLM_MODEL = os.environ.get(
    "TONGFLY_LLM_MODEL",
    os.path.join(QWEN_DIR, "Qwen2-VL-2B-Instruct.rkllm"),
)
RKLLM_LIB_CANDIDATES = [
    os.environ.get("TONGFLY_RKLLM_LIB"),
    os.path.join(QWEN_DIR, "install", "demo_Linux_aarch64", "lib", "librkllmrt.so"),
    "/home/elf/librkllmrt.so",
]
RKLLM_LIB = next((path for path in RKLLM_LIB_CANDIDATES if path and os.path.exists(path)), RKLLM_LIB_CANDIDATES[1])


def get_npu_core_mask():
    env_value = os.environ.get("TONGFLY_NPU_CORE_MASK")
    if env_value:
        return int(env_value, 0)

    for name in ("NPU_CORE_1_2", "NPU_CORE_0_1", "NPU_CORE_0"):
        if hasattr(RKNNLite, name):
            return getattr(RKNNLite, name)
    return None


class VisionEncoder:
    def __init__(self, path):
        self.rknn = RKNNLite()
        self.rknn.load_rknn(path)
        core_mask = get_npu_core_mask()
        if core_mask is None:
            self.rknn.init_runtime()
        else:
            self.rknn.init_runtime(core_mask=core_mask)

    def encode(self, img):
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = cv2.resize(img, (392, 392))
        img = np.expand_dims(img.astype(np.float32) / 255.0, 0)
        return self.rknn.inference([img])[0].flatten()

    def release(self):
        self.rknn.release()


class LLMEngine:
    def __init__(self, model_path):
        self.lock = threading.Lock()
        self.lib = ctypes.CDLL(RKLLM_LIB)
        self.handle = ctypes.c_void_p()

        self._text = []
        self._done = False

        def cb(result, ud, state):
            if state == 2:
                self._done = True
            elif state == 0 and result:
                try:
                    self._text.append(result.contents.text.decode())
                except:
                    pass

        self.callback = ctypes.CFUNCTYPE(None, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_int)(cb)

        class Param(ctypes.Structure):
            _fields_ = [
                ("model_path", ctypes.c_char_p),
                ("max_context_len", ctypes.c_int),
                ("max_new_tokens", ctypes.c_int),
                ("top_k", ctypes.c_int),
                ("top_p", ctypes.c_float),
                ("temperature", ctypes.c_float),
                ("repeat_penalty", ctypes.c_float),
                ("frequency_penalty", ctypes.c_float),
                ("presence_penalty", ctypes.c_float),
                ("mirostat", ctypes.c_int),
                ("mirostat_tau", ctypes.c_float),
                ("mirostat_eta", ctypes.c_float),
                ("skip_special_token", ctypes.c_bool),
                ("is_async", ctypes.c_bool),
                ("img_start", ctypes.c_char_p),
                ("img_end", ctypes.c_char_p),
                ("img_content", ctypes.c_char_p),
            ]

        self.param = Param()
        self.param.model_path = model_path.encode()
        self.param.max_context_len = 512
        self.param.max_new_tokens = 512
        self.param.top_k = 1
        self.param.top_p = 0.95
        self.param.temperature = 0.7

        self.lib.rkllm_init(ctypes.byref(self.handle), ctypes.byref(self.param), self.callback)
        self.fn_run = self.lib.rkllm_run
        self.fn_destroy = self.lib.rkllm_destroy

    def chat(self, text):
        with self.lock:
            self._text = []
            self._done = False
            inp = ctypes.c_char_p(text.encode())
            self.fn_run(self.handle, inp, None)

            while not self._done:
                pass

            return "".join(self._text)

    def release(self):
        self.fn_destroy(self.handle)


class VLMEngine:
    def __init__(self):
        self.vision = None
        self.llm = None
        self.lock = threading.Lock()
        self.loading = False
        self.last_error = None

    def load(self):
        if self.vision:
            return
        self.loading = True
        self.last_error = None
        try:
            for path in (VISION_MODEL, LLM_MODEL, RKLLM_LIB):
                if not os.path.exists(path):
                    raise FileNotFoundError(f"Missing VLM dependency: {path}")
            self.vision = VisionEncoder(VISION_MODEL)
            self.llm = LLMEngine(LLM_MODEL)
        except Exception as exc:
            self.last_error = str(exc)
            logger.exception("Failed to load VLM")
            self.release()
            raise
        finally:
            self.loading = False

    def chat(self, text):
        self.load()
        with self.lock:
            return self.llm.chat(text)

    def release(self):
        with self.lock:
            if self.vision:
                self.vision.release()
                self.vision = None
            if self.llm:
                self.llm.release()
                self.llm = None


vlm_engine = VLMEngine()
