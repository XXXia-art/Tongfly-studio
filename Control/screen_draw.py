# -*- coding: utf-8 -*-
"""
screen_draw.py —— 复用你debug脚本里验证过的二进制帧解析 + RDP简化 + 像素转NED逻辑，
区别是：不再只打印，而是在当前模式==SCREEN_DRAW时，把简化后的关键点序列
转换成"相对当前位置院的NED偏移"，交给 flight_executor.fly_path_positions() 飞过去。

[安全] 只有 mode_manager 当前模式是 SCREEN_DRAW 时，笔画才会被真正执行；
       否则只解析打印，不会移动飞机——避免"忘记切模式，画着玩结果飞机动了"。
"""
import asyncio
import re
import socket
import struct

import numpy as np

import config
import mode_manager as mm
from mode_manager import mode_manager
from flight_executor import flight_executor

pattern_dmu = re.compile(rb'([DMU]),x:(.{4}),y:(.{4})\r\n', re.DOTALL)
pattern_sl = re.compile(rb'([SL]),\r\n')

_current_stroke = []
_stroke_count = 0
_last_stroke_end_pixel = None
_last_stroke_end_ned = None


def _pixel_to_ned(x, y):
    global _last_stroke_end_pixel, _last_stroke_end_ned
    if _last_stroke_end_pixel is None:
        norm_x = (x / config.SCREEN_WIDTH) - 0.5
        norm_y = (y / config.SCREEN_HEIGHT) - 0.5
        east = norm_x * config.FLIGHT_SPAN_X
        north = -norm_y * config.FLIGHT_SPAN_Y
        return north, east
    dx = x - _last_stroke_end_pixel[0]
    dy = y - _last_stroke_end_pixel[1]
    d_east = dx * (config.FLIGHT_SPAN_X / config.SCREEN_WIDTH)
    d_north = -dy * (config.FLIGHT_SPAN_Y / config.SCREEN_HEIGHT)
    base_n, base_e = _last_stroke_end_ned
    return base_n + d_north, base_e + d_east


def _rdp(points, epsilon=config.RDP_EPSILON):
    if len(points) < 3:
        return points

    def perp_dist(pt, start, end):
        p, s, e = map(np.array, (pt, start, end))
        if (s == e).all():
            return np.linalg.norm(p - s)
        se = e - s
        sp = p - s
        cross_z = se[0] * sp[1] - se[1] * sp[0]
        return abs(cross_z) / np.linalg.norm(se)

    dmax, idx = 0.0, 0
    for i in range(1, len(points) - 1):
        d = perp_dist(points[i], points[0], points[-1])
        if d > dmax:
            dmax, idx = d, i
    if dmax > epsilon:
        left = _rdp(points[:idx + 1], epsilon)
        right = _rdp(points[idx:], epsilon)
        return left[:-1] + right
    return [points[0], points[-1]]


