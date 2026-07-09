#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_all.py —— 一个命令，把 model_server + flight 两个进程都拉起来，
所有打印信息汇总显示在【这一个终端】里，不用再开两个窗口切换看。

[重要] 底层依然是两个独立的操作系统进程(用subprocess拉起来的)，
不是又合并回单进程了——model_server那边该崩还是照样崩，崩了不会影响
flight进程的飞控安全逻辑，只是现在你不用自己开两个终端去分别盯着看。

[输出规则]
    - model_server的每一行输出，前面统一加 [model_server] 前缀，单独开一个线程
      不断读它的stdout往外转发
    - flight进程的输出【不重定向】，直接连到这个终端本身——因为它启动时有一个
      input()安全确认("确认安全检查已完成，按回车键继续启动")，必须让你能
      在终端里正常看到提示、正常按回车，如果重定向了stdin，这个确认就没法交互了。
      所以flight进程的日志跟[model_server]的日志会交替出现在同一个终端里，
      flight自己的日志已经有[FlightExecutor]/[uplink_udp]这些前缀，不难区分。

[退出] Ctrl+C：会先让flight进程走它自己的降落流程(它自己有KeyboardInterrupt处理)，
等它退出后再关model_server。
"""
import subprocess
import sys
import threading
import time


def _stream_output(proc, prefix):
    """不断读子进程的stdout，加前缀后转发到这个终端。"""
    try:
        for line in iter(proc.stdout.readline, b""):
            text = line.decode("utf-8", errors="replace").rstrip()
            print(f"[{prefix}] {text}")
    except Exception as e:
        print(f"[run_all][{prefix}读取输出异常] {e}")


def main():
    print("=" * 70)
    print("一键启动：model_server + flight 两个进程，输出统一汇总在这个终端里")
    print("=" * 70)

    print("[run_all] 启动 model_server 进程 ...")
    model_proc = subprocess.Popen(
        [sys.executable, "-u", "run_model_server.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    model_thread = threading.Thread(
        target=_stream_output, args=(model_proc, "model_server"), daemon=True
    )
    model_thread.start()

    # 给model_server一点点时间先把日志打出来，不是必须的，纯粹让终端显示顺序更好看
    time.sleep(2)

    print("[run_all] 启动 flight 进程 ...(接下来的安全确认提示直接在这个终端里按回车)")
    # 注意：flight进程的stdout/stdin不重定向，直接沿用这个终端，
    # 这样它的input()安全确认才能正常交互
    flight_proc = subprocess.Popen([sys.executable, "-u", "run_flight.py"])

    try:
        flight_proc.wait()
        print("[run_all] flight进程已退出")
    except KeyboardInterrupt:
        print("\n[run_all] 收到Ctrl+C，等待flight进程自行处理降落流程 ...")
        try:
            flight_proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            print("[run_all] flight进程超时未退出，强制终止")
            flight_proc.terminate()
            try:
                flight_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                flight_proc.kill()

    print("[run_all] 关闭 model_server 进程 ...")
    model_proc.terminate()
    try:
        model_proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        model_proc.kill()

    print("[run_all] 全部已退出")


if __name__ == "__main__":
    main()
