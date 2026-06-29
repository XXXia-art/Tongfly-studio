from typing import Optional
from pydantic import BaseModel, Field


class VlmChatRequest(BaseModel):
    text: str = Field(..., min_length=1, description="纯文本对话内容")


class VlmDescribeRequest(BaseModel):
    question: str = Field(..., min_length=1, description="关于图像的问题")
    image_base64: Optional[str] = Field(None, description="图像的 base64 数据（含或不含 data:image 前缀）")


class VlmResponse(BaseModel):
    response: str


class SdGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="文生图提示词")
    negative_prompt: Optional[str] = Field("", description="负面提示词")
    width: Optional[int] = Field(512, ge=256, le=1024)
    height: Optional[int] = Field(512, ge=256, le=1024)
    num_inference_steps: Optional[int] = Field(25, ge=1, le=100)
    guidance_scale: Optional[float] = Field(7.5, ge=1.0, le=20.0)


class SdResponse(BaseModel):
    image_base64: str
