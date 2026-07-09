# 无人机总控项目 —— 集成说明

## 一、架构总览

双进程 + 全UDP通信，不用FastAPI/uvicorn/requests。两个进程物理隔离，
`model_server`进程崩溃/OOM不会影响`flight`进程的飞控安全逻辑。

```
上位机
  │ UDP 9100(指令)              UDP 9300(回传结果)
  ▼                                 ▲
┌──────────────────────────┐   UDP 9200   ┌──────────────────────────────┐
│ 进程A: run_flight.py       │◀───────────▶│ 进程B: run_model_server.py     │
│ 只碰飞控，不碰AI模型         │              │ 只碰AI模型，不碰飞控             │
│                            │              │                              │
│  mode_manager              │              │  model_logic.py               │
│  flight_executor           │              │  vlm_engine.py (Qwen2VL)      │
│  uplink_udp                │              │  real_sd_adapter.py (真实LCM出图)│
│  screen_draw                │              │  voice_to_sd_singleton.py     │
│  voice_vlm                  │              │  prompt_utils.py              │
│  model_client ─────────────┼──────────────▶  model_server_udp             │
└──────────────────────────┘              └──────────────────────────────┘
```

**为什么拆两个进程**：`model_server`那边跑着VLM/SD/Whisper/翻译，板子内存紧张，
随时可能OOM崩溃；`flight`这边管着飞机安全，绝不能被AI那边拖累。两边只靠UDP
通信——`model_server`崩了，`flight`这边最多是等超时拿到`{"error":...}`，
飞控看门狗/降落逻辑完全不受影响。

---

## 二、目录结构与每个文件的作用

### 进程A：飞行控制

```
run_flight.py            进程A入口
mode_manager.py           四模式互斥仲裁
flight_executor.py        唯一往飞控发setpoint的地方
uplink_udp.py             监听上位机UDP指令(9100) + 回传结果
screen_draw.py            串口屏画笔TCP监听(5000)
voice_vlm.py              语音控制飞行的"执行"部分
model_client.py           UDP客户端，进程A调进程B用这个
```

- **`run_flight.py`**：进程入口。打印安全检查清单，`input()`人工确认后，
  拉起3个daemon线程(flight_executor / uplink_udp / screen_draw)，并探测
  一下model_server在不在(不在也不阻塞飞行，只是提醒语音/VLM/生图暂时用不了)。

- **`mode_manager.py`**：全局单例，维护一个字符串状态，四选一：
  `IDLE` / `UPLINK_VELOCITY` / `VOICE_VLM` / `SCREEN_DRAW`。任何模块想操作
  飞机之前都必须先`is_active(自己的模式名)`确认一下"我现在还是被允许说话
  的那个模式吗"——因为在异步处理指令的过程中，上位机随时可能已经把模式
  切走了。看门狗可以用`force_idle()`直接把模式打回IDLE，不走仲裁流程。

