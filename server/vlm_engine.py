import base64
import ctypes
import logging
import threading
import os
import time
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

MAX_NEW_TOKENS = 512
MAX_CONTEXT_LEN = 512
TOP_K = 1
TOP_P = 0.95
TEMPERATURE = 0.8
REPEAT_PENALTY = 1.1
FREQUENCY_PENALTY = 0.0
PRESENCE_PENALTY = 0.0

PROMPT_PREFIX = "<|im_start|>system\nYou are a helpful assistant.<|im_end|>\n<|im_start|>user\n"
PROMPT_SUFFIX = "<|im_end|>\n<|im_start|>assistant\n"

IMG_START = b"<|vision_start|>"
IMG_END = b"<|vision_end|>"
IMG_CONTENT = b"<|image_pad|>"

IMAGE_SIZE = 392
N_IMAGE_TOKENS = 196

RKLLM_RUN_NORMAL = 0
RKLLM_RUN_FINISH = 2
RKLLM_RUN_ERROR = 3

RKLLM_INPUT_PROMPT = 0
RKLLM_INPUT_MULTIMODAL = 3
RKLLM_INFER_GENERATE = 0


def get_npu_core_mask():
    env_value = os.environ.get("TONGFLY_NPU_CORE_MASK")
    if env_value:
        return int(env_value, 0)

    for name in ("NPU_CORE_AUTO", "NPU_CORE_1_2", "NPU_CORE_0_1", "NPU_CORE_0"):
        if hasattr(RKNNLite, name):
            return getattr(RKNNLite, name)
    return None


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


class RKLLMResultLastHiddenLayer(ctypes.Structure):
    _fields_ = [
        ("hidden_states", ctypes.POINTER(ctypes.c_float)),
        ("embd_size", ctypes.c_int),
        ("num_tokens", ctypes.c_int),
    ]


class RKLLMResult(ctypes.Structure):
    _fields_ = [
        ("text", ctypes.c_char_p),
        ("token_id", ctypes.c_int32),
        ("last_hidden_layer", RKLLMResultLastHiddenLayer),
    ]


CallbackType = ctypes.CFUNCTYPE(
    None,
    ctypes.POINTER(RKLLMResult),
    ctypes.c_void_p,
    ctypes.c_int,
)


class VisionEncoder:
    def __init__(self, path):
        self.rknn = RKNNLite()
        ret = self.rknn.load_rknn(path)
        if ret != 0:
            raise RuntimeError(f"Failed to load vision RKNN model: {path}")
        core_mask = get_npu_core_mask()
        if core_mask is None:
            ret = self.rknn.init_runtime()
        else:
            ret = self.rknn.init_runtime(core_mask=core_mask)
        if ret != 0:
            raise RuntimeError("Failed to initialize vision RKNN runtime")

    def preprocess(self, img):
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w = img.shape[:2]
        size = max(w, h)
        square = np.full((size, size, 3), 127.5, dtype=np.float32)
        x_off = (size - w) // 2
        y_off = (size - h) // 2
        square[y_off:y_off + h, x_off:x_off + w] = img.astype(np.float32)
        resized = cv2.resize(square, (IMAGE_SIZE, IMAGE_SIZE), interpolation=cv2.INTER_LINEAR)
        return np.expand_dims(resized, axis=0)

    def encode(self, img):
        outputs = self.rknn.inference(inputs=[self.preprocess(img)])
        return outputs[0].astype(np.float32).flatten()

    def release(self):
        self.rknn.release()


class LLMEngine:
    def __init__(self, model_path):
        self.lock = threading.Lock()
        self.lib = ctypes.CDLL(RKLLM_LIB)
        self.handle = ctypes.c_void_p()

        self._text = []
        self._done = threading.Event()

        def cb(result, ud, state):
            if state == RKLLM_RUN_FINISH:
                self._done.set()
            elif state == RKLLM_RUN_ERROR:
                self._text.append("\n[ERROR]")
                self._done.set()
            elif state == RKLLM_RUN_NORMAL and result and result.contents.text:
                decoded = result.contents.text.decode("utf-8", errors="replace")
                self._text.append(decoded)

        self.callback = CallbackType(cb)

        self.param = RKLLMParam()
        self.param.model_path = model_path.encode("utf-8")
        self.param.max_context_len = MAX_CONTEXT_LEN
        self.param.max_new_tokens = MAX_NEW_TOKENS
        self.param.top_k = TOP_K
        self.param.top_p = TOP_P
        self.param.temperature = TEMPERATURE
        self.param.repeat_penalty = REPEAT_PENALTY
        self.param.frequency_penalty = FREQUENCY_PENALTY
        self.param.presence_penalty = PRESENCE_PENALTY
        self.param.mirostat = 0
        self.param.mirostat_tau = 5.0
        self.param.mirostat_eta = 0.1
        self.param.skip_special_token = False
        self.param.is_async = False
        self.param.img_start = IMG_START
        self.param.img_end = IMG_END
        self.param.img_content = IMG_CONTENT
        self.param.extend_param.base_domain_id = 0

        self.fn_init = self.lib.rkllm_init
        self.fn_init.argtypes = [
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(RKLLMParam),
            CallbackType,
        ]
        self.fn_init.restype = ctypes.c_int

        ret = self.fn_init(ctypes.byref(self.handle), ctypes.byref(self.param), self.callback)
        if ret != 0:
            raise RuntimeError(f"rkllm_init failed with code {ret}")

        self.fn_run = self.lib.rkllm_run
        self.fn_run.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(RKLLMInput),
            ctypes.POINTER(RKLLMInferParam),
            ctypes.c_void_p,
        ]
        self.fn_run.restype = ctypes.c_int

        self.fn_destroy = self.lib.rkllm_destroy
        self.fn_destroy.argtypes = [ctypes.c_void_p]
        self.fn_destroy.restype = ctypes.c_int

    def _run(self, rkllm_input):
        infer_param = RKLLMInferParam()
        ctypes.memset(ctypes.byref(infer_param), 0, ctypes.sizeof(RKLLMInferParam))
        infer_param.mode = RKLLM_INFER_GENERATE

        ret = self.fn_run(self.handle, ctypes.byref(rkllm_input), ctypes.byref(infer_param), None)
        if ret != 0:
            raise RuntimeError(f"rkllm_run failed with code {ret}")

        while not self._done.is_set():
            time.sleep(0.01)

        return "".join(self._text)

    def chat(self, text):
        with self.lock:
            self._text = []
            self._done.clear()

            full = f"{PROMPT_PREFIX}{text}{PROMPT_SUFFIX}"
            inp = RKLLMInput()
            inp.input_type = RKLLM_INPUT_PROMPT
            prompt_bytes = full.encode("utf-8")
            inp.input_data.prompt_input = prompt_bytes
            inp._prompt_bytes = prompt_bytes

            return self._run(inp)

    def chat_multimodal(self, text, image_embed):
        with self.lock:
            self._text = []
            self._done.clear()

            full = f"{PROMPT_PREFIX}{text}{PROMPT_SUFFIX}"
            inp = RKLLMInput()
            inp.input_type = RKLLM_INPUT_MULTIMODAL
            prompt_bytes = full.encode("utf-8")
            inp.input_data.multimodal_input.prompt = prompt_bytes
            inp.input_data.multimodal_input.n_image_tokens = N_IMAGE_TOKENS
            inp.input_data.multimodal_input.image_embed = image_embed.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
            inp._prompt_bytes = prompt_bytes
            inp._image_embed = image_embed

            return self._run(inp)

    def release(self):
        if self.handle:
            self.fn_destroy(self.handle)
            self.handle = None


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
