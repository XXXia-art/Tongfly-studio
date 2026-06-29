import base64
import io
import logging
import re
from typing import Optional

from PIL import Image
from transformers import AutoProcessor, Qwen2VLForConditionalGeneration
from qwen_vl_utils import process_vision_info
import torch

from config import VLM_DEVICE, VLM_MODEL_PATH, VLM_MAX_NEW_TOKENS, VLM_DO_SAMPLE

logger = logging.getLogger(__name__)


class VLMEngine:
    def __init__(self):
        self.model = None
        self.processor = None
        self.device = VLM_DEVICE
        self.model_path = VLM_MODEL_PATH

    def load(self):
        if self.model is not None:
            return
        logger.info(f"Loading VLM from {self.model_path} to {self.device} ...")
        self.processor = AutoProcessor.from_pretrained(self.model_path, trust_remote_code=True)
        self.model = Qwen2VLForConditionalGeneration.from_pretrained(
            self.model_path,
            torch_dtype=torch.bfloat16,
            device_map=self.device,
            trust_remote_code=True,
        )
        self.model.eval()
        logger.info("VLM loaded.")

    def _decode_image(self, image_base64: Optional[str]) -> Optional[Image.Image]:
        if not image_base64:
            return None
        # Strip data URI prefix if present
        data = re.sub(r"^data:image/[^;]+;base64,", "", image_base64)
        try:
            raw = base64.b64decode(data)
            return Image.open(io.BytesIO(raw)).convert("RGB")
        except Exception as exc:
            logger.warning(f"Failed to decode image: {exc}")
            return None

    def _build_messages(self, text: str, image: Optional[Image.Image] = None):
        if image is not None:
            content = [
                {"type": "image", "image": image},
                {"type": "text", "text": text},
            ]
        else:
            content = [{"type": "text", "text": text}]
        return [{"role": "user", "content": content}]

    def _generate(self, messages) -> str:
        self.load()
        text = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = self.processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        )
        inputs = inputs.to(self.device)

        with torch.no_grad():
            generated_ids = self.model.generate(
                **inputs,
                max_new_tokens=VLM_MAX_NEW_TOKENS,
                do_sample=VLM_DO_SAMPLE,
            )
        generated_ids_trimmed = [
            out_ids[len(in_ids):]
            for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
        ]
        output_text = self.processor.batch_decode(
            generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )[0]
        return output_text.strip()

    def chat(self, text: str) -> str:
        messages = self._build_messages(text)
        return self._generate(messages)

    def describe(self, question: str, image_base64: Optional[str] = None) -> str:
        image = self._decode_image(image_base64)
        messages = self._build_messages(question, image)
        return self._generate(messages)


vlm_engine = VLMEngine()