- **`flight_executor.py`**：全项目唯一允许调用MAVSDK发送setpoint的地方。
  `run_forever()`在专属线程里起一个独立的asyncio事件循环：连接飞控→等
  OFFBOARD→**停在这里等显式起飞指令**→解锁→起飞→常驻监听状态。
  **[重要] 起飞不是自动的**——进入OFFBOARD之后不会自动解锁爬升，必须收到
  `request_takeoff()`(对应上位机`mode=8`)才会真正起飞，这是为了避免
  "遥控器一拨到OFFBOARD飞机就自己飞起来"这种意外。对外暴露的"安全阀"接口：
  - `request_takeoff()`——只有在"已进OFFBOARD、还没起飞"这个等待窗口内
    才有意义，已经在飞或者还没连接都会被拒绝并说明原因，不会静默失效
  - `set_velocity_body(mode_name, ...)`——检查`mode_manager.is_active()`，
    速度值全部经过`clamp()`限幅(`config.MAX_VELOCITY_MPS`等)
  - `fly_path_positions(mode_name, ne_offsets)`——画笔模式用，每走一个点
    都重新核对模式
  - `request_land()`——用独立的`land_requested`事件触发，跟`abort_event`
    彻底分开(如果共用一个事件，降落时的分级下降循环第一次检查就会立刻
    退出，飞机从未被真正指挥下降过)。等待起飞指令期间/等OFFBOARD期间
    如果收到降落请求，会被当成"取消起飞、直接清理退出"处理，不会走真正
    的下降流程(飞机压根没解锁过)，也不会导致进程卡死退不出去
  - `request_reset()`——仅地面允许的重置：如果当前处于人工接管
    (`offboard_lost`)之后的只读监听状态，必须拿到测距传感器"高度低于
    阈值+已断电"的实时读数才放行，不会仅凭软件内部标志位就相信飞机已落地

  内部有**两个看门狗**：`_offboard_watchdog`(掉出OFFBOARD=人工接管)和
  `_armed_watchdog`(意外断电)，都会设置`abort_reason`区分收尾方式——
  人工接管时绝对不能调用`disarm()`，只清理后台任务、把控制权完全交还
  给人；意外断电时`disarm()`只是幂等确认，无害。降落序列(`_land_sequence`)
  完整照抄了`test_04`/`test_05`两个已实测脚本的规格：分级下降→测距传感器
  确认贴地(带超时兜底)→确认失败则切飞控原生`Land()`模式兜底。

- **`uplink_udp.py`**：监听9100(`mode`指令)/9200(`content`内容数据，
  仅`mode`1/6/7有后续内容包)/9300(回传结果)三个UDP端口，收到`mode`数字
  按数字分发(0重置/1积木/2语音/3画笔/4生图/5手势(未实现)/6/7 VLM/8起飞/
  9降落)；旧版`{"cmd": "..."}`格式仍然兼容，作为手动调试用的次要路径。
  `send_reply()`统一从这里把结果回传到9300端口。

- **`screen_draw.py`**：监听5000端口TCP，解析串口屏/树莓派发来的二进制帧
  (`D`落笔/`M`移动/`U`抬笔/`S`起飞确认/`L`降落请求)。一笔画完后用RDP算法
  简化关键点，像素坐标转NED偏移，**只有当前模式真的是`SCREEN_DRAW`时**
  才会真的调`flight_executor.fly_path_positions()`飞过去，否则只解析
  打印、不动飞机。

- **`voice_vlm.py`**：语音控飞的执行半边。收到`voice_trigger`时，先确认
  是`VOICE_VLM`模式，问进程B要一段JSON动作序列(`velocity`/`hover`/`land`)，
  用正则从LLM原始输出里抠出JSON，逐条动作喂给`flight_executor`，执行前、
  执行中都反复检查模式有没有被切走。

- **`model_client.py`**：进程A访问进程B的唯一通道。纯UDP同步请求/响应，
  超时/连接失败(含Linux下UDP发到无监听端口触发的`ConnectionRefusedError`，
  这是常见的正常报错路径，不是死代码)统一包装成`{"error":...}`。

### 进程B：AI推理

```
run_model_server.py       进程B入口
model_logic.py            VLM/SD/Whisper/翻译的实际业务逻辑
model_server_udp.py       UDP服务端(9200)
vlm_engine.py             Qwen2VL推理引擎
real_sd_adapter.py        包装voice_to_sd.py里真实LCM出图pipeline
voice_to_sd_singleton.py  保证voice_to_sd.py全进程只加载一次
prompt_utils.py           解析flight_prompt.md
```

- **`run_model_server.py`**：进程入口，`model_logic.startup()`后开始
  `model_server_udp.serve()`(阻塞)。

