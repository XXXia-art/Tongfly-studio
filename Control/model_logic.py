# -*- coding: utf-8 -*-
"""
model_logic.py —— [进程B] 所有AI相关的实际逻辑，不含任何网络代码。

[本版本重点] 你板子是三核NPU，但内存不够，所以NPU并行不是现在要解决的问题——
现在的"同一时刻只有一个模型常驻"(model_memory_lock)这个设计不变，继续保持。

这一版把"加载耗时"、"每次对话/生图/语音识别的输入输出内容和各阶段耗时"都补全了，
尽量还原你原来 voice_to_sd.py / vlm_engine.py 里那些 print/logger.info 能看到的
关键信息(哪一步在跑、跑了多久、输入输出是什么)，只是现在这些信息在model_server
这个进程里打印，不会被转发给上位机——上位机只收到最终结果(通过flight进程回传)，
中间过程只在这个终端里能看到。
"""
import base64
import logging
import os
import shutil
import threading
import time

import config
import prompt_utils
from vlm_engine import vlm_engine
from real_sd_adapter import sd_engine  # 真实LCM pipeline，替换掉简化版sd_engine.py
from voice_to_sd_singleton import get_voice_to_sd

logging.basicConfig(level=logging.INFO)

vlm_lock = threading.Lock()
sd_lock = threading.Lock()
model_memory_lock = threading.Lock()
_active_model_kind = None
_active_frontend_mode = None
# [安全/正确性] 保护_flight_system_prompt/_flight_few_shot这对全局变量的读写：
# reload_flight_prompt()会重新赋值它们，而run_vlm_flight_command/
# run_voice_flight_command会读取它们喂给VLM。没有锁的话，reload发生在两次
# 读取之间，理论上可能读到"新system_prompt配旧few_shot"这种不匹配的组合。
flight_prompt_lock = threading.Lock()

# 飞行指令解析用的system prompt + few-shot，进程启动时加载一次并缓存
_flight_system_prompt, _flight_few_shot = prompt_utils.load_prompt_messages(config.FLIGHT_PROMPT_FILE)


def _get_flight_prompt():
    """读取当前缓存的system_prompt+few_shot，加锁保证读到的是同一次reload的配对结果。"""
    with flight_prompt_lock:
        return _flight_system_prompt, _flight_few_shot


class LogicError(Exception):
    """业务逻辑错误，跟网络层解耦，model_server_udp.py捕获这个转成{"error":...}回包。"""
    pass


class _Stage:
    """给一段代码计时用的小工具，进入/退出各打一行，方便看每一步耗时。
    用法: with _Stage("VLM chat推理"): result = vlm_engine.chat(text)"""

    def __init__(self, label):
        self.label = label

    def __enter__(self):
        self.t0 = time.time()
        print(f"[model_logic] >>> 开始: {self.label}")
        return self

    def __exit__(self, exc_type, exc, tb):
        elapsed = time.time() - self.t0
        if exc_type is not None:
            print(f"[model_logic] <<< 失败: {self.label} (耗时{elapsed:.2f}s) 错误: {exc}")
        else:
            print(f"[model_logic] <<< 完成: {self.label} (耗时{elapsed:.2f}s)")
        return False  # 不吞异常，让外层的except继续处理


def _mode_label(frontend_mode):
    return "unknown" if frontend_mode is None else str(frontend_mode)


def _remember_active_model(kind, frontend_mode):
    global _active_model_kind, _active_frontend_mode
    _active_model_kind = kind
    if frontend_mode is not None:
        _active_frontend_mode = frontend_mode


def ensure_vlm_active(frontend_mode=None):
    if vlm_engine.vision is not None:
        if _active_frontend_mode == frontend_mode:
            print(f"[model_logic] mode={_mode_label(frontend_mode)} 继续使用内存中的VLM")
        else:
            print(
                f"[model_logic] VLM已在内存中，前端mode "
                f"{_mode_label(_active_frontend_mode)} -> {_mode_label(frontend_mode)}，无需重载"
            )
        _remember_active_model("vlm", frontend_mode)
        return
    print(
        f"[model_logic] 需要切换到VLM：当前模型={_active_model_kind or 'none'}，"
        f"前端mode {_mode_label(_active_frontend_mode)} -> {_mode_label(frontend_mode)}"
    )
    with _Stage("VLM/SD切换 -> 加载VLM"):
        sd_engine.release()
        vlm_engine.load()
    _remember_active_model("vlm", frontend_mode)


