# -*- coding: utf-8 -*-
"""
uplink_udp.py -- front-end protocol adapter.

New Tongfei protocol:
  - UDP 9100: mode packets, {"mode": number}
  - UDP 9200: content packets for mode 1/6/7 only.
      mode 1: {"mode": 1, "text": [...]}
      mode 6: {"mode": 6, "text": "..."}
      mode 7: {"mode": 7, "text": "..."}
  - UDP 9300: output packets:
      {"type": "sd_result", "asr_text": "...", "prompt_en": "...", "image_path": "..."}
      {"type": "vlm_chat_result", "text": "..."}
      {"type": "vlm_vision_result", "text": "...", "image_path": "..."}

The old {"cmd": "..."} packets are still accepted on 9100 for quick manual debugging.
"""
import json
import re
import socket
import threading
import time

import config
import mode_manager as mm
from mode_manager import mode_manager
from flight_executor import flight_executor
import model_client

_reply_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def _output_target():
    return (config.OUTPUT_UDP_HOST, config.OUTPUT_UDP_PORT)


def send_reply(payload: dict):
    """Send one output packet to the Vite UDP bridge."""
    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        target = _output_target()
        _reply_sock.sendto(data, target)
        print(f"[uplink_udp] output -> {target}: {payload}")
    except Exception as e:
        print(f"[uplink_udp][output failed] {e}")


def _send_vlm_chat_result(text):
    if not text:
        return
    send_reply({"type": "vlm_chat_result", "text": text})


def _send_vlm_vision_result(text, image_path=None):
    if not text and not image_path:
        return
    payload = {"type": "vlm_vision_result", "text": text}
    if image_path:
        payload["image_path"] = image_path
    send_reply(payload)


def _send_sd_result(resp):
    if "error" in resp:
        print(f"[uplink_udp][SD生成失败] {resp['error']}")
        return
    send_reply({
        "type": "sd_result",
        "asr_text": resp.get("zh_text", ""),
        "prompt_en": resp.get("en_text", ""),
        "image_path": resp.get("path") or resp.get("image_path") or "",
    })


def _packet_desc(msg):
    return str(msg.get("describe", "") or "")


def _is_reset_packet(mode, describe):
    return mode == 0 or "重置飞控" in describe


def _safe_reset_flight():
    ok, reason = flight_executor.request_reset()
    if not ok:
        print(f"[uplink_udp] 拒绝重置飞控：{reason}。请先降落并确认在地面。")
        return
    mode_manager.force_idle("地面重置飞控")
    print(f"[uplink_udp] {reason}，正在重新初始化飞控执行器")
    if not flight_executor.is_runner_active():
        threading.Thread(
            target=flight_executor.run_forever,
            daemon=True,
            name="flight-executor-reset",
        ).start()


def _trigger_voice_flight():
    mode_manager.request_switch(mm.VOICE_VLM, source="mode=2 语音掌控飞行")
    import voice_vlm
    threading.Thread(target=voice_vlm.handle_voice_trigger, daemon=True).start()


def _handle_mode_packet(msg):
    mode = msg.get("mode")
    describe = _packet_desc(msg)

    if _is_reset_packet(mode, describe):
        _safe_reset_flight()
    elif mode == 1:
        mode_manager.request_switch(mm.UPLINK_VELOCITY, source=describe or "编程积木")
    elif mode == 2:
        _trigger_voice_flight()
    elif mode == 3:
        mode_manager.request_switch(mm.SCREEN_DRAW, source=describe or "创意喷绘")
    elif mode == 4:
        threading.Thread(target=_handle_gen_image, args=("",), daemon=True).start()
    elif mode == 5:
        print("[uplink_udp] 手势控制模式当前总控端尚未实现。")
    elif mode in (6, 7):
        # These modes have follow-up content on UDP 9200. Warm up VLM here, but
        # do not run inference or send output until the content packet arrives.
        threading.Thread(target=_warmup_vlm, args=(mode,), daemon=True).start()
        print(f"[uplink_udp] mode={mode} selected; warming up VLM and waiting for content packet on 9200")
    elif mode == 8:
        # [新增] 起飞指令，只走9100这一个mode包，不需要9200的content数据。
        # flight_executor.request_takeoff()内部会检查当前是不是"已经进入
        # OFFBOARD、还在等起飞指令"这个窗口，不是的话会拒绝并说明原因
        # (比如已经在飞了/还没连上飞控)，这里把结果打出来方便排查。
        ok, reason = flight_executor.request_takeoff()
        print(f"[uplink_udp] mode=8 起飞请求: {reason}")
    elif mode == 9:
        # [新增] 降落指令，同样只走9100，不需要9200的content数据。
        # request_land()内部不会做额外判断，任何时候都能发、降落永远优先，
        # 这跟legacy cmd里的"land"指令走的是同一个方法。
        flight_executor.request_land()
        print("[uplink_udp] mode=9 已收到降落请求")
    else:
        print(f"[uplink_udp] 未知mode指令: mode={mode}, describe={describe}")