- **`model_logic.py`**：所有AI业务逻辑核心，不含任何网络代码。
  `model_memory_lock`保证**同一时刻只有一个模型(VLM或SD)常驻内存**——
  板子是三核NPU但内存不够，这是硬约束，`ensure_vlm_active()`/
  `ensure_sd_active()`互相释放对方腾内存。进程启动时**不预加载**任何
  模型，只有收到对应指令才按需加载；Whisper+翻译是例外，常驻不参与互斥。
  每个功能函数(`run_vlm_chat`/`run_sd_generate`/`run_voice_flight_command`
  等)都用`_Stage`小工具包一层，打印每个阶段的耗时，方便定位哪一步慢。
  `flight_prompt_lock`保护`_flight_system_prompt`/`_flight_few_shot`这对
  全局变量的读写，避免`reload_flight_prompt()`跟正在读取的请求撞车导致
  新旧配对不一致。`_read_camera_frame_base64()`负责从本地磁盘读取摄像头
  推流pipeline用`tee`分出来的最新一帧JPEG(见下文"摄像头画面"一节)。

- **`model_server_udp.py`**：监听9200端口，纯UDP，`request_id`用来对应
  请求/响应(当前是一发一收同步等待)。每个请求进来都开一个新线程处理，
  避免生图这种慢请求卡住整个收包循环。

- **`vlm_engine.py`**：`VisionEncoder`(RKNN视觉编码器) + `LLMEngine`
  (ctypes调`librkllmrt.so`)。`chat_flight()`是专门给语音/文字飞行指令
  解析用的接口，内部走`chat_with_system()`，拿`flight_prompt.md`里的
  system prompt + few-shot拼出完整对话，复用同一个rkllm实例，不会额外
  占用内存。

- **`real_sd_adapter.py`**：把`voice_to_sd.py`里真正在用的LCM出图pipeline
  包装成跟`sd_engine.py`(旧的简化版，已停用)一致的接口
  (`.load()`/`.release()`/`.generate()`/`.pipe`/`.loading`/`.last_error`)。
  实际部署的`voice_to_sd.py`("集大成版")用的是它自己的`get_sd_pipe()`懒
  加载单例，`load()`直接调它即可，不需要额外的互斥逻辑改造。

- **`voice_to_sd_singleton.py`**：保证`voice_to_sd.py`全进程只用
  `importlib`加载一次，避免多份模型实例(否则每个实例各自持有自己的
  `_sd_pipe`等全局变量，等于变相加载了好几份模型)。**[实际部署版本的
  关键点]** 这份脚本里Whisper是每次`transcribe_audio()`调用时现场加载、
  用完就释放，不是常驻的，没有"后台预热"这个概念；翻译模块和SD都是
  "第一次调用才加载、之后缓存"的懒加载单例。但这份脚本本身**没有提供
  释放SD的办法**——一旦加载就永远占着内存，没法配合`ensure_vlm_active()`
  "先释放SD腾内存再加载VLM"这个需求。`voice_to_sd_singleton.py`会在拿到
  module之后，动态给它挂一个`release_sd_pipe()`函数(不修改磁盘上的原
  文件)，逐个释放`text_encoder`/`unet`/`vae_decoder`三个RKNN子模型的
  运行时资源。**如果没有这一步，VLM/SD互斥切换形同虚设**：SD一旦被用过
  一次，后续加载VLM时会跟SD同时占着NPU内存，大概率导致OOM。