def ensure_sd_active(frontend_mode=None):
    if sd_engine.pipe is not None:
        if _active_frontend_mode == frontend_mode:
            print(f"[model_logic] mode={_mode_label(frontend_mode)} 继续使用内存中的SD")
        else:
            print(
                f"[model_logic] SD已在内存中，前端mode "
                f"{_mode_label(_active_frontend_mode)} -> {_mode_label(frontend_mode)}，无需重载"
            )
        _remember_active_model("sd", frontend_mode)
        return
    print(
        f"[model_logic] 需要切换到SD：当前模型={_active_model_kind or 'none'}，"
        f"前端mode {_mode_label(_active_frontend_mode)} -> {_mode_label(frontend_mode)}"
    )
    with _Stage("VLM/SD切换 -> 加载SD"):
        vlm_engine.release()
        sd_engine.load()
    _remember_active_model("sd", frontend_mode)


def startup():
    """
    进程启动时调用一次。

    [改动] 不再在启动时就把VLM预加载进内存——现在的原则是"上位机发什么指令，
    才加载对应的模型"：
        - 收到 vlm_chat/vlm_describe/voice_trigger(语音控制飞行，走chat_flight
          用flight_prompt.md这份脚本) -> ensure_vlm_active() 才加载VLM
        - 收到 gen_image -> ensure_sd_active() 才加载SD

    [重要，跟之前版本的关键区别] 板子上实际部署的voice_to_sd.py("集大成版")里，
    Whisper是每次transcribe_audio()调用时现场加载、用完就release()，不是
    常驻的——没有后台并行加载这回事，也没有"预热"的意义(反正每次都要重新
    加载)。翻译模型(get_translate_module())和SD(get_sd_pipe())则是"第一次
    调用才加载，之后缓存"的懒加载单例，同样没有必要在进程启动时主动触发。

    [录音设备] voice_to_sd.py里RECORD_DEVICE_NAME_KEYWORD是模块级常量，
    在模块被动态加载的那一刻(即第一次调用get_voice_to_sd())就会读一次
    os.environ——必须在那之前把config.py里配置的关键字设进环境变量，
    这样config.py才是唯一的配置来源，不用另外单独export一次。
    """
    os.environ.setdefault("RECORD_DEVICE_NAME_KEYWORD", config.VOICE_RECORD_DEVICE_NAME_KEYWORD)
    print("[model_logic] ===== 进程启动 =====")
    print("[model_logic] 不预加载任何模型：Whisper每次现场加载+释放，"
          "翻译/SD是懒加载单例，都等第一次真正用到时才加载")
    os.makedirs(config.IMAGE_OUTPUT_DIR, exist_ok=True)
    print("[model_logic] ===== 启动流程完成，等待上位机指令 =====")


def shutdown():
    global _active_model_kind, _active_frontend_mode
    print("[model_logic] 收到关闭信号，释放模型 ...")
    with model_memory_lock:
        with _Stage("关闭时释放VLM+SD"):
            sd_engine.release()
            vlm_engine.release()
        _active_model_kind = None
        _active_frontend_mode = None


def get_health():
    """
    [跟之前版本的关键区别] 真实版voice_to_sd.py里Whisper是每次调用现场加载+
    释放、翻译/SD是懒加载单例，都没有"常驻就绪状态"这个概念，所以不再报告
    whisper_ready/translate_ready这两个字段(报告了也没有意义，永远要么是
    False要么强行猜一个值，不如干脆去掉，避免误导)。
    """
    return {
        "vlm": vlm_engine.vision is not None,
        "vlm_loading": vlm_engine.loading,
        "vlm_error": vlm_engine.last_error,
        "sd": sd_engine.pipe is not None,
        "sd_loading": sd_engine.loading,
        "sd_error": sd_engine.last_error,
        "active_model": _active_model_kind,
        "active_frontend_mode": _active_frontend_mode,
    }


