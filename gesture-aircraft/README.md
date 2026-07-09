# PC 端无人机手势运动控制原型

使用电脑摄像头、MediaPipe Hand Landmarker 和 OpenCV，实时识别单手手势并输出无人机运动指令。

## 手势映射

| 手势 | 输出指令 | 停止方式 |
| --- | --- | --- |
| 食指和中指并拢，向左/右滑动 | 左移/右移，固定强度 0.55，执行固定时长 | 动作执行结束后悬停 |
| 食指和中指并拢，向上/下滑动 | 上升/下降，固定强度 0.55，执行固定时长 | 动作执行结束后悬停 |
| 食指和中指并拢并保持静止 | 悬停 | — |
| 五指张开 | 前进，固定强度 0.55，执行固定时长 | 动作执行结束后悬停 |
| 握拳 | 后退，固定强度 0.55，执行固定时长 | 动作执行结束后悬停 |

识别到稳定手势后，程序只触发一次固定动作；动作执行期间会关闭手势识别，避免无人机运动造成的画面相对位移被误判为新手势。动作结束后需要先松手或进入未知手势状态，再识别下一次动作。

程序会镜像摄像头画面，所以屏幕中的左右方向和用户动作方向一致。当前阶段只输出模拟指令，不会连接或控制真实无人机。

## 安装与运行

建议使用 Python 3.10–3.12。

```powershell
python -m pip install -r requirements.txt
python scripts/download_model.py
python -m drone_gesture.app
```

当前机器如果已经安装 `opencv-python`、`mediapipe` 和 `numpy`，只需执行后两条命令。

运行时：

- `Q` 或 `Esc`：退出
- `R`：清空轨迹与状态机

可选参数：

```powershell
python -m drone_gesture.app --camera 0 --width 1280 --height 720
python -m drone_gesture.app --model models/hand_landmarker.task
python -m drone_gesture.app --action-duration 0.70 --fixed-intensity 0.55
python -m drone_gesture.app --stable-window-frames 9 --stable-minimum-votes 7
```

## 验收观察点

窗口右上角显示当前手势、控制指令和强度；手部中心附近的箭头表示检测到的两指滑动方向。终端只在指令发生变化或强度明显变化时打印，便于后续把 `ConsoleCommandSink` 替换成串口、UDP、ROS 2 或飞控 SDK 适配器。

为减少误触发：

- 两指手势要求食指、中指伸直，其他三指收起，且两个指尖距离较近。
- 两指滑动只用于判断方向，不再根据滑动速度改变指令强度。
- 主方向必须明显强于副方向，否则保持悬停。
- 动作执行期间跳过 MediaPipe 手势识别，执行时长结束后自动悬停。
- 动作结束后需要先松手或识别为未知手势，才会触发下一次固定动作。
- 离散手势默认经过 9 帧投票，至少 7 帧一致才稳定；30 FPS 下最少约 0.3 秒。

## 工程结构

```text
drone_gesture/
  app.py          摄像头、MediaPipe 推理和界面
  gestures.py     基于 21 个手部关键点的手势分类
  motion.py       固定动作执行、识别锁定和运动状态机
  commands.py     飞控无关的运动指令与输出接口
tests/
  test_gestures.py
  test_motion.py
```

## 后续接入飞控

保留 `MotionCommand` 作为统一协议，在新的 sink 中完成坐标系和量纲转换即可。真实飞行前必须增加解锁/急停、心跳超时、速度与高度限制、丢帧保护，并先在仿真器或拆桨状态下验证。