def _process_stroke(stroke_points):
    global _stroke_count, _last_stroke_end_pixel, _last_stroke_end_ned
    _stroke_count += 1
    print(f"\n[screen_draw] 第{_stroke_count}笔 原始点数={len(stroke_points)}")

    simplified = _rdp(stroke_points)
    print(f"[screen_draw] RDP简化后关键点: {simplified}")

    ned_points = []
    for x, y in simplified:
        n, e = _pixel_to_ned(x, y)
        ned_points.append((n, e))
        print(f"  像素({x},{y}) -> NED(north={n:.3f}, east={e:.3f})")

    # [修复] prev必须继承"上一笔结束时的位置"，不能每次调用都从None重新开始——
    # 原来的写法是prev=None起步，导致每一笔的第一个点(不管是笔画内部的还是
    # 跟上一笔之间的"抬笔跳转")永远不会被转换成一条飞行指令：飞机会直接从
    # 它当前实际所在的位置(也就是上一笔的终点)开始画这一笔的相对形状，
    # 导致图形画错位置，而且偏差会随笔画数量累积。
    # is_jump_from_previous_stroke记录这一笔是不是"接在上一笔后面"(不是整个
    # 会话的第一笔)——只有这种情况才需要"抬笔跳转"，第一笔本身没有上一笔
    # 可跳，直接按普通移动飞到起点就行。
    is_jump_from_previous_stroke = _last_stroke_end_ned is not None
    prev = _last_stroke_end_ned if _last_stroke_end_ned is not None else (0.0, 0.0)
    ne_offsets = []
    for n, e in ned_points:
        ne_offsets.append((n - prev[0], e - prev[1]))
        prev = (n, e)

    _last_stroke_end_pixel = stroke_points[-1]
    _last_stroke_end_ned = ned_points[-1]

    if not mode_manager.is_active(mm.SCREEN_DRAW):
        print("[screen_draw] 当前模式不是SCREEN_DRAW，仅解析不执行飞行")
        return

    if not ne_offsets or flight_executor.loop is None:
        return

    print(f"[screen_draw] 当前模式=SCREEN_DRAW，下发路径执行 ({len(ne_offsets)}段)")

    async def _run():
        if is_jump_from_previous_stroke:
            # [改动] 跟上一笔之间的"抬笔跳转"：现在改成同一高度直接水平
            # 移动过去，不再垂直抬升——画线这件事由激光负责(见
            # flight_executor.fly_path_positions()里的开关灯逻辑)，
            # 这段跳转期间激光是关的，飞行轨迹本身不会画出任何东西，
            # 之前"抬高避免拖出连接线"这个顾虑已经不成立。
            # ne_offsets[0]就是这段跳转的偏移量，剩下的才是这一笔真正要画的线。
            jump_dn, jump_de = ne_offsets[0]
            draw_offsets = ne_offsets[1:]
            ok = await flight_executor.fly_pen_up_jump(
                mm.SCREEN_DRAW, jump_dn, jump_de
            )
            if not ok:
                print("[screen_draw] 抬笔跳转失败/被中止，跳过这一笔剩余的绘制")
                return
            if draw_offsets:
                await flight_executor.fly_path_positions(mm.SCREEN_DRAW, draw_offsets)
        else:
            # 整个会话的第一笔，没有"上一笔"可跳，直接按普通移动飞完这一笔
            await flight_executor.fly_path_positions(mm.SCREEN_DRAW, ne_offsets)

    fut = asyncio.run_coroutine_threadsafe(_run(), flight_executor.loop)
    try:
        fut.result(timeout=60)
    except Exception as e:
        print(f"[screen_draw][路径执行异常] {e}")


def _handle_frame(tag, x=None, y=None):
    global _current_stroke
    if tag == 'D':
        _current_stroke = [(x, y)]
        print(f"[screen_draw][D] 笔画开始 起点=({x},{y})")
    elif tag == 'M':
        _current_stroke.append((x, y))
    elif tag == 'U':
        _current_stroke.append((x, y))
        print(f"[screen_draw][U] 笔画结束，共{len(_current_stroke)}个采样点")
        _process_stroke(list(_current_stroke))
        _current_stroke = []
    elif tag == 'S':
        print("[screen_draw][S] 收到起飞确认信号（本模块不处理起降，交给flight_executor主流程）")
    elif tag == 'L':
        print("[screen_draw][L] 收到降落请求信号")
        flight_executor.request_land()


def _try_parse_buffer(buf: bytearray):
    while True:
        if len(buf) == 0:
            return buf
        m = pattern_dmu.match(bytes(buf))
        if m:
            tag = m.group(1).decode("ascii")
            x = struct.unpack('<i', m.group(2))[0]
            y = struct.unpack('<i', m.group(3))[0]
            _handle_frame(tag, x, y)
            buf = buf[m.end():]
            continue
        m = pattern_sl.match(bytes(buf))
        if m:
            _handle_frame(m.group(1).decode("ascii"))
            buf = buf[m.end():]
            continue
        if len(buf) > 64:
            print(f"[screen_draw][警告] 无法解析且buffer堆积{len(buf)}字节，丢弃1字节重新同步")
            buf = buf[1:]
            continue
        return buf


def start_screen_listener():
    """在独立线程里调用：常驻TCP监听，跟你原debug脚本一样，接受单个树莓派连接。"""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((config.SCREEN_TCP_HOST, config.SCREEN_TCP_PORT))
    srv.listen(1)
    print(f"[screen_draw] 等待串口屏/树莓派连接 {config.SCREEN_TCP_HOST}:{config.SCREEN_TCP_PORT} ...")
    while True:
        conn, addr = srv.accept()
        print(f"[screen_draw] 已连接: {addr}")
        buf = bytearray()
        try:
            while True:
                data = conn.recv(1024)
                if not data:
                    print("[screen_draw] 连接断开，等待下一次连接")
                    break
                buf.extend(data)
                buf = _try_parse_buffer(buf)
        except Exception as e:
            print(f"[screen_draw][连接异常] {e}")