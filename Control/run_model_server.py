#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_model_server.py —— [进程B：model_server] 跑所有AI相关的东西。

不用FastAPI/uvicorn了，纯UDP服务(见model_server_udp.py)，跟flight进程
(run_flight.py)完全独立，不涉及MAVSDK/飞控，也不需要装mavsdk。
这个进程崩了不会影响飞机的安全控制。

启动的东西：
    - vlm_engine(Qwen2VL) 预加载
    - voice_to_sd.py 的 Whisper + 翻译 后台常驻加载(不参与VLM/SD互斥)
    - 真实SD pipeline(real_sd_adapter.py包装的voice_to_sd LCM pipeline)，
      跟VLM互斥，谁用谁通过 model_memory_lock 切换
    - UDP服务，监听 config.MODEL_SERVER_UDP_PORT (默认9200)，只接受本机flight进程的请求

支持的cmd(见model_server_udp.py/model_logic.py)：
    vlm_chat / vlm_describe / vlm_flight_command / sd_generate /
    voice_flight_command / voice_gen_image / reload_flight_prompt / health
"""
import model_logic
import model_server_udp


def main():
    print("=" * 70)
    print("模型服务进程启动中 —— VLM/SD/Whisper/翻译都在这个进程里")
    print("=" * 70)
    model_logic.startup()
    try:
        model_server_udp.serve()  # 阻塞
    except KeyboardInterrupt:
        print("\n[run_model_server] 收到退出信号，释放模型 ...")
        model_logic.shutdown()
        print("[run_model_server] 退出")


if __name__ == "__main__":
    main()
