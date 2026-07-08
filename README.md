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

总控返回 VLM 文本时：

```json
{
  "type": "vlm_result",
  "payload": {
    "text": "我看到了前方有障碍物"
  }
}
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
