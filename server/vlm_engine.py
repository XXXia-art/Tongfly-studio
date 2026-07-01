"""
Qwen2-VL 2B engine for RK3588.
Vision encoder → rknnlite (NPU cores 1+2)
LLM body → ctypes + librkllmrt.so (NPU)
"""

import base64
import ctypes
import io
import logging
import re
import threading
import time
from typing import Optional

import cv2
import numpy as np
from rknnlite.api import RKNNLite

from config import (
    RKLLM_LIB,
    VLM_MAX_CONTEXT_LEN,
    VLM_MAX_NEW_TOKENS,
    VLM_LLM_MODEL,
    VLM_VISION_MODEL,
)

logger = logging.getLogger(__name__)

# ============================================================
# Vision Encoder constants (must match C++ demo / model export)
# ============================================================
IMAGE_SIZE = 392
N_IMAGE_TOKENS = 196
IMAGE_EMBED_LEN = 1536

# Qwen2-VL chat template
PROMPT_PREFIX = "<|im_start|>system\nYou are a helpful assistant.<|im_end|>\n<|im_start|>user\n"
PROMPT_SUFFIX = "<|im_end|>\n<|im_start|>assistant\n"

IMG_START = b"<|vision_start|>"
IMG_END = b"<|vision_end|>"
IMG_CONTENT = b"<|image_pad|>"

# ============================================================
# rkllm ctypes setup
# ============================================================
_rkllm_lib = ctypes.CDLL(RKLLM_LIB)

RKLLM_RUN_NORMAL = 0
RKLLM_RUN_FINISH = 2
RKLLM_RUN_ERROR = 3

RKLLM_INPUT_PROMPT = 0
RKLLM_INPUT_MULTIMODAL = 3
RKLLM_INFER_GENERATE = 0


class RKLLMExtendParam(ctypes.Structure):
    _fields_ = [
        ("base_domain_id", ctypes.c_int32),
        ("reserved", ctypes.c_uint8 * 112),
    ]


class RKLLMParam(ctypes.Structure):
    _fields_ = [
        ("model_path", ctypes.c_char_p),
        ("max_context_len", ctypes.c_int32),
        ("max_new_tokens", ctypes.c_int32),
        ("top_k", ctypes.c_int32),
        ("top_p", ctypes.c_float),
        ("temperature", ctypes.c_float),
        ("repeat_penalty", ctypes.c_float),
        ("frequency_penalty", ctypes.c_float),
        ("presence_penalty", ctypes.c_float),
        ("mirostat", ctypes.c_int32),
        ("mirostat_tau", ctypes.c_float),
        ("mirostat_eta", ctypes.c_float),
        ("skip_special_token", ctypes.c_bool),
        ("is_async", ctypes.c_bool),
        ("img_start", ctypes.c_char_p),
        ("img_end", ctypes.c_char_p),
        ("img_content", ctypes.c_char_p),
        ("extend_param", RKLLMExtendParam),
    ]


class RKLLMMultiModelInput(ctypes.Structure):
    _fields_ = [
        ("prompt", ctypes.c_char_p),
        ("image_embed", ctypes.POINTER(ctypes.c_float)),
        ("n_image_tokens", ctypes.c_size_t),
    ]


class RKLLMInputUnion(ctypes.Union):
    _fields_ = [
        ("prompt_input", ctypes.c_char_p),
        ("embed_input", ctypes.c_ubyte * 16),
        ("token_input", ctypes.c_ubyte * 16),
        ("multimodal_input", RKLLMMultiModelInput),
    ]


class RKLLMInput(ctypes.Structure):
    _fields_ = [
        ("input_type", ctypes.c_int),
        ("input_data", RKLLMInputUnion),
    ]


class RKLLMInferParam(ctypes.Structure):
    _fields_ = [
        ("mode", ctypes.c_int),
        ("lora_params", ctypes.c_void_p),
        ("prompt_cache_params", ctypes.c_void_p),
    ]


class RKLLMResult(ctypes.Structure):
    _fields_ = [
        ("text", ctypes.c_char_p),
        ("token_id", ctypes.c_int32),
        ("last_hidden_layer", ctypes.c_void_p),
    ]


