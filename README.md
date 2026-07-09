# 童飞工坊 · Tongfly

本项目是面向无人机趣味编程与智能控制的综合仓库，采用 Monorepo 结构管理多个子系统：图形化编程前端、无人机总控状态机、提示词工程与手势控制原型。

---

## 仓库结构

```text
.
├── Control/            # 无人机总控（Python 双进程 + 全 UDP 通信）
├── Prompt_engineer/    # 大模型指令解析与 Few-shot Prompt
├── Studio/             # Scratch 图形化编程前端（Vite + React）
├── gesture-aircraft/   # PC 端手势控制无人机原型
└── README.md           # 本文件
```

### 1. Studio — 图形化编程前端

基于 Scratch Blocks 与 Vite 的前端界面，提供积木式无人机任务编排、VLM 对话、SD 图像预览等功能。

快速启动：

```bash
cd Studio
npm install
npm run dev -- --host 0.0.0.0
```

前端通过 Vite UDP 桥与总控通信：

| 方向 | 地址 | 用途 |
| --- | --- | --- |
| 前端 → 总控 | `127.0.0.1:9100` | mode 模式/动作指令 |
| 前端 → 总控 | `127.0.0.1:9200` | content 内容数据 |
| 总控 → 前端 | `127.0.0.1:9300` | output 结果回传 |

更多协议细节见 [`Studio/README.md`](Studio/README.md)。

### 2. Control — 无人机总控

双进程架构，进程 A（`run_flight.py`）负责飞行安全，进程 B（`run_model_server.py`）负责 AI 模型推理，两者通过 UDP 隔离，AI 进程崩溃不影响飞控安全。

快速启动（需分别启动两个终端）：

```bash
cd Control
python run_model_server.py
```

```bash
cd Control
python run_flight.py
```

详细说明见 [`Control/README.md`](Control/README.md)。

### 3. Prompt_engineer — 指令解析提示词

包含把中文自然语言转换为无人机 JSON 动作序列的 System Prompt 与 Few-shot 示例，供 `Control` 中的 VLM 调用。

见 [`Prompt_engineer/PROMPT.md`](Prompt_engineer/PROMPT.md)。

### 4. gesture-aircraft — 手势控制原型

使用电脑摄像头 + MediaPipe 识别单手手势，输出无人机运动指令。

```bash
cd gesture-aircraft
python -m pip install -r requirements.txt
python scripts/download_model.py
python -m drone_gesture.app
```

见 [`gesture-aircraft/README.md`](gesture-aircraft/README.md)。

---

## 远程仓库

| 名称 | 地址 | 用途 |
| --- | --- | --- |
| `origin` | `https://github.com/XXXia-art/Tongfly-studio` | 主开发仓库（GitHub） |
| `upstream` | `https://gitee.com/marquerze/Tongfly` | 上游镜像（Gitee） |

日常开发向 `origin` 推送；从 `upstream` 拉取上游更新。

---

## 许可证

待定 / 详见各子目录说明。