def _extract_json(text: str):
    match = re.search(r"(\[.*\]|\{.*\})", text or "", flags=re.DOTALL)
    if not match:
        raise ValueError(f"输出里没找到JSON: {(text or '')[:200]!r}")
    payload = json.loads(match.group(1))
    return payload if isinstance(payload, list) else [payload]


def _as_float(action, key, default=0.0):
    value = action.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be a number, got {value!r}")


def _execute_velocity_actions(actions, source_mode):
    for i, action in enumerate(actions):
        if not isinstance(action, dict):
            print(f"[uplink_udp] 动作{i + 1}格式错误，期望object，实际={action!r}")
            return False
        if flight_executor.should_stop_current_action():
            print("[uplink_udp] 收到安全停止信号，动作序列已中止。")
            return False
        if not mode_manager.is_active(source_mode):
            print(f"[uplink_udp] 模式已切换，剩余{len(actions) - i}个动作已丢弃。")
            return False

        action_type = action.get("type", "velocity")
        try:
            duration = min(max(_as_float(action, "duration", 1.0), 0.0), 6.0)
        except ValueError as e:
            print(f"[uplink_udp] 动作{i + 1}解析失败: {e}")
            return False
        if action_type == "land":
            flight_executor.request_land()
            print("[uplink_udp] 已收到动作序列中的降落指令，开始降落。")
            return True

        try:
            vx = _as_float(action, "vx", 0.0)
            vy = _as_float(action, "vy", 0.0)
            vz = _as_float(action, "vz", 0.0)
            yaw_rate = _as_float(action, "yaw_rate", 0.0)
        except ValueError as e:
            print(f"[uplink_udp] 动作{i + 1}解析失败: {e}")
            return False

        # Front-end protocol: vz > 0 means up. MAVSDK body velocity here uses
        # down_mps > 0 as down, so the sign must be inverted.
        down_mps = -vz
        print(
            f"[uplink_udp] 执行动作{i + 1}/{len(actions)}: "
            f"vx={vx} vy={vy} vz={vz}(up+) -> down_mps={down_mps} "
            f"yaw_rate={yaw_rate} duration={duration}s"
        )

        end_time = time.time() + duration
        while time.time() < end_time:
            if flight_executor.should_stop_current_action():
                print("[uplink_udp] 收到安全停止信号，动作序列已中止。")
                return False
            if not mode_manager.is_active(source_mode):
                print("[uplink_udp] 模式已切换，当前动作已停止。")
                return False
            flight_executor.set_velocity_body(source_mode, vx, vy, down_mps, yaw_rate)
            time.sleep(0.1)

    flight_executor.set_velocity_body(source_mode, 0.0, 0.0, 0.0, 0.0)
    return True


def _handle_block_actions(msg):
    actions = msg.get("text") or []
    if not isinstance(actions, list) or not actions:
        print("[uplink_udp] 积木编译结果里没有可执行的 text 动作数组。")
        return
    mode_manager.request_switch(mm.UPLINK_VELOCITY, source="编程积木编译结果")
    ok = _execute_velocity_actions(actions, mm.UPLINK_VELOCITY)
    if ok and not flight_executor.should_stop_current_action():
        mode_manager.request_switch(mm.IDLE, source="积木动作执行完成")


def _handle_text_flight(text):
    if not text:
        print("[uplink_udp] 文本掌控飞行缺少 payload.text。")
        return
    mode_manager.request_switch(mm.VOICE_VLM, source="文本掌控飞行")
    resp = model_client.vlm_flight_command(text, frontend_mode=2)
    if "error" in resp:
        print(f"[uplink_udp] 飞行指令解析失败: {resp['error']}")
        return
    raw_output = resp.get("result") or resp.get("response") or ""
    try:
        actions = _extract_json(raw_output)
    except Exception as e:
        print(f"[uplink_udp] 飞行指令JSON解析失败: {e}; raw_output={raw_output!r}")
        return
    ok = _execute_velocity_actions(actions, mm.VOICE_VLM)
    if ok and not flight_executor.should_stop_current_action():
        mode_manager.request_switch(mm.IDLE, source="文本飞行动作执行完成")


def _handle_content_packet(msg):
    mode = msg.get("mode")
    describe = _packet_desc(msg)

    if mode == 1:
        # [修复] 之前这里是同步调用_handle_block_actions()，而这个函数内部
        # 是一串time.sleep()循环(每个动作最长6秒，可能多个动作连续执行)。
        # _handle_content_packet()是在_serve_udp()的recvfrom()收包循环里
        # 直接同步调用的，不像mode 6/7那样丢给线程——意味着一段较长的积木
        # 动作序列执行期间(可能持续几十秒)，9200这个content端口不会再处理
        # 任何新包，跟mode 6/7的处理方式不一致。这里改成跟mode 6/7一样起
        # 后台线程，让content监听循环能继续及时收下一个包。
        threading.Thread(target=_handle_block_actions, args=(msg,), daemon=True).start()
    elif mode == 6:
        question = msg.get("text") or "请查看当前画面。"
        threading.Thread(
            target=_handle_vlm_describe,
            args=(question, msg.get("image_base64"), mode),
            daemon=True,
        ).start()
    elif mode == 7:
        text = msg.get("text") or ""
        threading.Thread(target=_handle_vlm_chat, args=(text, mode), daemon=True).start()
    else:
        print(f"[uplink_udp] 未知content指令: mode={mode}, describe={describe}")