def _read_camera_frame_base64():
    """读取gst pipeline落盘的最新JPEG帧，保存快照，并转成base64。"""
    path = config.CAMERA_LATEST_FRAME_PATH
    if not os.path.exists(path):
        raise LogicError(f"摄像头最新帧不存在: {path}")

    age = time.time() - os.path.getmtime(path)
    if age > config.CAMERA_FRAME_MAX_AGE_SECONDS:
        raise LogicError(
            f"摄像头最新帧已过期: {path}, age={age:.2f}s "
            f"> {config.CAMERA_FRAME_MAX_AGE_SECONDS:.2f}s"
        )

    with open(path, "rb") as f:
        raw = f.read()
    if not raw:
        raise LogicError(f"摄像头最新帧为空: {path}")

    os.makedirs(config.IMAGE_OUTPUT_DIR, exist_ok=True)
    snapshot_path = os.path.join(config.IMAGE_OUTPUT_DIR, f"vlm_frame_{int(time.time() * 1000)}.jpg")
    shutil.copyfile(path, snapshot_path)
    return base64.b64encode(raw).decode("ascii"), snapshot_path


def run_vlm_chat(text: str, frontend_mode=None):
    if not text:
        raise LogicError("Missing text")
    print(f"[model_logic] [VLM问答] 输入: {text!r}")
    t0 = time.time()
    try:
        with model_memory_lock:
            ensure_vlm_active(frontend_mode)
            with vlm_lock:
                with _Stage("VLM chat推理"):
                    result = vlm_engine.chat(text)
        print(f"[model_logic] [VLM问答] 输出: {result!r}  (总耗时{time.time()-t0:.2f}s)")
        return {"result": result, "response": result}
    except Exception as e:
        logging.exception("VLM chat failed")
        raise LogicError(str(e))


def run_vlm_describe(question: str, image_base64: str = None, frontend_mode=None):
    question = question or "请描述当前画面。"
    frame_path = None
    t0 = time.time()
    try:
        if not image_base64:
            with _Stage("读取摄像头最新帧"):
                image_base64, frame_path = _read_camera_frame_base64()
        has_image = bool(image_base64)
        print(f"[model_logic] [VLM图像理解] 问题: {question!r}  带图: {has_image}")
        with model_memory_lock:
            ensure_vlm_active(frontend_mode)
            with vlm_lock:
                with _Stage("VLM describe推理"):
                    result = vlm_engine.describe(question, image_base64)
        print(f"[model_logic] [VLM图像理解] 输出: {result!r}  (总耗时{time.time()-t0:.2f}s)")
        resp = {"result": result, "response": result}
        if frame_path:
            resp["image_path"] = frame_path
        return resp
    except Exception as e:
        logging.exception("VLM describe failed")
        raise LogicError(str(e))


def run_vlm_flight_command(user_text: str, frontend_mode=None):
    if not user_text:
        raise LogicError("Missing user_text")
    print(f"[model_logic] [文字->飞行指令] 输入: {user_text!r}")
    t0 = time.time()
    try:
        with model_memory_lock:
            ensure_vlm_active(frontend_mode)
            with vlm_lock:
                with _Stage("VLM飞行指令解析推理"):
                    system_prompt, few_shot = _get_flight_prompt()
                    result = vlm_engine.chat_flight(system_prompt, few_shot, user_text)
        print(f"[model_logic] [文字->飞行指令] LLM原始输出: {result!r}  (总耗时{time.time()-t0:.2f}s)")
        return {"result": result, "response": result}
    except Exception as e:
        logging.exception("VLM flight command parse failed")
        raise LogicError(str(e))


def run_sd_generate(prompt, width=512, height=512, steps=4, guidance=7.5, frontend_mode=None):
    print(f"[model_logic] [SD生图] prompt: {prompt!r}  {width}x{height} steps={steps} guidance={guidance}")
    t0 = time.time()
    try:
        with model_memory_lock:
            ensure_sd_active(frontend_mode)
            with sd_lock:
                with _Stage("SD生成推理"):
                    img = sd_engine.generate(prompt, width, height, steps, guidance)
        print(f"[model_logic] [SD生图] 完成，base64长度={len(img)}  (总耗时{time.time()-t0:.2f}s)")
        return {"image": img, "image_base64": img}
    except Exception as e:
        logging.exception("SD generate failed")
        raise LogicError(str(e))


