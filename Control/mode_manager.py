# -*- coding: utf-8 -*-
"""
mode_manager.py —— 模式仲裁层。

[安全铁律] 四个模式互斥，任意时刻只有一个模式的指令能真正送到飞控执行器：
    IDLE            空闲，不接受任何飞行指令，只能被切走
    UPLINK_VELOCITY 上位机UDP速度指令模式
    VOICE_VLM       语音/VLM意图解析飞行模式
    SCREEN_DRAW     串口屏画笔路径模式

切换只能通过 request_switch() 显式发生（对应上位机发来的 {"cmd":"switch_mode"...}）。
任何模式内部的代码都不能"自己切自己"，杜绝抢占。
每次真正执行前都要用 is_active(mode_name) 二次确认自己还是当前模式，
因为在你异步处理指令的过程中，上位机完全可能已经切走了模式。
"""
import threading
import time

IDLE = "IDLE"
UPLINK_VELOCITY = "UPLINK_VELOCITY"
VOICE_VLM = "VOICE_VLM"
SCREEN_DRAW = "SCREEN_DRAW"

ALL_MODES = {IDLE, UPLINK_VELOCITY, VOICE_VLM, SCREEN_DRAW}


class ModeManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._current = IDLE
        self._last_switch_time = time.time()

    def request_switch(self, new_mode: str, source: str = "unknown") -> bool:
        if new_mode not in ALL_MODES:
            print(f"[ModeManager] 拒绝切换：未知模式 '{new_mode}' (来源: {source})")
            return False
        with self._lock:
            old = self._current
            self._current = new_mode
            self._last_switch_time = time.time()
        print(f"[ModeManager] 模式切换: {old} -> {new_mode} (来源: {source})")
        return True

    def is_active(self, mode_name: str) -> bool:
        with self._lock:
            return self._current == mode_name

    def current(self) -> str:
        with self._lock:
            return self._current

    def force_idle(self, reason: str = ""):
        """[安全] 任何看门狗/异常检测都可以直接调这个，把模式打回IDLE，不需要走仲裁流程。"""
        with self._lock:
            old = self._current
            self._current = IDLE
        print(f"[ModeManager][强制IDLE] {old} -> IDLE  原因: {reason}")


# 全局单例：整个进程只应该有一份模式状态
mode_manager = ModeManager()
