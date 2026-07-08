# 童飞工坊 Scratch GUI 迁移版

## 当前运行方式

当前主流程只需要启动前端：

```bash
npm install
npm run dev -- --host 0.0.0.0
```

前端通过 Vite 内置的 UDP 桥把数据发给总控状态机：

- `mode` 模块：UDP `127.0.0.1:9100`
- `content` 模块：UDP `127.0.0.1:9200`
- `output` 返回：Vite 监听 UDP `127.0.0.1:9300`

前端发给总控的 UDP 包不再使用顶层 `type` 字段。`mode` 模块只发送 `mode` 一个字段，具体内容数据通过 `content` 模块发送。

```json
{
  "mode": 1
}
```

可以通过环境变量修改目标地址：

```bash
TONGFLY_MODE_UDP_HOST=127.0.0.1 TONGFLY_MODE_UDP_PORT=9100 \
TONGFLY_CONTENT_UDP_HOST=127.0.0.1 TONGFLY_CONTENT_UDP_PORT=9200 \
TONGFLY_OUTPUT_UDP_HOST=127.0.0.1 TONGFLY_OUTPUT_UDP_PORT=9300 \
TONGFLY_OUTPUT_IMAGE_ROOT=/home/elf \
npm run dev -- --host 0.0.0.0
```

总控返回 SD 图片时，推荐通过 UDP `9300` 发送图片路径：

```json
{
  "type": "sd_result",
  "payload": {
    "image_path": "/home/elf/Tongfly-output/images/sd_001.png",
    "prompt": "一架无人机在天空中"
  }
}
```

总控返回 VLM 文本时，直接用 `type` 区分回复来源，不再使用 `mode` 字段：

```json
{
  "type": "vlm_chat_result",
  "payload": {
    "text": "模型回复内容"
  }
}
```

## 通信协议与指令格式

浏览器不能直接收发 UDP，所以通信链路是：

```text
浏览器前端 -> HTTP -> Vite UDP 桥 -> UDP -> 总控状态机
总控状态机 -> UDP -> Vite UDP 桥 -> HTTP 轮询 -> 浏览器前端
```

### 端口约定

| 方向 | UDP 端口 | 用途 |
| --- | --- | --- |
| 前端 -> 总控 | `127.0.0.1:9100` | mode 模式/动作指令 |
| 前端 -> 总控 | `127.0.0.1:9200` | content 内容数据 |
| 总控 -> 前端 | `127.0.0.1:9300` | output 模型/总控返回结果 |

前端内部 HTTP 接口：

| HTTP 接口 | 作用 |
| --- | --- |
| `POST /bridge/mode` | 转发到 UDP `9100` |
| `POST /bridge/content` | 转发到 UDP `9200` |
| `GET /bridge/output` | 前端轮询读取总控返回 |
| `GET /bridge/output-image?path=...` | 把 RK3588 本地图片路径映射成浏览器可访问图片 |

### 前端发送包格式

前端发给总控的 UDP 包不使用顶层 `type` 字段。`mode` 包和 `content` 包格式不同。

`mode` 包走 UDP `9100`，只允许一个字段：