def _record_and_transcribe(vsd, duration, label):
    """录音 -> Whisper识别 -> 删除临时音频文件。抽出来是因为
    run_voice_flight_command和run_voice_gen_image里这段完全重复。
    label只是用来在_Stage的打印里区分是哪个功能触发的录音，不影响行为。"""
    duration = duration or config.VOICE_RECORD_SECONDS
    print(f"[model_logic] [{label}] 未提供文本，开始录音{duration}秒")
    with _Stage(f"录音{duration}秒"):
        audio_path = vsd.record_audio(duration=duration)
    with _Stage("Whisper语音识别"):
        zh_text = vsd.transcribe_audio(audio_path)
    try:
        os.remove(audio_path)
    except OSError:
        pass
    return zh_text


def run_voice_flight_command(duration=None, frontend_mode=None):
    """录音 -> Whisper识别 -> vlm_engine.chat_flight(飞行专用prompt) -> 返回JSON动作文本。
    [注] record_audio/transcribe_audio内部本来就有logger.info打印(音量/识别结果等)，
    这里额外包一层耗时统计，方便看整个链路里哪一步最慢。"""
    t_total = time.time()
    try:
        vsd = get_voice_to_sd()
        zh_text = _record_and_transcribe(vsd, duration, "语音控制飞行")

        if not zh_text:
            raise LogicError("未识别到有效文本")

        print(f"[model_logic] [语音控制飞行] 识别文本: {zh_text!r}")

        with model_memory_lock:
            ensure_vlm_active(frontend_mode)
            with vlm_lock:
                with _Stage("VLM飞行指令解析推理"):
                    system_prompt, few_shot = _get_flight_prompt()
                    raw_output = vlm_engine.chat_flight(system_prompt, few_shot, zh_text)

        print(f"[model_logic] [语音控制飞行] LLM原始输出: {raw_output!r}  "
              f"(全流程总耗时{time.time()-t_total:.2f}s)")
        return {"zh_text": zh_text, "raw_output": raw_output}
    except LogicError:
        raise
    except Exception as e:
        logging.exception("语音飞行指令解析失败")
        raise LogicError(str(e))


def run_voice_gen_image(text="", duration=None, frontend_mode=None):
    """(有文字就跳过录音) -> 翻译成英文 -> 真实LCM pipeline生成 -> 落盘，只返回路径。"""
    t_total = time.time()
    try:
        vsd = get_voice_to_sd()

        if text:
            zh_text = text
            print(f"[model_logic] [语音/文字生图] 使用传入文本，跳过录音: {zh_text!r}")
        else:
            zh_text = _record_and_transcribe(vsd, duration, "语音/文字生图")

        if not zh_text:
            raise LogicError("没有可用的文本用于生图")

        with _Stage("中译英翻译"):
            en_text = vsd.translate_zh_to_en(zh_text)
        print(f"[model_logic] [语音/文字生图] 中文: {zh_text!r}  英文: {en_text!r}")

        with model_memory_lock:
            ensure_sd_active(frontend_mode)
            with sd_lock:
                with _Stage("SD生成图片(含落盘)"):
                    out_path = vsd.generate_image_with_sd(en_text)

        filename = os.path.basename(out_path)
        print(f"[model_logic] [语音/文字生图] 已保存: {out_path}  "
              f"(全流程总耗时{time.time()-t_total:.2f}s)")
        return {
            "zh_text": zh_text,
            "en_text": en_text,
            "path": out_path,
            "filename": filename,
        }
    except LogicError:
        raise
    except Exception as e:
        logging.exception("语音/文字生图失败")
        raise LogicError(str(e))


def reload_flight_prompt():
    global _flight_system_prompt, _flight_few_shot
    print("[model_logic] 重新加载 flight_prompt.md ...")
    system_prompt, few_shot = prompt_utils.load_prompt_messages(config.FLIGHT_PROMPT_FILE)
    with flight_prompt_lock:
        _flight_system_prompt, _flight_few_shot = system_prompt, few_shot
    return {"ok": True, "system_prompt_len": len(system_prompt), "few_shot_count": len(few_shot)}