# -*- coding: utf-8 -*-
"""
model_client.py —— [进程A] 调 model_server进程(进程B) 的客户端，纯UDP，不用requests/HTTP。

每次调用：开一个临时UDP socket，发一个JSON包过去，同步等对方回一个JSON包，超时就返回
{"error": "..."}。model_server那边处理耗时的推理任务时不会阻塞这里——因为
调用方(uplink_udp.py/voice_vlm.py)本来就是在自己的daemon线程里调这些函数，
不会卡住UDP收包主循环或者飞控setpoint发送。

[容错] model_server不可达/超时/推理内部出错，统一都是返回{"error": "..."}，
调用方只需要检查"error" in resp，不用关心具体是网络问题还是模型出错了什么。
"""
import json
import socket
import uuid

import config


def _request(cmd, payload, timeout):
    payload = dict(payload)
    payload["cmd"] = cmd
    payload["request_id"] = uuid.uuid4().hex
    short_id = payload["request_id"][:8]

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        print(f"[model_client] -> 发送 cmd={cmd} id={short_id} 到 model_server "
              f"({config.MODEL_SERVER_HOST}:{config.MODEL_SERVER_UDP_PORT})")
        sock.sendto(data, (config.MODEL_SERVER_HOST, config.MODEL_SERVER_UDP_PORT))
        resp_data, _ = sock.recvfrom(65535)
        resp = json.loads(resp_data.decode("utf-8"))
        status = "错误: " + resp["error"] if "error" in resp else "成功"
        print(f"[model_client] <- 收到 cmd={cmd} id={short_id} 响应 ({status})")
        return resp
    except socket.timeout:
        print(f"[model_client] <- cmd={cmd} id={short_id} 超时({timeout}s)未收到响应")
        return {"error": f"model_server超过{timeout}秒未响应(cmd={cmd})"}
    except ConnectionRefusedError:
        print(f"[model_client] <- cmd={cmd} id={short_id} 连接被拒绝，model_server可能没启动")
        return {"error": "model_server不可达(ConnectionRefused)，检查run_model_server.py是否在跑"}
    except Exception as e:
        print(f"[model_client] <- cmd={cmd} id={short_id} 异常: {e}")
        return {"error": f"请求异常: {e}"}
    finally:
        sock.close()


def _with_frontend_mode(payload, frontend_mode):
    payload = dict(payload)
    if frontend_mode is not None:
        payload["frontend_mode"] = frontend_mode
    return payload


def vlm_chat(text: str, frontend_mode=None):
    return _request("vlm_chat", _with_frontend_mode({"text": text}, frontend_mode),
                    config.MODEL_SERVER_CHAT_TIMEOUT)


def vlm_describe(question: str, image_base64: str = None, frontend_mode=None):
    return _request("vlm_describe", _with_frontend_mode(
        {"question": question, "image_base64": image_base64}, frontend_mode),
                     config.MODEL_SERVER_CHAT_TIMEOUT)


def vlm_flight_command(text: str, frontend_mode=None):
    return _request("vlm_flight_command", _with_frontend_mode({"text": text}, frontend_mode),
                    config.MODEL_SERVER_CHAT_TIMEOUT)


def gen_image(text: str = "", frontend_mode=None):
    return _request("voice_gen_image", _with_frontend_mode({"text": text}, frontend_mode),
                    config.MODEL_SERVER_IMAGE_TIMEOUT)


def voice_flight_command(duration: float = None, frontend_mode=None):
    payload = {}
    if duration is not None:
        payload["duration"] = duration
    payload = _with_frontend_mode(payload, frontend_mode)
    return _request("voice_flight_command", payload, config.MODEL_SERVER_VOICE_TIMEOUT)


def health():
    return _request("health", {}, 3)