```json
{
  "mode": 1
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `mode` | number | 指令/模式编号 |

`content` 包走 UDP `9200`，用于发送具体内容。不同 `mode` 的字段不同，不再统一包一层 `payload`，也不再发送 `describe` 和 `sentAt`。

### UDP 9100: mode 指令

| mode | 触发位置 | 说明 |
| --- | --- | --- |
| `0` | 顶部 `重置飞控` 按钮 | 通知总控重置飞控状态 |
| `1` | 顶部 `编程积木` 按钮 | 进入积木编程模式 |
| `2` | `+` 技能菜单点击 `掌控飞行` | 进入掌控飞行模式，只发送 mode 包 |
| `3` | 顶部 `创意喷绘` 按钮 | 进入创意喷绘模式 |
| `4` | `+` 技能菜单点击 `创建图片` | 进入 SD 图片生成模式，只发送 mode 包 |
| `5` | 顶部 `手势识别` 按钮 | 进入手势识别模式 |
| `6` | `+` 技能菜单点击 `查看画面` | 进入查看画面模式，之后点击发送再发 content 包 |
| `7` | `+` 技能菜单点击 `普通对话` | 进入普通 VLM 对话模式，之后点击发送再发 content 包 |

示例：

```json
{
  "mode": 2
}
```

```json
{
  "mode": 4
}
```

### UDP 9200: content 内容包

#### 编程积木编译结果

点击积木区 `运行` 后发送。总控真正执行飞行时，直接读取顶层 `text`，其中 `text` 是运动学速度指令数组。

`text` 数组中每一项包含：

| 字段 | 单位 | 说明 |
| --- | --- | --- |
| `vx` | m/s | 前后方向速度，正数向前，负数向后 |
| `vy` | m/s | 左右方向速度，正数向右，负数向左 |
| `vz` | m/s | 上下方向速度，正数向上，负数向下 |
| `yaw_rate` | deg/s | 偏航角速度，正数顺时针，负数逆时针 |
| `duration` | s | 动作持续时间 |

```json
{
  "mode": 1,
  "text": [
    {
      "vx": 1,
      "vy": 0,
      "vz": 0,
      "yaw_rate": 0,
      "duration": 2
    },
    {
      "vx": 0,
      "vy": 0,
      "vz": 0.6,
      "yaw_rate": 0,
      "duration": 1
    },
    {
      "vx": 0,
      "vy": 0,
      "vz": 0,
      "yaw_rate": 30,
      "duration": 1
    }
  ]
}
```

常见积木映射：

| 积木动作 | 生成结果 |
| --- | --- |
| 向前，速度 `s`，时间 `t` | `{vx: s, vy: 0, vz: 0, yaw_rate: 0, duration: t}` |
| 向后，速度 `s`，时间 `t` | `{vx: -s, vy: 0, vz: 0, yaw_rate: 0, duration: t}` |
| 向左，速度 `s`，时间 `t` | `{vx: 0, vy: -s, vz: 0, yaw_rate: 0, duration: t}` |
| 向右，速度 `s`，时间 `t` | `{vx: 0, vy: s, vz: 0, yaw_rate: 0, duration: t}` |
| 向上，速度 `s`，时间 `t` | `{vx: 0, vy: 0, vz: s, yaw_rate: 0, duration: t}` |
| 向下，速度 `s`，时间 `t` | `{vx: 0, vy: 0, vz: -s, yaw_rate: 0, duration: t}` |
| 顺时针转向，时间 `t` | `{vx: 0, vy: 0, vz: 0, yaw_rate: 30, duration: t}` |
| 逆时针转向，时间 `t` | `{vx: 0, vy: 0, vz: 0, yaw_rate: -30, duration: t}` |
| 悬停/等待，时间 `t` | `{vx: 0, vy: 0, vz: 0, yaw_rate: 0, duration: t}` |

#### 查看画面内容

触发：先在 `+` 技能菜单点击 `查看画面` 进入 `mode=6`，再点击发送按钮。

```json
{
  "mode": 6,
  "text": "请查看当前画面"
}
```

#### 普通对话内容

触发：先在 `+` 技能菜单点击 `普通对话` 进入 `mode=7`，再点击发送按钮。

```json
{
  "mode": 7,
  "text": "请介绍一下当前任务状态"
}
```

### UDP 9300: 总控返回前端

总控把结果发送到 UDP `127.0.0.1:9300`。Vite 缓存消息，前端通过 `/bridge/output` 轮询读取。

当前返回包使用顶层 `type` 决定前端显示位置。返回包不使用 `payload`，内容字段直接放在顶层。控飞解析结果当前不需要返回给前端。

| type | 前端显示位置 |
| --- | --- |
| `sd_result` | 右上角 SD 图片显示区 |
| `vlm_chat_result` | 右下角聊天区，普通 VLM 对话回复 |
| `vlm_vision_result` | 右下角聊天区，查看画面/图像理解回复 |

SD 图片返回推荐格式：

```json
{
  "type": "sd_result",
  "asr_text": "画一架红色无人机在天空中飞行",
  "prompt_en": "A red drone flying in the sky",
  "image_path": "/home/elf/Tongfly-output/images/sd_001.png"
}
```

VLM 普通文本对话返回：

```json
{
  "type": "vlm_chat_result",
  "text": "模型回复内容"
}
```

查看画面返回：

```json
{
  "type": "vlm_vision_result",
  "text": "我看到了前方有障碍物",
  "image_path": "/home/elf/Tongfly-output/images/vision_001.png"
}
```

### 总控侧处理建议

```text
监听 9100:
  mode=0 -> 重置飞控
  mode=1 -> 编程积木模式
  mode=2 -> 掌控飞行模式
  mode=3 -> 创意喷绘模式
  mode=4 -> SD 图片生成模式
  mode=5 -> 手势识别模式
  mode=6 -> 查看画面模式
  mode=7 -> VLM 普通对话模式