- **`prompt_utils.py`**：从`flight_prompt.md`里用正则抠出\`\`\`text\`\`\`
  代码块当system prompt，\`\`\`python\`\`\`代码块里`ast.parse`出
  `FEW_SHOT_MESSAGES`变量当few-shot。文件缺失时优雅降级成默认prompt+
  空few-shot，不会导致进程崩溃。

### 公共配置

- **`config.py`**：全部端口、路径、安全限幅参数的唯一来源，两个进程都读。
  关键安全参数：`MAX_ALTITUDE`(2.0m)、`MAX_VELOCITY_MPS`(0.5m/s)、
  `MAX_YAWSPEED_DEGS`(30°/s)、`UPLINK_VELOCITY_TIMEOUT`(0.3s，速度指令
  断联清零)。

- **`flight_prompt.md`**：语音/文字飞行指令解析用的system prompt +
  few-shot示例，格式是两个代码块(text/python)，被`prompt_utils.py`解析。

### 便利脚本

- **`run_all.py`**：用`subprocess`同时拉起两个进程，进程B的输出加
  `[model_server]`前缀转发到同一个终端；进程A的stdin/stdout**不重定向**，
  直接连到当前终端，因为它有`input()`安全确认需要交互。`Ctrl+C`退出时
  先让flight进程走完自己的降落流程，再关model_server。

### 不再被服务代码使用的文件（仅供参考）

- `sd_engine.py`——旧的简化版SD实现，已被`real_sd_adapter.py`取代，
  没有任何地方import它
- `main.py`——更早期的单进程FastAPI版本，跟现在这套双进程UDP架构是
  两代设计，已废弃
- `run_2core.py` / `run_qwen2vl.py`——Qwen2VL的独立命令行调试脚本，
  `prompt_utils.py`的解析逻辑是从`run_qwen2vl.py`里抽出来的，但抽出来
  之后两边就没有代码层面的关联了
- `test_04_square_land.py` / `test_05_velocity_land.py`——一次性人工
  确认的联调测试脚本，`flight_executor.py`的降落/速度控制逻辑是照着
  这两个脚本的规格"移植"过来的，但它们本身不被服务进程调用
- `mavlink_bridge.py`——独立跑的MAVLink透传桥接程序，是运行前提条件，
  不属于这两个进程的代码，需要单独启动
- `voice_to_sd_fast.py`——就是`config.VOICE_TO_SD_SCRIPT_PATH`指向的
  那个原始脚本，被`voice_to_sd_singleton.py`用`importlib`按路径动态
  加载复用，不是常规import

---

## 三、启动前必须做的事

1. `mavlink_bridge.py`已经在跑，且是带Offboard转发那一路的版本
   (`grep OFFBOARD mavlink_bridge.py`应该有输出)
2. QGC参数`COM_RC_OVERRIDE`已勾选offboard覆盖选项，建议
   `COM_OBL_RC_ACT`设为0(信号丢失切Position悬停)
3. 遥控器已开机、对频，随时可以拨模式开关接管——这是最后一道安全网，
   全程需要有人手持待命
4. **首次联调强烈建议拆桨或固定飞机**
5. `config.py`里的路径按板子实际情况改(`VOICE_TO_SD_SCRIPT_PATH`等)
6. `vlm_engine.py`/`voice_to_sd.py`依赖的`TONGFLY_*`环境变量按需设置
7. 摄像头推流pipeline(见下文)已经按tee分支改好，`CAMERA_LATEST_FRAME_PATH`
   指向的文件在持续更新
8. 依赖安装：
   - 进程A(飞控)：`pip install mavsdk`(不需要requests/FastAPI)
   - 进程B(模型)：不需要FastAPI/uvicorn，装板子上本来就有的
     rknnlite/sounddevice/soundfile/cv2/PIL等

---

## 四、运行方式

**方式一：一个命令，输出汇总在一个终端里(推荐日常用)**
```bash
python3 run_all.py
```

**方式二：两个终端，分开看(适合调试/排查问题)**
```bash
# 终端1
python3 run_model_server.py
# 终端2
python3 run_flight.py
```

启动顺序没有强制要求，但建议先起model_server：`run_flight.py`启动时会
探测一下它在不在，先起能让你在飞行进程启动时就确认AI那边状态正常。

---

## 五、上位机UDP协议

### 端口9100（上位机 → 进程A，mode指令）
```jsonc
{"mode": 0}                              // 重置飞控(仅地面允许，见下方安全说明)
{"mode": 1}                              // 切到编程积木模式(动作数组走9200)
{"mode": 2}                              // 触发语音掌控飞行
{"mode": 3}                              // 切到创意喷绘(画笔)模式
{"mode": 4}                              // 触发语音/文字生图(text留空则现场录音)
{"mode": 5}                              // 手势控制模式(当前总控端尚未实现)
{"mode": 6}                              // VLM图像理解(问题内容走9200)
{"mode": 7}                              // VLM文字问答(问题内容走9200)
{"mode": 8}                              // 起飞：只有"已进OFFBOARD、还没起飞"这个
                                          // 等待窗口内有效，默认起飞高度1米
                                          // (config.TAKEOFF_ALTITUDE)，不需要9200内容
{"mode": 9}                              // 降落，不受模式限制，随时可发，不需要9200内容
```
`mode=0`的重置指令，也可以用`{"mode": 任意值, "describe": "...重置飞控..."}`
这种"描述文字里带关键字"的方式触发，兼容旧协议习惯，但**建议直接用`mode=0`**，
更明确、不会被describe字段里意外出现的文字误触发。

### 端口9200（上位机 → 进程A，content内容数据，仅mode 1/6/7需要）
```jsonc
{"mode": 1, "text": [{"vx":0.15,"vy":0.0,"vz":0.0,"yaw_rate":0.0,"duration":3}, ...]}
{"mode": 6, "text": "这是什么", "image_base64": null}   // image_base64留空则用摄像头最新帧
{"mode": 7, "text": "你好"}
```

### 端口9300（进程A → 上位机，回传结果）
```jsonc
{"type": "sd_result", "asr_text": "...", "prompt_en": "...", "image_path": "..."}
{"type": "vlm_chat_result", "text": "..."}
{"type": "vlm_vision_result", "text": "...", "image_path": "..."}
```
生图/VLM图像理解结果只包含**文件路径**，不含图片二进制——UDP单包传不了
大文件，上位机要怎么真正拿到图片本体(共享盘/单独传输通道)需要另外设计，
这套代码目前不负责传输图片二进制。

### 端口9200（进程A ↔ 进程B，内部协议，上位机看不到，跟上面同端口号但用途不同）
```jsonc
请求: {"cmd": "vlm_chat", "request_id": "...", "text": "..."}
响应: {"request_id": "...", "result": "..."} 或 {"request_id": "...", "error": "..."}
```
这是`model_client.py`访问`model_server`时用的**本机内部**UDP协议(9201端口，
见`config.MODEL_SERVER_UDP_PORT`)，跟9200这个"上位机→进程A"的content端口
是两回事，只是历史上都叫"9200"容易混淆，需要注意区分。支持的cmd：
`vlm_chat` `vlm_describe` `vlm_flight_command` `sd_generate`
`voice_flight_command` `voice_gen_image` `reload_flight_prompt` `health`

---

## 六、四个飞行模式

由`mode_manager.py`互斥仲裁，任意时刻只有一个模式的指令能真正送到飞控执行器。
**注意区分**：这里的"模式"是`mode_manager`内部状态机(字符串)，跟上位机
UDP协议里的`mode`数字(0-9)不是一回事——数字协议里`mode=1/2/3`会触发切换
到对应的互斥模式，但`mode=8`(起飞)/`mode=9`(降落)不属于这四个互斥模式，
是直接作用于`flight_executor`的独立控制，不经过`mode_manager`仲裁：

| `mode_manager`状态 | 触发方式 | 说明 |
|---|---|---|
| `IDLE` | 默认/降落后 | 不接受任何飞行指令 |
| `UPLINK_VELOCITY` | 上位机`mode=1` | 编程积木/上位机直接发送速度指令 |
| `VOICE_VLM` | 上位机`mode=2` | 语音识别+VLM解析飞行指令 |
| `SCREEN_DRAW` | 上位机`mode=3` | 串口屏笔画自动转换成飞行路径 |

`mode=9`(降落)不受这四个互斥模式限制，任何时候都能发。
`mode=8`(起飞)只在"已连接飞控、已进入OFFBOARD、还没解锁起飞"这个等待窗口
内有效——**起飞不再是自动的**，遥控器拨到OFFBOARD之后飞机会停在地面等
`mode=8`，不会自己解锁爬升，这是刻意设计，避免"一进OFFBOARD就自动起飞"
带来的意外。

---

## 七、模型加载机制：完全由上位机指令驱动，不预加载

进程B启动时**不会**预加载任何模型。真实版`voice_to_sd.py`("集大成版")里：
- Whisper是**每次调用现场加载、用完就释放**，不是常驻的，没有"预热"这回事
- 翻译模块、SD都是**懒加载单例**——第一次真正用到时才加载，之后缓存复用
- VLM同理，第一次收到`mode=6`/`mode=7`/`mode=2`(语音掌控飞行)才会
  `ensure_vlm_active()`加载；`mode=4`(生图)才会`ensure_sd_active()`加载SD

同一时刻只有一个模型(VLM或SD)常驻内存，`model_memory_lock`锁住的是**整个
推理过程**，不只是切换那一下——如果一个语音识别+VLM推理正在跑，这期间任何
其他请求都会排队等待，防止正在使用的模型被另一个请求把底层资源拆掉
导致崩溃。

---

## 八、摄像头画面：VLM看的是推流pipeline分流出来的本地文件

板子上只有一个摄像头(`/dev/video21`)，被一条常驻的`gst-launch`推流
pipeline独占，实时推给上位机看(`udpsink host=... port=5002`)。VLM不能
再单独开一次这个设备抢画面，所以推流命令需要用`tee`多分一路，把每一帧
JPEG同时落盘到`config.CAMERA_LATEST_FRAME_PATH`(默认
`/tmp/vlm_latest_frame.jpg`，不断覆盖)：

```bash
taskset -c 4 gst-launch-1.0 v4l2src device=/dev/video21 ! \
  image/jpeg,width=1920,height=1080,framerate=30/1 ! \
  tee name=t \
  t. ! queue ! mppjpegdec ! videoconvert ! \
       mpph264enc gop=30 bps=4000000 ! h264parse config-interval=1 ! \
       mpegtsmux alignment=7 ! udpsink host=192.168.1.11 port=5002 \
  t. ! queue leaky=downstream max-size-buffers=2 ! \
       multifilesink location=/tmp/vlm_latest_frame.jpg max-files=1
