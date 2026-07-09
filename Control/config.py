# -*- coding: utf-8 -*-
"""
config.py —— 全局配置集中存放。所有端口/路径/安全参数改这里，不要散落在各文件里改。
"""
import os

# ========== 前端/Vite UDP桥通信 ==========
# 新协议：
#   9100: mode 指令
#   9200: content 内容数据
#   9300: output 总控返回结果
UPLINK_UDP_HOST = os.environ.get("UPLINK_UDP_HOST", os.environ.get("TONGFLY_MODE_UDP_HOST", "0.0.0.0"))
UPLINK_UDP_PORT = int(os.environ.get("UPLINK_UDP_PORT", os.environ.get("TONGFLY_MODE_UDP_PORT", "9100")))
CONTENT_UDP_HOST = os.environ.get("CONTENT_UDP_HOST", os.environ.get("TONGFLY_CONTENT_UDP_HOST", "0.0.0.0"))
CONTENT_UDP_PORT = int(os.environ.get("CONTENT_UDP_PORT", os.environ.get("TONGFLY_CONTENT_UDP_PORT", "9200")))
OUTPUT_UDP_HOST = os.environ.get("OUTPUT_UDP_HOST", os.environ.get("TONGFLY_OUTPUT_UDP_HOST", "127.0.0.1"))
OUTPUT_UDP_PORT = int(os.environ.get("OUTPUT_UDP_PORT", os.environ.get("TONGFLY_OUTPUT_UDP_PORT", "9300")))

# 上位机地址：用于我们主动回传结果（图片路径、VLM回答、状态）。
# 如果上位机不是固定IP，第一次收到包时会自动学习对方地址并覆盖这里，
# 之后回传就发到"最后一次跟我们说过话的地址"。
# [已不再使用] 早期版本里uplink_udp.py会"自动学习最后一次跟自己说话的地址"
# 当作回传目标，用的就是这两个变量做默认值。现在的uplink_udp.py改成固定
# 回传到 config.OUTPUT_UDP_HOST/OUTPUT_UDP_PORT(9300，Vite UDP桥地址)，
# 不再有"自动学习地址"这个逻辑，这两个变量目前没有任何代码在读，纯历史遗留。
UPLINK_REPLY_HOST_DEFAULT = os.environ.get("UPLINK_REPLY_HOST", "192.168.1.1")
UPLINK_REPLY_PORT_DEFAULT = int(os.environ.get("UPLINK_REPLY_PORT", "9101"))

# [安全] 速度模式的上行指令，超过这个时间(秒)没收到新包，立刻把速度setpoint清零。
# 防止上位机断线/丢包后飞机"傻乎乎地按最后一条指令继续飞"。
UPLINK_VELOCITY_TIMEOUT = float(os.environ.get("UPLINK_VELOCITY_TIMEOUT", "0.3"))

# ========== 串口屏画笔 TCP 通信 ==========
SCREEN_TCP_HOST = os.environ.get("SCREEN_TCP_HOST", "0.0.0.0")
SCREEN_TCP_PORT = int(os.environ.get("SCREEN_TCP_PORT", "5000"))
SCREEN_WIDTH = 893
SCREEN_HEIGHT = 480
FLIGHT_SPAN_X = 2.8   # 米，画笔模式允许的水平活动范围
FLIGHT_SPAN_Y = 1.5
RDP_EPSILON = 3.0

# ========== 飞控连接（MAVSDK，经 mavlink_bridge.py 的offboard转发口） ==========
DRONE_CONNECTION_ADDRESS = os.environ.get("DRONE_CONNECTION_ADDRESS", "udp://:14540")
SETPOINT_RATE_HZ = 20

# [安全] 硬性限幅，任何模式都不能突破
MAX_ALTITUDE = 2.0          # 米
MAX_VELOCITY_MPS = 0.5       # 任何模式下水平速度的硬上限，防止上位机/VLM给出离谱数值
MAX_YAWSPEED_DEGS = 30.0     # 偏航角速度硬上限

TAKEOFF_ALTITUDE = 1.0
CLIMB_STEP = 0.1
TAKEOFF_STEP_INTERVAL = 0.2
LAND_STEP_INTERVAL = 0.3
POSITION_TOLERANCE = 0.15
REACH_TIMEOUT = 15
LAND_HEIGHT_CONFIRM_THRESHOLD = 0.11
LAND_HEIGHT_CONFIRM_TIMEOUT = 5.0
LAND_NATIVE_TIMEOUT = 20.0

# 画笔模式：每一步移动的步长/间隔（沿用position控制的分级移动逻辑）
SCREEN_STEP_DISTANCE = 0.05
SCREEN_STEP_INTERVAL = 0.25
# [已停用，不再被任何代码使用] 之前"抬笔跳转"时垂直抬升的高度(米)，
# 用来避免飞机贴着原高度平移拖出一条连接两笔的误线。现在改用激光开关
# 控制画线(见laser_control.py+flight_executor.fly_path_positions())，
# 跳转期间激光是关的，飞行轨迹本身不会画出任何东西，不再需要这个垂直
# 抬升动作。留着这个常量只是避免删掉导致其它地方引用报错，不建议再改
# 它的值，改了也不会有任何效果。
SCREEN_LIFT_HEIGHT = 0.3

