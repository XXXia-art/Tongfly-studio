# -*- coding: utf-8 -*-
"""
voice_vlm.py —— [flight进程侧] 语音控制飞行的执行部分。

跟之前版本的关键区别：录音/Whisper识别/VLM推理这些全部搬到了model_server进程
(见 main.py 的 /voice/flight_command)。这个文件现在只做两件事：
    1. 通过 model_client.voice_flight_command() 发一个HTTP请求，等着拿JSON动作序列
    2. 把动作序列在flight_executor上执行掉，全程带mode_manager互斥检查

[容错] 如果model_server不可达/超时/推理出错，model_client会返回{"error":...}，
这里直接把错误通过UDP回传给上位机，不会让flight进程卡住或崩溃。
"""
import json
import re
import time

import mode_manager as mm
from mode_manager import mode_manager
from flight_executor import flight_executor
import model_client


def _extract_json(text: str):
    match = re.search(r"(\[.*\]|\{.*\})", text, flags=re.DOTALL)
    if not match:
        raise ValueError(f"输出里没找到JSON: {text[:200]!r}")
    payload = json.loads(match.group(1))
    if isinstance(payload, dict):
        payload = [payload]
    return payload


def _execute_actions(actions):
    for i, action in enumerate(actions):
        if not mode_manager.is_active(mm.VOICE_VLM):
            print(f"[voice_vlm] 模式已切换，剩余{len(actions) - i}个动作全部丢弃")
            return False

        a_type = action.get("type", "velocity")
        duration = float(action.get("duration", 1.0))
        duration = min(duration, 6.0)  # [安全] 单段动作硬上限6秒

        if a_type == "land":
            print("[voice_vlm] 动作: land")
            flight_executor.request_land()
            return True

        if a_type == "hover":
            print(f"[voice_vlm] 动作: hover {duration}s")
            flight_executor.set_velocity_body(mm.VOICE_VLM, 0.0, 0.0, 0.0, 0.0)
            end_time = time.time() + duration
            while time.time() < end_time:
                if flight_executor.should_stop_current_action():
                    print("[voice_vlm] 收到安全停止信号，hover动作中止")
                    return False
                if not mode_manager.is_active(mm.VOICE_VLM):
                    print("[voice_vlm] hover中模式被切走，立即停止")
                    return False
                time.sleep(0.1)
            continue

        vx = float(action.get("vx", 0.0))
        vy = float(action.get("vy", 0.0))
        vz = float(action.get("vz", 0.0))
        yawspeed = float(action.get("yawspeed", 0.0))
        print(f"[voice_vlm] 动作: velocity vx={vx} vy={vy} vz={vz} "
              f"yawspeed={yawspeed} 持续{duration}s")

        end_time = time.time() + duration
        while time.time() < end_time:
            if flight_executor.should_stop_current_action():
                print("[voice_vlm] 收到安全停止信号，速度动作中止")
                return False
            if not mode_manager.is_active(mm.VOICE_VLM):
                print("[voice_vlm] 执行中模式被切走，立即停止")
                return False
            flight_executor.set_velocity_body(mm.VOICE_VLM, vx, vy, vz, yawspeed)
            time.sleep(0.1)

    flight_executor.set_velocity_body(mm.VOICE_VLM, 0.0, 0.0, 0.0, 0.0)
    return True


def handle_voice_trigger():
    """由 uplink_udp.py 收到 {"cmd":"voice_trigger"} 时调用（必须先切到VOICE_VLM模式）。"""
    if not mode_manager.is_active(mm.VOICE_VLM):
        print("[voice_vlm] 当前模式不是VOICE_VLM，请先switch_mode")
        return

    print("[voice_vlm] 请求model_server做语音识别+飞行指令解析 ...")
    resp = model_client.voice_flight_command(frontend_mode=2)

    if "error" in resp:
        print(f"[voice_vlm][model_server错误] {resp['error']}")
        return

    zh_text = resp.get("zh_text", "")
    raw_output = resp.get("raw_output", "")
    print(f"[voice_vlm] 识别文本: {zh_text}")
    print(f"[voice_vlm] LLM原始输出: {raw_output}")

    try:
        actions = _extract_json(raw_output)
    except Exception as e:
        print(f"[voice_vlm][解析JSON失败] {e}")
        return

    print(f"[voice_vlm] 解析动作: {actions}")

    # 模式可能在网络往返/model_server推理这段时间里被切走了，执行前必须再确认一次
    if not mode_manager.is_active(mm.VOICE_VLM):
        print("[voice_vlm] 拿到动作时模式已经不是VOICE_VLM了，放弃执行")
        return

    ok = _execute_actions(actions)
    if ok and not flight_executor.should_stop_current_action():
        flight_executor.request_hold_current_position(mm.VOICE_VLM)
