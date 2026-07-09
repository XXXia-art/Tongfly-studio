#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_flight.py —— [进程A：flight] 只跑飞行控制相关的东西。

不import vlm_engine/sd_engine/rknnlite/voice_to_sd这些AI依赖，也不需要装它们——
这个进程只需要 mavsdk + numpy 就能跑(跟model_server之间也是纯UDP，不需要requests/HTTP)。

跟model_server进程(run_model_server.py)完全隔离：就算那边OOM/崩溃，
这个进程的看门狗/降落逻辑不受任何影响，最多是"语音/VLM/生图这几个功能暂时用不了"，
飞机的安全始终由这个进程自己兜底。

[运行前提醒]
    - mavlink_bridge.py 已经在跑，且带Offboard转发那一路
    - QGC参数 COM_RC_OVERRIDE 已勾选offboard覆盖选项
    - 遥控器已开机、对频，随时可以拨模式开关接管
    - 首次联调强烈建议拆桨或固定飞机
    - 如果要用语音/VLM/生图功能，记得另外开一个终端跑 run_model_server.py
"""
import threading
import time

import config


def _start_flight_executor():
    from flight_executor import flight_executor
    print("[run_flight] 启动飞行执行器 ...")
    flight_executor.run_forever()  # 阻塞，内部自建事件循环


def _start_uplink_udp():
    from uplink_udp import start_uplink_listener
    start_uplink_listener()  # 阻塞


def _start_screen_draw():
    from screen_draw import start_screen_listener
    start_screen_listener()  # 阻塞


def _check_model_server():
    """启动时探测一下model_server在不在，不在也不阻塞飞行，只是提醒一声。"""
    import model_client
    resp = model_client.health()
    if "error" in resp:
        print(f"[run_flight][提示] model_server目前不可达({resp['error']})，"
              f"语音/VLM/生图功能暂时用不了，但不影响飞行控制。"
              f"如需这些功能，请另开终端运行 run_model_server.py")
    else:
        print(f"[run_flight] model_server状态: {resp}")


def main():
    print("=" * 70)
    print("飞行控制进程启动中 —— 请确认已完成安全检查清单(见本文件顶部注释)")
    print("=" * 70)
    input("确认安全检查已完成，按回车键继续启动 ...")

    _check_model_server()

    flight_thread = threading.Thread(target=_start_flight_executor, daemon=True, name="flight-executor")
    threads = [
        flight_thread,
        threading.Thread(target=_start_uplink_udp, daemon=True, name="uplink-udp"),
        threading.Thread(target=_start_screen_draw, daemon=True, name="screen-draw-tcp"),
    ]
    for t in threads:
        t.start()
        time.sleep(0.5)

    print(f"\n[run_flight] 已启动。mode UDP端口: {config.UPLINK_UDP_PORT}  "
          f"content UDP端口: {config.CONTENT_UDP_PORT}  output UDP端口: {config.OUTPUT_UDP_PORT}  "
          f"画笔TCP端口: {config.SCREEN_TCP_PORT}")
    print("[run_flight] 当前模式: IDLE，上位机可发 switch_mode 切换")
    print("[run_flight] 按 Ctrl+C 退出（会尝试触发降落，更推荐用遥控器接管后手动处理）\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[run_flight] 收到退出信号，正在请求降落并等待飞控线程收尾 ...")
        try:
            from flight_executor import flight_executor
            flight_executor.request_land()
        except Exception as e:
            print(f"[run_flight][警告] 请求降落失败: {e}")

        # 不再固定等3秒就退出。flight_executor.run_forever()会在降落/清理完成后返回；
        # 主线程必须等它完成，否则daemon线程会被进程退出直接切掉。
        warn_interval = 5.0
        last_warn = 0.0
        while flight_thread.is_alive():
            now = time.time()
            if now - last_warn >= warn_interval:
                print("[run_flight] 正在等待飞控降落/清理完成，请勿关闭进程；"
                      "如情况异常，请用遥控器接管。")
                last_warn = now
            try:
                flight_thread.join(timeout=1.0)
            except KeyboardInterrupt:
                print("\n[run_flight][警告] 再次收到Ctrl+C。仍建议等待降落完成；"
                      "紧急情况请优先遥控器接管。")

        # [安全] 主动关一次激光，跟laser_control.py里的atexit兜底形成双保险——
        # 不依赖atexit单独兜底(atexit在正常退出路径下当然会触发，但这里
        # 主动调一次可以更早、更明确地确保激光关掉，不用等到解释器真正
        # 退出那一刻)。laser_control在没有实际开过灯的情况下调release()
        # 也是安全的(内部有_released判重复调用的保护)。
        try:
            import laser_control
            laser_control.release()
        except Exception as e:
            print(f"[run_flight][警告] 关闭激光失败: {e}")

        print("[run_flight] 退出")


if __name__ == "__main__":
    main()