监听 9200:
  mode=1 -> 读取 text 数组并执行 vx/vy/vz/yaw_rate/duration
  mode=6 -> 读取 text，执行图像理解
  mode=7 -> 读取 text，执行普通 VLM 对话

返回 9300:
  type=sd_result -> 前端显示图片
  type=vlm_chat_result -> 前端显示 VLM 普通对话回复
  type=vlm_vision_result -> 前端显示查看画面回复
```

旧的 FastAPI 后端、VLM/SD 模型调用代码已经归档到：

```text
assets/legacy-server/
```

这部分当前主流程不再使用，只作为历史代码和参考保留。

这个目录是把现有单文件原型迁移到 Scratch 生态的第一步。根目录的 `index.html` 仍然保留，`scratch-drone/` 负责后续可扩展开发。

## 为什么这样拆

- `scratchfoundation/scratch-gui` 已在 2026-06-10 归档，Scratch 团队说明新开发迁到 `scratch-editor` mono-repo，并发布为 `@scratch/scratch-gui`。
- 当前 npm 可用稳定版为 `@scratch/scratch-gui@14.1.0`，它使用 React 18。
- Scratch GUI 本质是一组 React 组件；Scratch VM 负责积木定义和执行。
- 你的无人机能力更适合做成 Scratch VM 扩展：飞行动作、YOLO、VLM、SD 都放在一个 `droneVLM` 扩展里。
- 循环、如果、等待等逻辑积木应优先使用 Scratch 原生 Control 分类，避免自己维护 C 形逻辑块。

## 已搬运的能力

- 飞行：向前、向后、向左、向右、向上、向下、转向，均保留速度和时间参数。
- 逻辑：重复、无限循环、如果、等待、持续执行作为 Scratch 原生/迁移规划保留。
- AI：YOLO 识别、询问画面、问小助手、创建图片。
- 右侧面板：无人机图传 mock、VLM 聊天、SD 生成 mock。
- 封装：预览界面保留「封装模块」入口，真正项目中建议映射到 Scratch 的「自制积木 / My Blocks」。

## 目录说明

- `src/extensions/droneScratchExtension.js`：Scratch VM 扩展定义，后续接入 scratch-gui 的核心。
- `src/scratch/registerDroneExtension.js`：注册扩展的适配函数。
- `src/services/`：DroneBridge、VLMClient、SDClient 的虚拟接口。
- `src/data/droneBlockCatalog.js`：界面和扩展共享的积木配置。
- `src/components/`：Scratch 风格的迁移预览界面，不替代真正 scratch-gui。

## 本地运行

```bash
cd scratch-drone
npm install
npm run dev
```

如果只想检查扩展定义：

```bash
npm run check:extension
```

## 接入 scratch-gui 的方式

在真正的 Scratch GUI/VM 工程里，保留 `src/extensions/droneScratchExtension.js` 和 `src/services/*`，然后在 VM 初始化后注册：

```js
import {registerDroneExtension} from './scratch/registerDroneExtension';
import {droneBridge} from './services/droneBridge';
import {vlmClient} from './services/vlmClient';
import {sdClient} from './services/sdClient';

registerDroneExtension(vm, Scratch, {
  droneBridge,
  vlmClient,
  sdClient
});
```

如果使用 `scratchfoundation/scratch-gui` 源码，还需要在 `src/lib/libraries/extensions/index.jsx` 里增加一个扩展库入口，`extensionId` 与扩展里的 `id: 'droneVLM'` 保持一致。

## 后续建议

- 把真实无人机图传接入 `DroneBridge.getFrameStream()`。
- 把 VLM 图片理解接入 `VLMClient.describeFrame()`。
- 把 SD 生成接入 `SDClient.createImage()`。
- 将「封装模块」迁移为 Scratch 的 My Blocks，而不是自研保存格式。