# ========== 进程拆分：flight进程通过UDP调model_server进程 ==========
# [架构] flight_executor所在的进程(run_flight.py)不直接import任何AI模型代码，
# 只通过本机UDP调用model_server进程(run_model_server.py)。不用FastAPI/HTTP，
# 两边都是轻量的UDP收发，flight进程连requests库都不需要装。
# 这样模型那边OOM/崩溃，不会拖累飞行控制这条命。
MODEL_SERVER_HOST = os.environ.get("MODEL_SERVER_HOST", "127.0.0.1")
# 9200 已按新协议留给前端content通道；内部model_server挪到9201，避免端口冲突。
MODEL_SERVER_UDP_PORT = int(os.environ.get("MODEL_SERVER_UDP_PORT", "9201"))

# 各类请求的超时时间：VLM/SD/Whisper推理可能比较慢，要给够；
# 但也不能无限等，不然uplink_udp里对应的处理线程会卡死很久
MODEL_SERVER_CHAT_TIMEOUT = float(os.environ.get("MODEL_SERVER_CHAT_TIMEOUT", "30"))
MODEL_SERVER_VOICE_TIMEOUT = float(os.environ.get("MODEL_SERVER_VOICE_TIMEOUT", "60"))
MODEL_SERVER_IMAGE_TIMEOUT = float(os.environ.get("MODEL_SERVER_IMAGE_TIMEOUT", "120"))

# ========== 语音/VLM 飞行指令 ==========
QWEN2VL_BASE_DIR = os.environ.get("QWEN2VL_BASE_DIR", "/home/elf/Project")
FLIGHT_PROMPT_FILE = os.environ.get(
    "FLIGHT_PROMPT_FILE", os.path.join(QWEN2VL_BASE_DIR, "flight_prompt.md")
)
VOICE_RECORD_SECONDS = int(os.environ.get("VOICE_RECORD_SECONDS", "5"))
VOICE_SAMPLE_RATE = 16000
# [修复] 原来这里是 VOICE_RECORD_DEVICE = int(...)，写死一个数字设备编号——
# 但这个编号是sounddevice.query_devices()扫描到的"排第几个"，不是USB硬件
# 固定ID，会随驱动加载顺序/USB插拔顺序变化(真实踩过这个坑)。而且这个变量
# 之前model_logic.py调用vsd.record_audio()时根本没传进去，是个没人用的
# 死配置，容易让人误以为改这个数字就能生效。
# 现在跟voice_to_sd.py里_find_record_device()的新逻辑对齐：改成按名字关键字
# 查找录音设备，config.py统一管这个关键字，作为唯一配置来源。
VOICE_RECORD_DEVICE_NAME_KEYWORD = os.environ.get(
    "VOICE_RECORD_DEVICE_NAME_KEYWORD", "1080P USB Camera"
)
VOICE_TMP_AUDIO_PATH = "/home/elf/Project/tmp_master_record.wav"

# 语音生图输出目录（生成后只把这个路径通过UDP回传给上位机，不做HTTP/静态目录服务；
# 上位机怎么拿到实际图片文件，由你们自己的部署方式决定，比如共享盘/后续单独传输）
IMAGE_OUTPUT_DIR = "/home/elf/Project/output"

# ========== 摄像头最新帧（供VLM图像理解读取） ==========
# gst推流pipeline用tee分一路持续覆盖这个JPEG文件；vlm_describe不传image_base64时，
# model_server会读取这里的最新帧转成base64喂给VLM。
CAMERA_LATEST_FRAME_PATH = os.environ.get("CAMERA_LATEST_FRAME_PATH", "/tmp/vlm_latest_frame.jpg")
CAMERA_FRAME_MAX_AGE_SECONDS = float(os.environ.get("CAMERA_FRAME_MAX_AGE_SECONDS", "3.0"))

# ========== 已有脚本路径（仅model_server进程用到，动态import复用） ==========
VOICE_TO_SD_SCRIPT_PATH = os.environ.get("VOICE_TO_SD_SCRIPT_PATH", "/home/elf/Project/voice_to_sd.py")
WHISPER_SCRIPT_PATH = "/home/elf/whisper/official_224/whisper_lite.py"
TRANSLATE_SCRIPT_PATH = "/home/elf/whisper/NLP/translate_lite.py"

# [注意] 真实出图用的是 voice_to_sd.py 里那份 run_rknn-lcm.py(真正LCM pipeline)，
# 不再用 sd_engine.py(那份是简化实现，已停用，只保留文件做参考)。
# VLM(Qwen2VL)模型路径由 vlm_engine.py 自己的 TONGFLY_VISION_MODEL/TONGFLY_LLM_MODEL/
# TONGFLY_RKLLM_LIB 环境变量管理；SD路径由 voice_to_sd.py 里的 SD_SCRIPT_PATH/SD_MODEL_DIR
# 常量管理(在那个文件顶部改)。这些都发生在model_server进程里，flight进程完全不需要关心。

# ========== 激光模组(SCREEN_DRAW画笔模式用) ==========
# [注] LASER_GPIO_LINE需要按实际接线改，这里的默认值只是占位。
LASER_GPIO_CHIP = os.environ.get("LASER_GPIO_CHIP", "gpiochip0")
LASER_GPIO_LINE = int(os.environ.get("LASER_GPIO_LINE", "17"))
# 有些激光驱动模组是低电平触发(接地导通)，不是高电平触发——按实际模组确认，
# 接反了会导致"代码认为关了，其实还亮着"这种最危险的情况。
LASER_ACTIVE_HIGH = os.environ.get("LASER_ACTIVE_HIGH", "1") not in ("0", "false", "False")