# ============================================================
# Vision Encoder (stateless, rknnlite)
# ============================================================
class VisionEncoder:
    def __init__(self, model_path: str):
        self.rknn = RKNNLite()
        ret = self.rknn.load_rknn(model_path)
        if ret != 0:
            raise RuntimeError(f"Failed to load vision RKNN model: {model_path}")
        # Use NPU core 1+2, leave core 0 for other tasks
        ret = self.rknn.init_runtime(core_mask=0b011)
        if ret != 0:
            raise RuntimeError("Vision RKNN init_runtime failed")
        logger.info("Vision encoder loaded (NPU core 1+2)")

    def preprocess(self, img_bgr: np.ndarray) -> np.ndarray:
        """BGR→RGB → expand2square(127.5) → resize 392 → NHWC → /255"""
        img = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        h, w = img.shape[:2]
        size = max(w, h)
        square = np.full((size, size, 3), 127.5, dtype=np.float32)
        x_off = (size - w) // 2
        y_off = (size - h) // 2
        square[y_off : y_off + h, x_off : x_off + w] = img.astype(np.float32)
        resized = cv2.resize(square, (IMAGE_SIZE, IMAGE_SIZE), interpolation=cv2.INTER_LINEAR)
        return np.expand_dims(resized, axis=0)

    def encode(self, img_bgr: np.ndarray) -> np.ndarray:
        """Return image_embed (np.float32, shape: [196*1536])"""
        blob = self.preprocess(img_bgr)
        outputs = self.rknn.inference(inputs=[blob])
        return outputs[0].astype(np.float32).flatten()

    def release(self):
        self.rknn.release()


# ============================================================
# LLM Engine (ctypes + librkllmrt.so, one instance with lock)
# ============================================================
class LLMEngine:
    def __init__(self, model_path: str):
        self._text_parts: list = []
        self._done: bool = False
        self._req_lock = threading.Lock()

        # Build callback that writes into this instance's state
        engine_ref = self

        @ctypes.CFUNCTYPE(None, ctypes.POINTER(RKLLMResult), ctypes.c_void_p, ctypes.c_int)
        def _callback(result_ptr, _userdata, state):
            if state == RKLLM_RUN_FINISH:
                engine_ref._done = True
            elif state == RKLLM_RUN_ERROR:
                engine_ref._done = True
            elif state == RKLLM_RUN_NORMAL:
                if result_ptr and result_ptr.contents.text:
                    try:
                        text = result_ptr.contents.text.decode("utf-8", errors="replace")
                    except Exception:
                        text = result_ptr.contents.text.decode("utf-8", errors="ignore")
                    engine_ref._text_parts.append(text)

        self._callback = _callback  # prevent GC

        param = RKLLMParam()
        param.model_path = model_path.encode("utf-8")
        param.max_context_len = VLM_MAX_CONTEXT_LEN
        param.max_new_tokens = VLM_MAX_NEW_TOKENS
        param.top_k = 1
        param.top_p = 0.95
        param.temperature = 0.8
        param.repeat_penalty = 1.1
        param.frequency_penalty = 0.0
        param.presence_penalty = 0.0
        param.mirostat = 0
        param.mirostat_tau = 5.0
        param.mirostat_eta = 0.1
        param.skip_special_token = False
        param.is_async = False
        param.img_start = IMG_START
        param.img_end = IMG_END
        param.img_content = IMG_CONTENT
        param.extend_param.base_domain_id = 0

        self.handle = ctypes.c_void_p()

        fn_init = _rkllm_lib.rkllm_init
        fn_init.argtypes = [
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(RKLLMParam),
            ctypes.CFUNCTYPE(None, ctypes.POINTER(RKLLMResult), ctypes.c_void_p, ctypes.c_int),
        ]
        fn_init.restype = ctypes.c_int
        ret = fn_init(ctypes.byref(self.handle), ctypes.byref(param), self._callback)
        if ret != 0:
            raise RuntimeError(f"rkllm_init failed, code: {ret}")

        self._fn_run = _rkllm_lib.rkllm_run
        self._fn_run.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(RKLLMInput),
            ctypes.POINTER(RKLLMInferParam),
            ctypes.c_void_p,
        ]
        self._fn_run.restype = ctypes.c_int

        self._fn_destroy = _rkllm_lib.rkllm_destroy
        self._fn_destroy.argtypes = [ctypes.c_void_p]
        self._fn_destroy.restype = ctypes.c_int

        logger.info("LLM engine initialised (rkllm)")

    def _run(self, rkllm_input: RKLLMInput) -> str:
        infer_param = RKLLMInferParam()
        ctypes.memset(ctypes.byref(infer_param), 0, ctypes.sizeof(RKLLMInferParam))
        infer_param.mode = RKLLM_INFER_GENERATE

        def _runner():
            self._fn_run(self.handle, ctypes.byref(rkllm_input), ctypes.byref(infer_param), None)

        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        t.join()

        while not self._done:
            time.sleep(0.01)

        return "".join(self._text_parts)

    def _reset_state(self):
        self._text_parts = []
        self._done = False

    def chat_text(self, prompt: str) -> str:
        """纯文本对话"""
        with self._req_lock:
            self._reset_state()
            full = f"{PROMPT_PREFIX}{prompt}{PROMPT_SUFFIX}"
            inp = RKLLMInput()
            inp.input_type = RKLLM_INPUT_PROMPT
            inp.input_data.prompt_input = full.encode("utf-8")
            return self._run(inp)

    def chat_multimodal(self, prompt: str, image_embed: np.ndarray) -> str:
        """多模态对话（图片 + 文本）"""
        if image_embed.dtype != np.float32:
            image_embed = image_embed.astype(np.float32)
        with self._req_lock:
            self._reset_state()
            full = f"{PROMPT_PREFIX}{prompt}{PROMPT_SUFFIX}"
            inp = RKLLMInput()
            inp.input_type = RKLLM_INPUT_MULTIMODAL
            inp.input_data.multimodal_input.prompt = full.encode("utf-8")
            inp.input_data.multimodal_input.n_image_tokens = N_IMAGE_TOKENS
            inp.input_data.multimodal_input.image_embed = image_embed.ctypes.data_as(
                ctypes.POINTER(ctypes.c_float)
            )
            return self._run(inp)

    def release(self):
        self._fn_destroy(self.handle)


