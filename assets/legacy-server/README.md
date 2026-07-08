# Tongfly Studio 推理服务

为 `Tongfly-studio` 前端提供服务器端模型推理：

- **VLM**：`Qwen2-VL-2B-Instruct`（文本对话 + 图像理解）
- **SD**：`Stable Diffusion v1.5`（文生图）

## 环境

使用 conda 环境 `drone`：

```bash
conda activate drone
```

所需依赖已在该环境中安装，主要包括：

```text
torch torchvision transformers accelerate diffusers
fastapi uvicorn qwen-vl-utils pillow
```

如果在新机器上部署，可运行：

```bash
pip install -r requirements.txt
```

> 注意：本服务所在的机器无法访问 HuggingFace，因此 SD 所需的 CLIP tokenizer/config 已通过 `prepare_clip_local.py` 从 `openai-clip` 包生成到 `clip_local/` 目录，并在首次加载时自动写入本地 HF 缓存。

## 配置

可通过环境变量修改默认行为：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MODEL_WEIGHT_DIR` | 自动向上查找 `model-weight/` | 模型权重根目录 |
| `VLM_MODEL_PATH` | `<MODEL_WEIGHT_DIR>/VLM` | VLM 模型目录 |
| `SD_MODEL_PATH` | `<MODEL_WEIGHT_DIR>/SD/v1-5-pruned-emaonly.safetensors` | SD 权重文件 |
| `VLM_DEVICE` | `cuda:0` | VLM 使用的 GPU |
| `SD_DEVICE` | `cuda:1` | SD 使用的 GPU |
| `HOST` | `0.0.0.0` | 服务监听地址 |
| `PORT` | `8000` | 服务端口 |
| `VLM_MAX_NEW_TOKENS` | `256` | VLM 最大生成 token 数 |
| `SD_DEFAULT_STEPS` | `25` | SD 默认推理步数 |

## 启动

```bash
cd Tongfly-studio/server
conda activate drone
python main.py
```

启动后会自动加载两个模型（约 30–60 秒），然后监听 `http://0.0.0.0:8000`。

建议用 `nohup` 或 `tmux` 保持后台运行：

```bash
cd Tongfly-studio/server
nohup python main.py > server.log 2>&1 &
```

## API

### 健康检查

```http
GET /health
```

### VLM 文本对话

```http
POST /api/vlm/chat
Content-Type: application/json

{
  "text": "你好"
}
```

响应：

```json
{
  "response": "你好！有什么可以帮你的吗？"
}
```

### VLM 图像理解

```http
POST /api/vlm/describe
Content-Type: application/json

{
  "question": "画面里有什么？",
  "image_base64": "data:image/png;base64,iVBORw0KGgo..."
}
```

### SD 文生图

```http
POST /api/sd/generate
Content-Type: application/json

{
  "prompt": "a drone flying over a playground",
  "width": 512,
  "height": 512,
  "num_inference_steps": 25,
  "guidance_scale": 7.5
}
```

响应：

```json
{
  "image_base64": "iVBORw0KGgo..."
}
```

## 前端连接

前端代码已改为调用服务端 API。

- 若前端在服务器本机开发：Vite 代理会自动转发 `/api` 到 `http://localhost:8000`。
- 若前端在本地 PC：需设置环境变量指向服务器：

```bash
# 在本地 PC 启动前端时
VITE_API_BASE_URL=http://10.65.14.8:8000 npm run dev
```

或者在 `.env.local` 中写入：

```text
VITE_API_BASE_URL=http://10.65.14.8:8000
```
