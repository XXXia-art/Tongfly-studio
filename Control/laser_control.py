# -*- coding: utf-8 -*-
"""
laser_control.py —— [flight进程侧] 封装激光模组的开/关，用gpiod直接操作GPIO，
不走命令行调用(比如subprocess跑raspi-gpio这种)，延迟更低也更稳。

[安全设计要点]
    1. 请求(request)这根GPIO线的那一刻，就把默认值设成"关"——不依赖后面
       第一次调用turn_off()才关掉。这样"进程接管这根引脚"和"第一次明确
       调用关闭"之间不存在激光状态不确定的窗口期。
    2. 进程退出时(不管是正常退出还是收到SIGINT/SIGTERM)，用atexit注册
       一个兜底关灯动作。[注] atexit在进程被SIGKILL强杀时不会执行——
       这是纯软件方案的天花板，如果需要覆盖"进程被强杀"这种极端情况，
       需要额外的硬件看门狗(比如接一个物理定时继电器)，不是这层代码
       能解决的问题，这里如实说明，不过度承诺。
    3. 对外只暴露turn_on()/turn_off()/is_on()/release()这几个函数，
       调用方(flight_executor.py)不需要关心具体是gpiod哪个版本的API、
       高电平触发还是低电平触发这些细节。

[依赖] 这份代码用的是gpiod 1.x系列的Python绑定API(Chip/get_line/request/
set_value这套)，是目前树莓派上最常见的版本。如果你的板子装的是gpiod 2.x
(API完全不同，改用request_lines()这一套)，这个模块需要相应改写，不是
简单的参数调整——建议先用下面这行确认版本：
    python3 -c "import gpiod; print(gpiod.__version__ if hasattr(gpiod,'__version__') else '未知，看能不能import Chip类')"
"""
import atexit
import threading

import gpiod

import config

_lock = threading.Lock()
_chip = None
_line = None
_current_state_on = False
_released = False


def _ensure_line():
    """懒加载：第一次真正要开关灯时才去请求GPIO线，不在import这个模块的
    瞬间就去碰硬件——避免"只是import了这个模块做别的事，结果意外抢占了
    这根GPIO线"这种情况。"""
    global _chip, _line
    if _line is not None:
        return
    _chip = gpiod.Chip(config.LASER_GPIO_CHIP)
    _line = _chip.get_line(config.LASER_GPIO_LINE)
    # [安全] 请求这根线的同时，直接把默认值设成"关"对应的电平——不管是
    # 高电平触发还是低电平触发，这一步保证"请求成功"和"确认是关的"是
    # 同一个原子操作，中间没有窗口期。
    off_value = 0 if config.LASER_ACTIVE_HIGH else 1
    _line.request(
        consumer="laser_control",
        type=gpiod.LINE_REQ_DIR_OUT,
        default_vals=[off_value],
    )
    print(f"[laser_control] 已接管GPIO {config.LASER_GPIO_CHIP}:{config.LASER_GPIO_LINE}"
          f"({'高电平触发' if config.LASER_ACTIVE_HIGH else '低电平触发'})，初始状态=关")


def turn_on():
    global _current_state_on
    with _lock:
        if _released:
            print("[laser_control][警告] GPIO已释放，忽略开灯请求")
            return
        _ensure_line()
        _line.set_value(1 if config.LASER_ACTIVE_HIGH else 0)
        _current_state_on = True


def turn_off():
    global _current_state_on
    with _lock:
        if _released:
            return
        _ensure_line()
        _line.set_value(0 if config.LASER_ACTIVE_HIGH else 1)
        _current_state_on = False


def is_on():
    return _current_state_on


def release():
    """进程退出/不再需要控制激光时调用：先确保关灯，再释放GPIO占用。
    [注] 这个函数被设计成可以安全重复调用(比如atexit兜底 + 主动调用
    两边都触发，不会因为重复release()而报错)。"""
    global _chip, _line, _current_state_on, _released
    with _lock:
        if _line is not None:
            try:
                _line.set_value(0 if config.LASER_ACTIVE_HIGH else 1)
            except Exception as e:
                print(f"[laser_control][警告] 释放前关灯失败: {e}")
            _current_state_on = False
            try:
                _line.release()
            except Exception:
                pass
            _line = None
        if _chip is not None:
            try:
                _chip.close()
            except Exception:
                pass
            _chip = None
        _released = True


# [安全兜底] 注册在进程正常退出/收到SIGINT等能被Python捕获处理的信号时
# 自动关灯——这是最后一道防线，防止代码某处忘了调turn_off()导致激光
# 跟着进程一起"卡死在亮着"的状态。SIGKILL强杀不会触发这个，见文件顶部说明。
atexit.register(release)