# ============================================================
# Top-level VLM engine
# ============================================================
class VLMEngine:
    def __init__(self):
        self.vision: Optional[VisionEncoder] = None
        self.llm: Optional[LLMEngine] = None
        self._npui_lock = threading.Lock()

    def load(self):
        if self.vision is not None:
            return
        logger.info("Loading VLM (Qwen2-VL 2B) …")
        self.vision = VisionEncoder(VLM_VISION_MODEL)
        self.llm = LLMEngine(VLM_LLM_MODEL)
        logger.info("VLM ready")

    def _decode_image(self, image_base64: str) -> np.ndarray:
        """Decode base64 image (PNG/JPEG) to BGR numpy array for vision encoder."""
        data = re.sub(r"^data:image/[^;]+;base64,", "", image_base64)
        raw = base64.b64decode(data)
        img_array = np.frombuffer(raw, np.uint8)
        img_bgr = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if img_bgr is None:
            raise ValueError("Failed to decode image from base64")
        return img_bgr

    def chat(self, text: str) -> str:
        """纯文本对话（VLM 的文本模式）"""
        self.load()
        with self._npui_lock:
            return self.llm.chat_text(text)

    def describe(self, question: str, image_base64: Optional[str] = None) -> str:
        """多模态描述：可选图片 + 问题"""
        self.load()
        with self._npui_lock:
            if image_base64:
                img_bgr = self._decode_image(image_base64)
                embed = self.vision.encode(img_bgr)
                prompt = f"<image>{question}"
                return self.llm.chat_multimodal(prompt, embed)
            else:
                # 没有图片时用文本模式回答
                return self.llm.chat_text(question)

    def release(self):
        if self.vision:
            self.vision.release()
        if self.llm:
            self.llm.release()


vlm_engine = VLMEngine()