```

`vlm_describe`指令现在**不需要上位机传图片**，`model_logic.py`会自动读
这个本地文件转base64喂给VLM。如果文件不存在、或者超过
`CAMERA_FRAME_MAX_AGE_SECONDS`(默认3秒)没更新，直接返回错误，不会拿一张
过期画面悄悄做推理。

生图(`gen_image`)落盘到`config.IMAGE_OUTPUT_DIR`跟这个逻辑是对称的
"本地磁盘中转"思路，都不走网络传图片本体。

---

## 九、安全机制清单

- 所有速度/角速度指令都经过硬性限幅(`config.py`里`MAX_*`常量)
- 速度模式超过`UPLINK_VELOCITY_TIMEOUT`(0.3s)没收到新指令，立刻清零，
  防止断联续飞
- 四模式互斥，`is_active()`二次确认防止"模式已切走，后台线程还在傻发指令"
- 双看门狗(OFFBOARD丢失/意外disarm)，`abort_reason`区分收尾方式，绝不
  在人工接管时误触发`disarm()`
- 降落指令(`land_requested`)跟意外abort(`abort_event`)用独立事件，互不
  干扰，降落分级下降循环能正常跑完
- 降落规格对齐已实测的`test_04`/`test_05`：分级下降→测距传感器确认
  贴地(硬超时兜底)→飞控原生`Land()`模式兜底(同样有超时)
- 语音飞行指令解析结果里的`duration`硬上限6秒，长距离移动需要拆成多段

---

## 十、还需要确认/补全的地方

1. **图片二进制传输**：生图结果目前只回传路径字符串，上位机跟板子如果
   不在同一文件系统，需要另外设计传输方式(共享盘/TCP单独通道/UDP分片)
2. **`flight_prompt.md`的few-shot质量**：需要多喂真实场景例子调优
3. **`model_client.py`没有请求排队限流**：极端情况下上位机短时间连续
   触发多个耗时请求，`vlm_lock`/`sd_lock`保证模型调用本身不冲突，但
   没做限流，建议高并发场景下加
4. **9200端口没有认证**：仅限本机使用，如果以后两个进程要跑在不同设备
   上，需要加认证/防火墙规则
5. **摄像头推流pipeline的`tee`分支**：需要你手动改到实际部署的启动脚本
   /systemd service里，这不是Python代码能覆盖的部分

---

## 十一、建议的第一次联调顺序

1. 拆桨/固定飞机
2. 起`run_all.py`，确认两个进程都正常连上飞控、model_server也ready
3. **先只测`land`指令**——降落逻辑经过重点修复，最值得先单独验证
4. 再测`velocity`小幅度移动，确认限幅、超时清零生效
5. 语音/画笔/VLM这些功能放最后测，出问题不影响飞行安全这条底线
---

## 十二、本次修复记录

1. **`flight_executor.py`**：`offboard_lost`(人工接管)之前会让`request_reset()`
   永久被拒绝，只能重启进程。**修正为：不再纯靠人工信任**——人工接管后
   保持MAVSDK连接和遥测订阅存活(`_post_handover_monitor()`)，持续记录测距
   传感器高度和armed状态；`request_reset()`必须读到"高度低于阈值 且
   armed==False"的实时数据才放行，读数缺失/超过5秒未更新一律拒绝。这跟
   `_land_sequence()`落地确认用的判断依据一致：优先信测距传感器的物理
   高度读数，而不是依赖`in_air`/`flight_mode`这类依赖本地位置(光流)估计、
   贴地时容易失真的遥测。监听协程本身异常退出时也不会静默放行，会持续
   拒绝reset直到人工重启进程。
2. **`uplink_udp.py`**：`mode=1`(积木指令)之前是同步执行的，内部的
   `time.sleep()`循环会卡住整个content(9200)监听线程，导致执行期间收不到
   新的content包。现在跟`mode=6/7`一样丢给后台线程执行。
3. **`README.md`**：协议章节里输出端口写的是9101，跟`config.py`实际的
   `OUTPUT_UDP_PORT`默认值9300不一致，已改正；同时给`config.py`里已经不再
   被任何代码使用的`UPLINK_REPLY_HOST_DEFAULT`/`UPLINK_REPLY_PORT_DEFAULT`
   加了说明，避免以后误以为它们还生效。
4. **`flight_executor.py`**：新增`mode=8`(起飞)/`mode=9`(降落)显式指令。
   **起飞不再是"一进OFFBOARD就自动解锁爬升"**，改成必须收到`mode=8`才会
   真正起飞——进入OFFBOARD后会停在等待点，只有`request_takeoff()`被调用
   才往下走`arm()`+爬升。原来"起飞后abort"那段收尾逻辑抽成`_handle_flight_abort()`
   方法，起飞前(等待期间)和起飞后的abort现在共用同一套代码；`_offboard_watchdog`
   里"是否需要传感器只读监听确认"这一步，只在真正起飞过(`armed_and_flying`
   为True)时才会开启，起飞前退出OFFBOARD直接回到待机，不需要走那套确认流程。
   顺带修了两个由这次改动暴露出来的bug：等待起飞指令、等待OFFBOARD这两个
   循环之前都没检查`land_requested`，如果`Ctrl+C`退出/降落请求恰好发生在
   这两个等待阶段，进程会永久卡住退不出去——现在都加上了检查。
5. **`README.md`**：第五节协议文档整节重写——之前一直写的是旧版
   `{"cmd": "..."}`格式当主协议，但`uplink_udp.py`实际早就换成了`{"mode": 数字}`
   这套协议(`{"cmd":...}`现在只是保留的手动调试次要路径)，文档跟代码完全对不上，
   这次照实际协议重写，补上`mode=8/9`，并把第六/七节里过时的"Whisper常驻后台
   预热"、`voice_to_sd_singleton.py`的旧版patch说明(实际部署脚本压根没有
   `start_background_loaders`这个函数，问题和patch方式跟文档原来写的不一样)
   都改成跟实际代码一致的描述。