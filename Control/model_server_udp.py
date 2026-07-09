# -*- coding: utf-8 -*-
"""
model_server_udp.py —— [进程B] 纯UDP服务端，不用FastAPI/HTTP。

协议(JSON over UDP，每个请求一个包，每个响应一个包)：
    请求: {"cmd": "vlm_chat", "request_id": "...", "text": "..."}
    响应: {"request_id": "...", "result": "...", ...} 或 {"request_id": "...", "error": "..."}

request_id由调用方(model_client.py)生成，纯粹用来对应请求和响应，
当前实现是"一发一收"同步等待，用不用其实无所谓，但留着方便以后扩展成
"连续发多个请求，用request_id区分谁是谁的响应"。

每个请求进来都开一个新线程处理，避免一个慢请求(比如生图要好几秒)卡住整个UDP收包循环。
"""
import json
import logging
import socket
import threading

import config
import model_logic

logger = logging.getLogger(__name__)


def _handle_request(sock, msg, addr):
    cmd = msg.get("cmd")
    request_id = msg.get("request_id")
    frontend_mode = msg.get("frontend_mode")
    short_id = (request_id or "")[:8]
    print(f"[model_server_udp] <- 收到请求 cmd={cmd} id={short_id} 来自 {addr}")
    try:
        if cmd == "vlm_chat":
            result = model_logic.run_vlm_chat(msg.get("text", ""), frontend_mode)
        elif cmd == "vlm_describe":
            result = model_logic.run_vlm_describe(
                msg.get("question", ""), msg.get("image_base64"), frontend_mode
            )
        elif cmd == "vlm_flight_command":
            result = model_logic.run_vlm_flight_command(msg.get("text", ""), frontend_mode)
        elif cmd == "sd_generate":
            result = model_logic.run_sd_generate(
                msg.get("prompt", ""), msg.get("width", 512), msg.get("height", 512),
                msg.get("steps", 4), msg.get("guidance", 7.5), frontend_mode,
            )
        elif cmd == "voice_flight_command":
            result = model_logic.run_voice_flight_command(msg.get("duration"), frontend_mode)
        elif cmd == "voice_gen_image":
            result = model_logic.run_voice_gen_image(
                msg.get("text", ""), msg.get("duration"), frontend_mode
            )
        elif cmd == "reload_flight_prompt":
            result = model_logic.reload_flight_prompt()
        elif cmd == "health":
            result = model_logic.get_health()
        else:
            result = {"error": f"未知cmd: {cmd}"}
    except model_logic.LogicError as e:
        result = {"error": str(e)}
    except Exception as e:
        logger.exception(f"[model_server_udp] 处理{cmd}时发生未捕获异常")
        result = {"error": f"内部异常: {e}"}

    result["request_id"] = request_id
    status = "错误: " + result["error"] if "error" in result else "成功"
    print(f"[model_server_udp] -> 回复 cmd={cmd} id={short_id} 到 {addr} ({status})")
    try:
        data = json.dumps(result, ensure_ascii=False).encode("utf-8")
        sock.sendto(data, addr)
    except Exception as e:
        logger.error(f"[model_server_udp] 回包发送失败: {e}")


def serve():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((config.MODEL_SERVER_HOST, config.MODEL_SERVER_UDP_PORT))
    print(f"[model_server_udp] 正在监听flight进程的请求 "
          f"{config.MODEL_SERVER_HOST}:{config.MODEL_SERVER_UDP_PORT} ...")
    while True:
        try:
            data, addr = sock.recvfrom(65535)
            try:
                msg = json.loads(data.decode("utf-8"))
            except Exception as e:
                print(f"[model_server_udp][解析失败] {e} 原始数据: {data[:100]!r}")
                continue
            threading.Thread(target=_handle_request, args=(sock, msg, addr), daemon=True).start()
        except Exception as e:
            print(f"[model_server_udp][接收异常] {e}")