def _warmup_vlm(mode):
    resp = model_client.health()
    if "error" in resp:
        print(f"[uplink_udp] VLM预热失败(mode={mode}): {resp['error']}")
        return
    if resp.get("vlm"):
        print(f"[uplink_udp] VLM已在内存中(mode={mode})")
        return
    if resp.get("vlm_loading"):
        print(f"[uplink_udp] VLM正在加载中(mode={mode})")
        return
    resp = model_client.vlm_chat("请只回复：ready", frontend_mode=mode)
    if "error" in resp:
        print(f"[uplink_udp] VLM预热失败(mode={mode}): {resp['error']}")
    else:
        print(f"[uplink_udp] VLM预热完成(mode={mode})")


def _handle_legacy_cmd(msg):
    cmd = msg.get("cmd")
    if cmd == "switch_mode":
        mode_manager.request_switch(msg.get("mode", ""), source="legacy cmd")
    elif cmd == "velocity":
        ok = flight_executor.set_velocity_body(
            mm.UPLINK_VELOCITY,
            forward_mps=float(msg.get("vx", 0.0)),
            right_mps=float(msg.get("vy", 0.0)),
            down_mps=float(msg.get("vz", 0.0)),
            yawspeed_degs=float(msg.get("yawspeed", 0.0)),
        )
        if not ok:
            print("[uplink_udp] legacy velocity rejected")
    elif cmd == "land":
        flight_executor.request_land()
    elif cmd == "vlm_chat":
        threading.Thread(
            target=_handle_vlm_chat,
            args=(msg.get("text", ""), msg.get("frontend_mode")),
            daemon=True,
        ).start()
    elif cmd == "vlm_describe":
        threading.Thread(
            target=_handle_vlm_describe,
            args=(msg.get("question", ""), msg.get("image_base64"), msg.get("frontend_mode")),
            daemon=True,
        ).start()
    elif cmd == "gen_image":
        threading.Thread(target=_handle_gen_image, args=(msg.get("text", ""),), daemon=True).start()
    elif cmd == "voice_trigger":
        _trigger_voice_flight()
    else:
        print(f"[uplink_udp] 未知legacy cmd: {cmd}")


def _handle_packet(data: bytes, addr, channel):
    try:
        msg = json.loads(data.decode("utf-8"))
    except Exception as e:
        print(f"[uplink_udp][parse failed] {e} raw={data[:100]!r}")
        return

    print(f"[uplink_udp] {channel} <- {addr}: {msg}")
    if "cmd" in msg:
        _handle_legacy_cmd(msg)
    elif channel == "mode":
        _handle_mode_packet(msg)
    else:
        _handle_content_packet(msg)


def _handle_vlm_chat(text, frontend_mode=None):
    resp = model_client.vlm_chat(text, frontend_mode=frontend_mode)
    if "error" in resp:
        print(f"[uplink_udp] VLM问答失败: {resp['error']}")
    else:
        _send_vlm_chat_result(resp.get("result") or resp.get("response") or "")


def _handle_vlm_describe(question, image_base64, frontend_mode=None):
    resp = model_client.vlm_describe(question, image_base64, frontend_mode=frontend_mode)
    if "error" in resp:
        print(f"[uplink_udp] 图像理解失败: {resp['error']}")
    else:
        _send_vlm_vision_result(
            resp.get("result") or resp.get("response") or "",
            image_path=resp.get("image_path"),
        )


def _handle_gen_image(text):
    resp = model_client.gen_image(text, frontend_mode=4)
    _send_sd_result(resp)


def _serve_udp(host, port, channel):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, port))
    print(f"[uplink_udp] listening {channel} {host}:{port}")
    while True:
        try:
            data, addr = sock.recvfrom(65535)
            _handle_packet(data, addr, channel)
        except Exception as e:
            print(f"[uplink_udp][{channel} receive error] {e}")


def start_uplink_listener():
    """Run in one daemon thread; internally starts mode and content listeners."""
    threading.Thread(
        target=_serve_udp,
        args=(config.UPLINK_UDP_HOST, config.UPLINK_UDP_PORT, "mode"),
        daemon=True,
        name="udp-mode-9100",
    ).start()
    threading.Thread(
        target=_serve_udp,
        args=(config.CONTENT_UDP_HOST, config.CONTENT_UDP_PORT, "content"),
        daemon=True,
        name="udp-content-9200",
    ).start()
    while True:
        time.sleep(3600)