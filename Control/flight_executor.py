# -*- coding: utf-8 -*-
"""
flight_executor.py —— 全项目里唯一允许往飞控发setpoint的地方。

改编自你已经实测过的 test_04(位置控制) / test_05(速度控制)，安全机制原样保留：
    - offboard_watchdog: 掉出OFFBOARD模式立刻abort，交还遥控器
    - armed_watchdog:    意外上锁立刻abort
    - 分级起降 + 到达确认
    - 降落优先用测距传感器判断贴地，超时兜底飞控自身Land()

[架构要点] 其它模块(uplink_udp / voice_vlm / screen_draw)不直接跟MAVSDK打交道，
只调用这里暴露的 set_velocity_body() / fly_path_positions() 等方法。
这些方法内部都会先检查 mode_manager 当前模式是不是调用方自己，不是就直接拒绝执行——
这是防止"模式已经被切走了，但某个后台线程还在傻乎乎地继续发指令"的最后一道闸门。
"""
import asyncio
import threading
import time

from mavsdk import System
from mavsdk.offboard import PositionNedYaw, VelocityBodyYawspeed, OffboardError

import config
from mode_manager import mode_manager, IDLE
import laser_control


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


class FlightExecutor:
    def __init__(self):
        self.drone = System()
        self.loop = None
        self.abort_event = None
        self._reset_requested = threading.Event()
        self._arming_started = False
        self._runner_active = False

        # setpoint发送使用的全局状态，由 _setpoint_sender 唯一读取
        self._setpoint_mode = "position"   # "position" | "velocity_body"
        self.current_n = 0.0
        self.current_e = 0.0
        self.current_d = 0.0
        self.yaw_lock = 0.0
        self.vel_forward = 0.0
        self.vel_right = 0.0
        self.vel_down = 0.0
        self.vel_yawspeed = 0.0

        self._state_lock = threading.Lock()
        self._last_velocity_cmd_time = 0.0

        self.origin_n = self.origin_e = self.origin_d = 0.0
        self.armed_and_flying = False

        self._sender_task = None
        self._watchdog_task = None
        self._armed_watchdog_task = None
        self._idle_watcher_task = None

        # [安全] 记录上一次观察到的mode_manager状态，用来检测"刚刚切进IDLE"
        # 这个瞬间——只有瞬间发生时才需要动作，不是每次轮询都做。
        self._last_seen_manager_mode = None

        # [安全] abort_reason区分"为什么abort"，决定收尾时能不能碰电机：
        #   "offboard_lost" -> 飞行员主动拨出OFFBOARD接管，飞机还在空中被人工控制，
        #                       绝对不能再发disarm()，那是在人控制飞行时凭空断电
        #   "disarmed"      -> 飞控自己已经处于disarmed状态(电机已经停了)，
        #                       这时候再调disarm()只是幂等确认，无害
        #   None            -> 没有意外abort，走到这里说明是正常的land请求
        self.abort_reason = None

        # [安全] land_requested跟abort_event彻底分开，不复用同一个标志：
        # abort_event只代表"意外情况，立刻停止自动控制"(看门狗触发)；
        # land_requested只代表"请求正常降落"。如果两者共用一个event，
        # _climb_to()/_wait_until_reached()里"检测到abort就return False"
        # 这行判断会在request_land()一发生就立刻为True，导致降落时的
        # 分级下降循环第一次检查就直接退出，飞机从来没有真的被指挥下降过。
        self.land_requested = None  # 运行时(run_forever)才创建真正的asyncio.Event

        # [新增] 起飞不再是"一进OFFBOARD就自动解锁爬升"，改成必须等mode=8
        # 显式起飞指令。进入OFFBOARD后会停在一个等待点，只有这个事件被
        # set()才会真正往下走到arm()+爬升。运行时(run_forever)才创建真正
        # 的asyncio.Event，跟abort_event/land_requested的生命周期管理一致。
        self.takeoff_requested = None

        # [安全] 人工接管(offboard_lost)之后的"只读监听"状态，供request_reset()
        # 做实时校验用，不能仅凭armed_and_flying/_arming_started标志已经复位
        # 就相信飞机已经落地——那两个标志只是软件内部记账，跟飞机真实物理状态
        # 是两回事。这里记录的是测距传感器+armed遥测的最新实况。
        # _in_post_handover_monitor为True的整个期间，request_reset()必须拿到
        # 高度低于阈值、且armed==False的实时读数才会放行，标志复位只是让
        # 判断逻辑"能够被走到"，不是判断本身。
        self._in_post_handover_monitor = False
        self._post_handover_lock = threading.Lock()
        self._post_handover_height_m = None
        self._post_handover_armed = None
        self._post_handover_updated_at = 0.0

    # ---------------------------------------------------------------
    # 生命周期：由 main.py 在独立线程里跑一个asyncio事件循环来驱动这些协程
    # ---------------------------------------------------------------

    def run_forever(self):
        """在专属线程里调用：起飞前的准备 + 常驻事件循环。"""
        if self._runner_active:
            print("[FlightExecutor] run_forever已在运行，忽略重复启动")
            return
        self._runner_active = True
        try:
            while True:
                try:
                    self._reset_requested.clear()
                    self.drone = System()
                    self._reset_control_state()

                    self.loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(self.loop)
                    self.abort_event = asyncio.Event()
                    self.land_requested = asyncio.Event()
                    self.takeoff_requested = asyncio.Event()
                    self.abort_reason = None
                    self.loop.run_until_complete(self._main_async())
                finally:
                    if self.loop is not None:
                        self.loop.close()
                        self.loop = None

                if self._reset_requested.is_set():
                    print("[FlightExecutor] 飞控执行器已清理，准备重新连接飞控 ...")
                    continue
                return
        finally:
            self._runner_active = False

    def _reset_control_state(self):
        with self._state_lock:
            self._setpoint_mode = "position"
            self.current_n = 0.0
            self.current_e = 0.0
            self.current_d = 0.0
            self.yaw_lock = 0.0
            self.vel_forward = 0.0
            self.vel_right = 0.0
            self.vel_down = 0.0
            self.vel_yawspeed = 0.0
            self._last_velocity_cmd_time = 0.0
        self.origin_n = self.origin_e = self.origin_d = 0.0
        self.armed_and_flying = False
        self._arming_started = False
        self._sender_task = None
        self._watchdog_task = None
        self._armed_watchdog_task = None
        self._idle_watcher_task = None
        self._last_seen_manager_mode = None
        self._in_post_handover_monitor = False
        with self._post_handover_lock:
            self._post_handover_height_m = None
            self._post_handover_armed = None
            self._post_handover_updated_at = 0.0

    async def _main_async(self):
        print(f"[FlightExecutor] 连接飞控 {config.DRONE_CONNECTION_ADDRESS} ...")
        await self.drone.connect(system_address=config.DRONE_CONNECTION_ADDRESS)

        async for state in self.drone.core.connection_state():
            if self._reset_requested.is_set():
                await self._cleanup_background_tasks()
                return
            if state.is_connected:
                break
        print("[FlightExecutor] 飞控已连接")

        async for health in self.drone.telemetry.health():
            if self._reset_requested.is_set():
                await self._cleanup_background_tasks()
                return
            if health.is_local_position_ok and health.is_armable:
                break
        print("[FlightExecutor] 本地位置估计就绪 + 自检通过")

        pos = await self._get_position_once()
        self.origin_n, self.origin_e, self.origin_d = pos
        self.current_n, self.current_e, self.current_d = pos

        async for att in self.drone.telemetry.attitude_euler():
            self.yaw_lock = att.yaw_deg
            break
        print(f"[FlightExecutor] 记录起飞原点 N={self.origin_n:.2f} E={self.origin_e:.2f} "
              f"D={self.origin_d:.2f} yaw={self.yaw_lock:.1f}")

        self._sender_task = asyncio.create_task(self._setpoint_sender())
        await asyncio.sleep(1)

        print("[FlightExecutor] 等待遥控器切换到 OFFBOARD 模式 ...")
        async for flight_mode in self.drone.telemetry.flight_mode():
            if self._reset_requested.is_set():
                await self._cleanup_background_tasks()
                return
            if self.land_requested.is_set():
                # [安全] 等飞行员切OFFBOARD这一步可能要等很久，期间如果
                # 收到降落/退出请求(比如run_flight.py的Ctrl+C处理会调
                # request_land())，必须能被这里检测到并干净退出，不然
                # 这个循环会一直卡在等遥测更新，进程永远退不出去。这时候
                # 飞机还没进OFFBOARD、更没解锁，不需要走降落序列。
                print("[FlightExecutor] 等待OFFBOARD期间收到降落/退出请求，直接清理并结束")
                await self._cleanup_background_tasks()
                return
            if str(flight_mode) == "OFFBOARD":
                break
        print("[FlightExecutor] 已进入 OFFBOARD")

        self._watchdog_task = asyncio.create_task(self._offboard_watchdog())

        # [新增] 不再一进OFFBOARD就自动解锁爬升，改成停在这里等mode=8的
        # 显式起飞指令(request_takeoff())。看门狗已经在跑，如果这段等待
        # 期间飞行员就把遥控器拨出了OFFBOARD，一样会被_offboard_watchdog
        # 检测到、设置abort_event——这种情况下走的是跟"起飞后又被接管"
        # 完全同一套abort处理代码(见下面_reset_requested/abort_reason分支)，
        # 不需要额外写一份，只是这时armed_and_flying还是False，_land_sequence
        # /post_handover_monitor那几处判断本来就兼容"还没起飞就abort"这种情况。
        print("[FlightExecutor] 已进入OFFBOARD，等待起飞指令(mode=8) ...")
        self.takeoff_requested.clear()
        while (not self.takeoff_requested.is_set()
               and not self.abort_event.is_set()
               and not self._reset_requested.is_set()
               and not self.land_requested.is_set()):
            await asyncio.sleep(0.2)

        if self._reset_requested.is_set():
            print("[FlightExecutor] 等待起飞指令期间收到地面重置请求，清理并重新初始化")
            await self._cleanup_background_tasks()
            return

        if self.land_requested.is_set():
            # [安全] 起飞前(还没解锁过)收到降落/退出请求(比如Ctrl+C退出时
            # run_flight.py会调request_land())——这时候飞机压根没飞起来，
            # 不需要走_land_sequence()那套下降+测距确认+disarm流程(那是
            # 给"真的在天上"准备的)，直接清理后台任务、结束这一轮_main_async
            # 即可，不会导致进程卡死退不出去。
            print("[FlightExecutor] 等待起飞指令期间收到降落/退出请求，"
                  "尚未解锁起飞，直接清理并结束")
            await self._cleanup_background_tasks()
            return

        if self.abort_event.is_set():
            # 还没起飞就被看门狗abort了(比如飞行员在等待期间就拨出了OFFBOARD)，
            # 走跟"起飞后abort"完全一样的收尾分支——见下面armed_and_flying=True
            # 之后那段代码，这里直接调用同一段逻辑，不重复写。
            await self._handle_flight_abort()
            return

        print("[FlightExecutor] 收到起飞指令，开始解锁 ...")
        self._arming_started = True
        try:
            await self.drone.action.arm()
        except Exception as e:
            # [安全] 之前这里没有try/except——如果飞控拒绝解锁(比如预解锁
            # 检查失败、GPS质量突然下降)，异常会一路传出run_forever()，
            # 直接把flight-executor这个线程崩掉，而且_arming_started会
            # 永久卡在True：request_reset()第一道闸门就检查这个标志，
            # 会永久拒绝重置；就算is_runner_active()因为线程崩溃变回
            # False，_safe_reset_flight()的调用顺序是"先request_reset()
            # 通过了、才起线程重新调run_forever()"，永远走不到"重新调
            # run_forever()"这一步去真正清掉_arming_started——等于卡死，
            # 只能重启整个进程。现在改成：解锁失败时清理标志、清理后台
            # 任务，正常结束这一轮_main_async，回到run_forever()的外层
            # 循环(不是reset_requested触发的continue，是直接return到
            # run_forever()，那边finally会把_runner_active设回False，
            # 之后可以通过mode=0/重置流程正常重新拉起，不会导致线程崩溃
            # 或者永久卡死)。
            print(f"[FlightExecutor][严重] 解锁失败: {e}，取消本次起飞")
            self._arming_started = False
            await self._cleanup_background_tasks()
            return
        await asyncio.sleep(2)
        print("[FlightExecutor] 已解锁")

        self._armed_watchdog_task = asyncio.create_task(self._armed_watchdog())

        target_d = self.origin_d - min(config.TAKEOFF_ALTITUDE, config.MAX_ALTITUDE)
        print(f"[FlightExecutor] 起飞到 {config.TAKEOFF_ALTITUDE}m ...")
        climb_ok = await self._climb_to(self.origin_n, self.origin_e, target_d,
                                         step_interval=config.TAKEOFF_STEP_INTERVAL, label="起飞")

        # [修复] 之前这里直接丢弃了_climb_to()的返回值，不管爬升有没有真的
        # 确认到位/中途有没有被abort，都无条件打印"起飞完成"——这跟
        # fly_offset_with_lift()里"每次调_climb_to()都检查ok"的处理方式
        # 不一致。这里补上检查，让日志能准确反映实际发生的情况，避免
        # "abort已经发生了，却先打印一句起飞完成"这种误导性的日志顺序。
        if self.abort_event.is_set() or self.land_requested.is_set():
            # abort/降落请求发生在爬升过程中(_climb_to内部检测到就会提前
            # 返回False)——不打印"起飞完成"，直接往下走，armed_and_flying
            # 还是要设成True(因为解锁确实已经发生了，_handle_flight_abort()
            # 需要知道飞机现在是"已解锁"状态才能正确判断收尾方式)，紧接着
            # 下面的主循环会立刻发现abort_event/land_requested已经被设置，
            # 转入对应的收尾分支处理，这里不重复处理。
            print("[FlightExecutor] 起飞爬升过程中检测到abort/降落请求，转入相应收尾流程")
        elif not climb_ok:
            # 纯粹是REACH_TIMEOUT超时、没有真正abort——setpoint仍在按目标
            # 高度持续发送(_setpoint_sender不受这个确认结果影响)，飞机大概率
            # 还是会继续朝目标高度飞，只是没能在超时时间内确认到达。继续
            # 往下走进入监听状态，但用警告日志如实说明，不能假装是正常完成。
            print(f"[FlightExecutor][警告] 起飞爬升超过{config.REACH_TIMEOUT}秒"
                  f"未确认到达目标高度，但setpoint仍在持续发送，继续进入监听状态")
        else:
            print("[FlightExecutor] 起飞完成，进入常驻监听状态，等待各模式下发指令 ...")

        self.armed_and_flying = True

        self._idle_watcher_task = asyncio.create_task(self._idle_hold_watcher())

        # 常驻：一直跑到abort(意外情况)或land_requested(正常降落请求)
        while not self.abort_event.is_set() and not self.land_requested.is_set():
            await asyncio.sleep(0.2)

        if self._reset_requested.is_set():
            print("[FlightExecutor] 收到地面重置请求，清理当前连接并重新初始化")
            await self._cleanup_background_tasks()
            return

        await self._handle_flight_abort()

    async def _handle_flight_abort(self):
        """abort_event被设置后的收尾处理，覆盖两种触发场景：
            1. 起飞前(还在等待mode=8起飞指令期间)就被看门狗abort——这时候
               armed_and_flying必然是False，abort_reason必然是"offboard_lost"
               (armed_watchdog这时候还没启动，不可能是"disarmed")。
            2. 起飞后(正常飞行中)被看门狗abort——armed_and_flying是True，
               abort_reason可能是"offboard_lost"或"disarmed"。
        两种场景收尾逻辑基本一致，抽成这一个方法两处调用，不重复代码。
        [安全] 根据abort原因决定收尾方式，绝不能一律执行降落/上锁：
            - offboard_lost: 飞行员已经用遥控器接管(或者压根还没起飞就退出了
              OFFBOARD)，这里唯一该做的是"停止我们自己的自动控制"，不发任何
              降落/上锁指令，把飞机完全交还给人。
            - 其它情况(disarmed / land_requested)：走完整降落序列。
        """
        if self.abort_reason == "offboard_lost":
            print("[FlightExecutor] 检测到飞行员已接管(退出OFFBOARD)，"
                  "停止自动控制，不执行降落/上锁，控制权完全交还遥控器")
            self.armed_and_flying = False
            self._arming_started = False
            await self._cleanup_background_tasks()
            # [安全] 只有真正已经起飞过(_in_post_handover_monitor在
            # _offboard_watchdog里只在armed_and_flying为True时才会被置位)，
            # 才需要走"只读监听确认物理落地状态"这一套——起飞前(还在等待
            # mode=8指令期间)就退出OFFBOARD，飞机本来就还在地面没解锁过，
            # 不存在"要不要相信它已经落地"这个问题，直接回到待机状态即可，
            # 不用为了这种情况也硬跑一遍传感器监听。
            if self._in_post_handover_monitor:
                print("[FlightExecutor] 进入人工接管后的只读监听状态："
                      "持续记录测距/armed遥测，等待地面确认reset ...")
                try:
                    await self._post_handover_monitor()
                    # 只有正常路径(地面发起reset、监听正常结束)才清掉这个门槛，
                    # 交给下一轮run_forever重新走_reset_control_state()彻底复位。
                    self._in_post_handover_monitor = False
                except Exception as e:
                    # [安全兜底] 监听协程本身如果因为遥测异常崩了，绝不能顺手把
                    # _in_post_handover_monitor清成False——那样request_reset()会
                    # 因为"不在监听状态"直接跳过测距/armed校验，变成无条件放行，
                    # 等于绕开了刚加的安全校验，比修复前更危险。这里刻意保持它
                    # 为True：request_reset()会持续因为"读数缺失/过期"拒绝，
                    # 直到人工重启进程——这是本次异常下唯一诚实的兜底方式。
                    print(f"[FlightExecutor][严重] 人工接管后的遥测监听异常退出: {e}\n"
                          f"[FlightExecutor][严重] 无法再确认飞机是否已落地，"
                          f"request_reset()将持续拒绝，如确认飞机已安全落地，"
                          f"请重启run_flight.py进程")
            else:
                print("[FlightExecutor] 尚未解锁/起飞就检测到退出OFFBOARD，"
                      "直接回到地面待机状态，无需只读监听确认")
            return

        await self._land_sequence()
        self.armed_and_flying = False
        self._arming_started = False
        # [安全] 这里必须也清掉_in_post_handover_monitor：如果_offboard_watchdog
        # 先触发过(打开了这个门槛)，紧接着_armed_watchdog又触发把abort_reason
        # 覆盖成"disarmed"，代码会走到这个分支而不是offboard_lost那条分支，
        # 那条分支里"监听结束后清掉_in_post_handover_monitor"的逻辑就不会被执行——
        # 如果这里不清，这个门槛会永久卡在True，但post_handover_height_m/armed
        # 又因为没启动过监听而永远是初始值None，导致request_reset()以后永远
        # 因为"读数缺失"拒绝，等于重新变成了修复前的那个"卡死只能重启进程"问题，
        # 只是触发路径换成了两个看门狗的竞态，而不是原来的"标志不复位"。
        self._in_post_handover_monitor = False
        with self._post_handover_lock:
            self._post_handover_height_m = None
            self._post_handover_armed = None
            self._post_handover_updated_at = 0.0
        await self._cleanup_background_tasks()

    # ---------------------------------------------------------------
    # 后台任务：setpoint发送 + 双看门狗
    # ---------------------------------------------------------------

    async def _setpoint_sender(self):
        interval = 1.0 / config.SETPOINT_RATE_HZ
        while True:
            try:
                with self._state_lock:
                    mode = self._setpoint_mode
                    if mode == "velocity_body":
                        # [安全] 速度模式下，超时没有新指令就强制清零，不管指令来源是谁
                        # [安全] 用monotonic clock而不是time.time()，避免NTP
                        # 同步/人工调整系统时间导致墙上时钟跳变，让这个超时
                        # 判断失真(比如时间往回跳，算出负数/异常小的差值，
                        # 永远小于超时阈值，导致本该被清零的速度指令一直
                        # 不清零，飞机会在断联情况下继续按最后一条指令飞)。
                        if time.monotonic() - self._last_velocity_cmd_time > config.UPLINK_VELOCITY_TIMEOUT:
                            self.vel_forward = 0.0
                            self.vel_right = 0.0
                            self.vel_down = 0.0
                            self.vel_yawspeed = 0.0
                        forward, right, down, yawspeed = (
                            self.vel_forward, self.vel_right, self.vel_down, self.vel_yawspeed
                        )
                    else:
                        n, e, d, yaw = self.current_n, self.current_e, self.current_d, self.yaw_lock

                if mode == "velocity_body":
                    await self.drone.offboard.set_velocity_body(
                        VelocityBodyYawspeed(forward, right, down, yawspeed)
                    )
                else:
                    await self.drone.offboard.set_position_ned(
                        PositionNedYaw(n, e, d, yaw)
                    )
            except OffboardError as exc:
                print(f"[FlightExecutor][setpoint异常] {exc}")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"[FlightExecutor][setpoint未知异常] {exc}")
            await asyncio.sleep(interval)

    async def _offboard_watchdog(self):
        async for flight_mode in self.drone.telemetry.flight_mode():
            if self.abort_event.is_set() or self.land_requested.is_set():
                return
            if str(flight_mode) != "OFFBOARD":
                print(f"[看门狗] 已退出OFFBOARD(当前:{flight_mode})，中止自动控制，交还遥控器！")
                mode_manager.force_idle("退出OFFBOARD")
                if self.abort_reason is None:
                    self.abort_reason = "offboard_lost"
                    # [安全] 只有已经armed_and_flying(真正起飞过)才需要开启
                    # 只读监听确认——如果还在"等待mode=8起飞指令"这个阶段就
                    # 退出了OFFBOARD，飞机本来就还在地面、根本没解锁过，不存在
                    # "要不要相信它已经落地"这个问题，不需要为这种情况也硬跑
                    # 一遍传感器监听。必须在检测到的这一刻(跟abort_reason同一
                    # 个同步块里)就判断，不能等到_main_async里清理完才设——
                    # 那样存在"标志已经复位但监听门槛还没打开"的窗口期，
                    # request_reset()可能误判成"不在监听状态"从而跳过实时校验。
                    if self.armed_and_flying:
                        self._in_post_handover_monitor = True
                self.abort_event.set()
                return

    async def _armed_watchdog(self):
        async for is_armed in self.drone.telemetry.armed():
            if self.abort_event.is_set() or self.land_requested.is_set():
                return
            if not is_armed:
                print("[看门狗] 检测到已上锁(disarmed)，中止自动控制！")
                mode_manager.force_idle("意外disarm")
                # 电机已经停了，这个原因优先级最高，允许覆盖offboard_lost：
                # disarmed是更明确的"电机已停"状态，收尾时disarm()调用是安全的幂等操作
                self.abort_reason = "disarmed"
                self.abort_event.set()
                return

    async def _idle_hold_watcher(self):
        """[安全] 独立的轻量轮询任务，跟20Hz的_setpoint_sender解耦，专门检测
        "任务正常完成、切回IDLE"这个瞬间：一旦发现，立刻读一次飞控的真实当前
        位置(不能用self.current_n/e/d，那几个变量在velocity_body模式下根本
        不会被更新，是过期数据)，把这个真实坐标锁定成新的悬停目标，切内部
        setpoint模式为位置控制——这样不管切到IDLE之前是在速度模式还是位置
        模式，IDLE状态下飞机都会稳定悬停在切换那一刻的真实位置，不会靠
        "速度=0"被动漂移。

        [安全，关键] 只在"任务正常完成"这条路径上锁定悬停，绝不能在看门狗
        触发force_idle()的紧急场景(人工接管OFFBOARD/意外disarm)下补发任何
        setpoint——那种情况下mode_manager虽然也会变成IDLE，但语义完全不同，
        是"立刻停止一切自动控制"，不是"任务做完了稳稳停着"。这两种IDLE在
        mode_manager这一层看起来完全一样(都只是把状态改成字符串"IDLE")，
        没法从状态本身区分，只能靠abort_event做区分：看门狗调用force_idle()
        总是紧接着调用abort_event.set()(两者之间没有await，几乎是原子的)。
        所以这里在真正提交悬停锁定之前，读取真实位置的前后各检查一次
        abort_event——读之前没设置说明大概率是正常路径；读取过程中有await
        (可能被其它协程插入执行)，读完之后必须再确认一次，堵住"读的时候
        看门狗才触发"这个竞态窗口，避免在紧急abort发生后还补一刀写入
        位置setpoint状态。

        [注] 这只是flight_executor内部的实现细节，不会向uplink_udp/voice_vlm
        这些外部模块暴露"内部又多了一个position模式"这种概念，外部只看到
        mode_manager的IDLE状态，行为上"任务做完了飞机停在原地"就是了。"""
        poll_interval = 0.1  # 10Hz轮询模式变化足够及时，没必要跟20Hz发送同频
        while not self.abort_event.is_set() and not self.land_requested.is_set():
            current_manager_mode = mode_manager.current()
            just_entered_idle = (
                current_manager_mode == IDLE
                and self._last_seen_manager_mode is not None
                and self._last_seen_manager_mode != IDLE
            )
            self._last_seen_manager_mode = current_manager_mode

            # [安全] 读取位置前先确认一次abort_event——如果是看门狗刚触发的
            # force_idle，这里大概率已经能拦住，不用白费一次遥测读取
            if just_entered_idle and self.armed_and_flying and not self.abort_event.is_set():
                try:
                    n, e, d = await self._get_position_once()
                    yaw = None
                    async for att in self.drone.telemetry.attitude_euler():
                        yaw = att.yaw_deg
                        break
                    # [安全] 上面这两次遥测读取都有await，期间abort_event可能
                    # 才被看门狗设置(比如飞行员突然拨出OFFBOARD)——这种情况下
                    # 这次IDLE转变根本不是"任务完成"，是紧急状况，绝不能在
                    # 这里补一刀写入位置setpoint状态，必须重新确认一次才提交。
                    if self.abort_event.is_set():
                        print("[FlightExecutor] 读取位置期间检测到意外abort，"
                              "放弃本次悬停锁定，控制权交还遥控器")
                    else:
                        with self._state_lock:
                            self.current_n, self.current_e, self.current_d = n, e, d
                            if yaw is not None:
                                self.yaw_lock = yaw
                            self._setpoint_mode = "position"
                        print(f"[FlightExecutor] 任务完成切入IDLE，锁定当前实际位置悬停 "
                              f"N={n:.2f} E={e:.2f} D={d:.2f}")
                except Exception as e:
                    print(f"[FlightExecutor][警告] 切入IDLE时读取真实位置失败: {e}，"
                          f"暂时保持原有setpoint状态，不做悬停锁定")

            await asyncio.sleep(poll_interval)

    # ---------------------------------------------------------------
    # 对外接口：各模式只能通过这些方法间接控制飞机
    # ---------------------------------------------------------------

    def set_velocity_body(self, mode_name, forward_mps, right_mps, down_mps=0.0, yawspeed_degs=0.0):
        """速度模式设置入口。调用前必须传入调用方自己的模式名，内部会核对是否仍是当前模式。
        [安全] 所有分量都做硬性限幅，防止上位机/VLM解析给出离谱数值。"""
        if self.should_stop_current_action():
            return False
        if not mode_manager.is_active(mode_name):
            return False  # 已经被切走了，静默拒绝，不抛异常打断调用方主流程
        if not self.armed_and_flying:
            print("[FlightExecutor] 拒绝速度指令：飞机还没完成起飞流程")
            return False

        forward_mps = clamp(forward_mps, -config.MAX_VELOCITY_MPS, config.MAX_VELOCITY_MPS)
        right_mps = clamp(right_mps, -config.MAX_VELOCITY_MPS, config.MAX_VELOCITY_MPS)
        down_mps = clamp(down_mps, -config.MAX_VELOCITY_MPS, config.MAX_VELOCITY_MPS)
        yawspeed_degs = clamp(yawspeed_degs, -config.MAX_YAWSPEED_DEGS, config.MAX_YAWSPEED_DEGS)

        with self._state_lock:
            self._setpoint_mode = "velocity_body"
            self.vel_forward = forward_mps
            self.vel_right = right_mps
            self.vel_down = down_mps
            self.vel_yawspeed = yawspeed_degs
            self._last_velocity_cmd_time = time.monotonic()
        return True

    async def fly_path_positions(self, mode_name, ne_offsets, step_distance=None, step_interval=None):
        """位置路径模式（画笔模式用）：给一串相对当前位置的(N,E)偏移，按顺序分级飞过去。
        每走一个点之前都会重新核对 mode_manager 是否仍是调用方的模式，一旦被切走立刻停止，
        不会把队列里剩下的点飞完。

        [激光] 这是真正"画线"的阶段，进入时开激光，不管是正常画完退出、
        还是中途因为模式切走/abort/降落被打断退出，用try/finally保证
        激光一定会被关掉——不会出现"模式已经切走了，但激光还跟着上一次
        的状态亮着"这种情况。"""
        step_distance = step_distance or config.SCREEN_STEP_DISTANCE
        step_interval = step_interval or config.SCREEN_STEP_INTERVAL

        if not self.armed_and_flying:
            print("[FlightExecutor] 拒绝路径指令：飞机还没完成起飞流程")
            return False

        with self._state_lock:
            self._setpoint_mode = "position"

        laser_control.turn_on()
        try:
            for (dn, de) in ne_offsets:
                if self.should_stop_current_action():
                    print(f"[FlightExecutor] 收到安全停止信号，路径执行中止 (来源:{mode_name})")
                    return False
                if not mode_manager.is_active(mode_name):
                    print(f"[FlightExecutor] 模式已切换，路径执行中止 (来源:{mode_name})")
                    return False
                target_n = self.current_n + dn
                target_e = self.current_e + de
                ok = await self._move_horizontal_to(
                    target_n, target_e, step_distance, step_interval, stop_on_land=True
                )
                if not ok:
                    return False
            return True
        finally:
            laser_control.turn_off()

    async def fly_pen_up_jump(self, mode_name, dn, de, step_distance=None, step_interval=None):
        """[画笔模式专用] "抬笔跳转"：直接在当前高度水平飞到(dn,de)偏移的
        目标点，不做垂直抬升/降回。用于两笔之间不连着画的情况。

        [改动] 之前这个方法会先垂直抬升一段高度再平移、最后再降回原高度，
        是因为担心飞机贴着原高度直接平移会"拖出一条连接两笔的误线"——
        但现在画线这件事是激光负责的，不是飞行轨迹本身，只要激光在这段
        平移期间保持关闭，不管飞机是不是贴着原高度飞过去，都不会画出
        任何东西，抬升这个动作已经没有必要，直接删掉简化。

        [激光] 进入时主动关一次激光(防御性——正常情况下上一次
        fly_path_positions()结束时已经通过try/finally关掉了，这里再关
        一次是双重保险，不依赖调用方一定按预期顺序调用)。这个方法执行
        期间激光全程保持关闭，不会在这里重新打开——真正画下一笔的
        laser_control.turn_on()是fly_path_positions()自己负责的。

        跟fly_path_positions()一样，每一步之前都重新核对mode_manager当前
        是不是调用方自己的模式，一旦被切走立刻停止，不会继续往下走。"""
        step_distance = step_distance or config.SCREEN_STEP_DISTANCE
        step_interval = step_interval or config.SCREEN_STEP_INTERVAL

        laser_control.turn_off()

        if not self.armed_and_flying:
            print("[FlightExecutor] 拒绝抬笔跳转：飞机还没完成起飞流程")
            return False
        if not mode_manager.is_active(mode_name):
            return False

        with self._state_lock:
            self._setpoint_mode = "position"

        target_n = self.current_n + dn
        target_e = self.current_e + de
        print(f"[FlightExecutor] 抬笔跳转: 水平移动到偏移({dn:.3f},{de:.3f}) ...")
        ok = await self._move_horizontal_to(
            target_n, target_e, step_distance, step_interval, stop_on_land=True
        )
        if not ok or self.should_stop_current_action() or not mode_manager.is_active(mode_name):
            print("[FlightExecutor] 抬笔跳转中止")
            return False
        return True

    async def hold_current_position(self, mode_name):
        """在不切换mode_manager模式的情况下，读取当前位置并切到position定点。"""
        if not mode_manager.is_active(mode_name):
            return False
        if not self.armed_and_flying:
            print("[FlightExecutor] 拒绝定点：飞机还没完成起飞流程")
            return False
        if self.should_stop_current_action():
            return False
        try:
            n, e, d = await self._get_position_once()
            yaw = self.yaw_lock
            async for att in self.drone.telemetry.attitude_euler():
                yaw = att.yaw_deg
                break
            if self.should_stop_current_action() or not mode_manager.is_active(mode_name):
                return False
            with self._state_lock:
                self.current_n, self.current_e, self.current_d = n, e, d
                self.yaw_lock = yaw
                self._setpoint_mode = "position"
            print(f"[FlightExecutor] 模式{mode_name}内定点悬停 N={n:.2f} E={e:.2f} D={d:.2f}")
            return True
        except Exception as e:
            print(f"[FlightExecutor][警告] 模式{mode_name}内定点失败: {e}")
            return False

    def request_hold_current_position(self, mode_name):
        """线程安全触发当前位置定点，供voice_vlm等同步线程调用。"""
        if self.loop is None:
            return False
        fut = asyncio.run_coroutine_threadsafe(self.hold_current_position(mode_name), self.loop)
        try:
            return bool(fut.result(timeout=3.0))
        except Exception as e:
            print(f"[FlightExecutor][警告] 请求定点失败: {e}")
            return False

    def should_stop_current_action(self):
        """安全事件触发后，普通动作应立刻停止给降落/接管让路。"""
        aborting = self.abort_event is not None and self.abort_event.is_set()
        landing = self.land_requested is not None and self.land_requested.is_set()
        return aborting or landing

    def request_reset(self):
        """仅地面允许：清理当前MAVSDK连接并让run_forever重新初始化。

        [安全校验] 第一道闸门(armed_and_flying/_arming_started)只是排除
        "明显还在正常飞行流程里"的情况。如果当前正处于人工接管
        (offboard_lost)之后的只读监听状态(_in_post_handover_monitor为True)，
        还有第二道闸门：必须拿到测距传感器的实时读数确认高度低于
        config.LAND_HEIGHT_CONFIRM_THRESHOLD，且armed遥测确认为False，
        才真正放行——不能仅凭标志已经复位就相信飞机已经落地。
        读数缺失/过期(超过5秒没更新)一律按"无法确认"拒绝，不做乐观放行。
        """
        if self.armed_and_flying or self._arming_started:
            return False, "飞机可能已解锁/起飞，拒绝重置"

        if self._in_post_handover_monitor:
            with self._post_handover_lock:
                height = self._post_handover_height_m
                armed = self._post_handover_armed
                updated_at = self._post_handover_updated_at

            # [安全] 必须是"明确读到armed==False"才算安全，armed是None
            # (还没收到过遥测，比如监听协程刚订阅、第一条数据还没到)不能被
            # 当成"默认安全"处理——不然会出现地面在这个极短窗口期发reset，
            # armed状态还没确认、但测距读数恰好已经低于阈值，就被误判放行的
            # 情况。所以这里反过来写：只有明确等于False才放行，True/None
            # 一律拒绝。
            if armed is not False:
                return False, (f"armed遥测状态为{armed!r}(不是明确的False)，"
                                f"无法确认已上锁，拒绝重置")
            # [安全] 同样用monotonic clock，跟_post_handover_monitor()写入
            # updated_at时用的时钟保持一致，不受系统时间调整影响——这里
            # 判断的是"能不能安全重置"，如果用墙上时钟、系统时间被往回调，
            # 这个新鲜度检查可能被绕过，让一个已经过期很久的读数被误判成
            # "刚刚更新过"，从而在没有实时确认的情况下允许了重置。
            if height is None or (time.monotonic() - updated_at) > 5.0:
                return False, ("无法获取有效的测距传感器读数(缺失或超过5秒未更新)，"
                                "拒绝重置——请确认飞机已落地、传感器工作正常后重试")
            if height >= config.LAND_HEIGHT_CONFIRM_THRESHOLD:
                return False, f"测距传感器读数{height:.2f}m，判定飞机仍在空中，拒绝重置"

            print(f"[FlightExecutor] 测距确认高度{height:.2f}m且已disarmed，允许重置")

        self._reset_requested.set()
        if self.loop is not None and self.abort_event is not None:
            self.loop.call_soon_threadsafe(self.abort_event.set)
        return True, "已请求重置飞控连接"

    def is_runner_active(self):
        return self._runner_active

    def request_takeoff(self):
        """请求起飞(mode=8)。只有在"已经进入OFFBOARD、还没解锁起飞"这个
        等待窗口内才有实际意义——_main_async()里在等待期间用
        self.takeoff_requested.wait()等这个事件，收到就往下走arm()+爬升。

        [安全] 如果已经armed_and_flying(已经飞起来了)，直接拒绝重复请求，
        不会让"再发一次mode=8"产生任何副作用(比如重新爬升一次)。如果飞控
        执行器还没连上/还没进入等待窗口(loop还是None)，也直接拒绝，
        不会静默丢失请求让人误以为已经生效。"""
        if self.armed_and_flying:
            print("[FlightExecutor] 已经在飞行状态，忽略重复的起飞请求")
            return False, "已经在飞行状态，无需重复起飞"
        if self.loop is None or self.takeoff_requested is None:
            print("[FlightExecutor] 拒绝起飞请求：飞控执行器还没初始化/还没连接")
            return False, "飞控执行器还没初始化，请稍后重试"
        self.loop.call_soon_threadsafe(self.takeoff_requested.set)
        return True, "已请求起飞"

    def request_land(self):
        """任何模式都可以请求降落，这个不受模式互斥限制——降落永远优先。
        [安全] 用独立的land_requested事件触发，不跟abort_event混用——
        abort_event专门表示"意外情况"，_climb_to()等分级移动函数只检查
        abort_event来决定要不要提前中断，这样正常的降落请求不会被
        自己触发的标志位打断降落循环本身。"""
        if self.loop is not None and self.land_requested is not None:
            self.loop.call_soon_threadsafe(self.land_requested.set)

    # ---------------------------------------------------------------
    # 内部：分级移动 / 起降（改编自test_04/test_05，逻辑不变）
    # ---------------------------------------------------------------

    async def _get_position_once(self):
        async for pv in self.drone.telemetry.position_velocity_ned():
            return pv.position.north_m, pv.position.east_m, pv.position.down_m

    async def _wait_until_reached(self, target_n, target_e, target_d,
                                   tolerance=None, timeout=None, stop_on_land=False):
        tolerance = tolerance or config.POSITION_TOLERANCE
        timeout = timeout or config.REACH_TIMEOUT
        start = asyncio.get_event_loop().time()
        async for pv in self.drone.telemetry.position_velocity_ned():
            if self.abort_event.is_set():
                return False
            if stop_on_land and self.land_requested.is_set():
                return False
            pos = pv.position
            dist = ((pos.north_m - target_n) ** 2 + (pos.east_m - target_e) ** 2
                     + (pos.down_m - target_d) ** 2) ** 0.5
            if dist < tolerance:
                return True
            if asyncio.get_event_loop().time() - start > timeout:
                print(f"[FlightExecutor][警告] 超过{timeout}秒未到达目标点")
                return False

    async def _climb_to(self, target_n, target_e, target_d, step_interval, label="", stop_on_land=False):
        start_d = self.current_d
        step = -config.CLIMB_STEP if target_d < start_d else config.CLIMB_STEP
        d = start_d
        while (step < 0 and d > target_d) or (step > 0 and d < target_d):
            if self.abort_event.is_set():
                return False
            if stop_on_land and self.land_requested.is_set():
                return False
            d += step
            if (step < 0 and d < target_d) or (step > 0 and d > target_d):
                d = target_d
            with self._state_lock:
                self.current_n, self.current_e, self.current_d = target_n, target_e, d
            await asyncio.sleep(step_interval)
        with self._state_lock:
            self.current_n, self.current_e, self.current_d = target_n, target_e, target_d
        return await self._wait_until_reached(target_n, target_e, target_d, stop_on_land=stop_on_land)

    async def _move_horizontal_to(self, target_n, target_e, step_distance, step_interval, stop_on_land=False):
        start_n, start_e = self.current_n, self.current_e
        total_dist = ((target_n - start_n) ** 2 + (target_e - start_e) ** 2) ** 0.5
        if total_dist > 1e-6:
            num_steps = max(1, int(total_dist / step_distance))
            for i in range(1, num_steps + 1):
                if self.abort_event.is_set():
                    return False
                if stop_on_land and self.land_requested.is_set():
                    return False
                frac = min(1.0, i / num_steps)
                with self._state_lock:
                    self.current_n = start_n + (target_n - start_n) * frac
                    self.current_e = start_e + (target_e - start_e) * frac
                await asyncio.sleep(step_interval)
        with self._state_lock:
            self.current_n, self.current_e = target_n, target_e
        return await self._wait_until_reached(
            target_n, target_e, self.current_d, stop_on_land=stop_on_land
        )

    async def _poll_distance_sensor_for_landing(self, threshold):
        """持续读取测距传感器，读数低于threshold就判定已贴地，返回True。
        [注] 不做超时判断，调用方必须用asyncio.wait_for包一层硬性超时——
        跟test_04/test_05里的poll_distance_sensor_for_landing逻辑完全一致，
        避免"传感器话题从头到尾一条数据都没发出来"时无限期卡住。"""
        async for ds in self.drone.telemetry.distance_sensor():
            if self.abort_event.is_set():
                return False
            h = ds.current_distance_m
            if h == h and h < threshold:  # h==h 用来排除NaN
                print(f"[FlightExecutor] 测距传感器读数{h:.3f}m，判定已贴地")
                return True
        return False

    async def _land_sequence(self):
        """[安全] 只应该在这两种情况下被调用：
             1. abort_reason == "disarmed"：飞控已经处于disarmed状态，电机已经停了，
                这里只做一次幂等disarm()确认，不发任何降落setpoint。
             2. abort_reason is None(正常land_requested)：走完整降落序列，
                规格跟test_04/test_05完全一致：分级下降 -> 测距传感器确认贴地
                (asyncio.wait_for硬超时兜底) -> 确认失败则切飞控原生Land()模式
                兜底 -> 等待in_air变为False(同样有硬超时)。
           绝不能在 abort_reason == "offboard_lost" 时调用——那种情况下飞机仍在
           被人工控制，不能碰油门/disarm。"""
        if self.abort_reason == "disarmed":
            print("[FlightExecutor] 飞控已处于disarmed状态，跳过降落序列，仅确认上锁状态")
            try:
                await self.drone.action.disarm()
            except Exception:
                pass  # 本来就已经disarmed，报错属预期，忽略
            return

        print("[FlightExecutor] 降落中(保持OFFBOARD，用setpoint分级下降到地面)...")
        await self._climb_to(self.current_n, self.current_e, self.origin_d,
                              step_interval=config.LAND_STEP_INTERVAL, label="降落")
        if self.abort_event.is_set():
            print("[FlightExecutor] 降落过程中检测到异常(意外abort)，交给遥控器接管，停止后续降落流程")
            return

        print("[FlightExecutor] 等待飞控确认已落地...")
        already_disarmed = False

        # ---- 优先用测距传感器判断是否真的贴地了，硬超时兜底，不无限期等待 ----
        height_confirmed_landed = False
        try:
            height_confirmed_landed = await asyncio.wait_for(
                self._poll_distance_sensor_for_landing(config.LAND_HEIGHT_CONFIRM_THRESHOLD),
                timeout=config.LAND_HEIGHT_CONFIRM_TIMEOUT,
            )
        except asyncio.TimeoutError:
            pass  # 超时了，height_confirmed_landed保持False，走下面的Land()兜底
        except Exception as e:
            print(f"[FlightExecutor][提示] 读取测距传感器失败: {e}，改走飞控Land模式兜底")

        if height_confirmed_landed and not self.abort_event.is_set():
            print("[FlightExecutor] 已通过测距传感器确认贴地，直接尝试上锁...")
            # disarm之前先取消看门狗，避免它把这个预期内的状态变化误判成异常
            if self._watchdog_task is not None:
                self._watchdog_task.cancel()
                try:
                    await self._watchdog_task
                except asyncio.CancelledError:
                    pass
                self._watchdog_task = None
            try:
                await self.drone.action.disarm()
                print("[FlightExecutor] 已上锁")
                already_disarmed = True
            except Exception as e:
                print(f"[FlightExecutor][警告] 直接上锁失败: {e}，改走飞控Land模式兜底")

        # ---- 上面这条路没能确认/没能直接上锁：交给飞控自己的Land逻辑兜底 ----
        if not already_disarmed:
            if self._watchdog_task is not None:
                self._watchdog_task.cancel()
                try:
                    await self._watchdog_task
                except asyncio.CancelledError:
                    pass
                self._watchdog_task = None

            print("[FlightExecutor] 正在切换到飞控自身Land模式，交给它完成最后贴地和上锁...")
            try:
                await self.drone.action.land()
                print("[FlightExecutor] 已切换到Land模式，等待飞控自动完成降落...")
            except Exception as e:
                print(f"[FlightExecutor][警告] 切换Land模式失败: {e}，请人工用遥控器接管降落")

            land_wait_start = asyncio.get_event_loop().time()
            try:
                async for in_air in self.drone.telemetry.in_air():
                    if not in_air:
                        print("[FlightExecutor] 飞控确认已落地(Land模式)")
                        break
                    if asyncio.get_event_loop().time() - land_wait_start > config.LAND_NATIVE_TIMEOUT:
                        print(f"[FlightExecutor][警告] Land模式超过{config.LAND_NATIVE_TIMEOUT:.0f}秒"
                              f"仍未确认落地，建议人工检查(可考虑遥控器接管)")
                        break
            except Exception as e:
                print(f"[FlightExecutor][警告] 监听in_air状态异常: {e}")


    async def _post_handover_monitor(self):
        """[安全] 人工接管(offboard_lost)之后调用。保持MAVSDK连接存活，
        只订阅遥测(不发送任何setpoint、不碰油门/解锁状态)，持续把最新的
        测距传感器高度和armed状态写进_post_handover_height_m/_armed，
        供request_reset()做实时校验。跟_land_sequence()里落地确认用的
        判断依据一致：优先信测距传感器的物理高度读数，而不是依赖
        in_air/flight_mode这类依赖本地位置(光流)估计的判断——那类判断在
        贴地时因为光流质量下降，本身就可能失真，这个坑在test_04/05的
        注释里已经提过，这里延续同样的原则。

        只有当地面发起reset(_reset_requested被设置)时才结束这个监听。"""

        async def _watch_distance():
            async for ds in self.drone.telemetry.distance_sensor():
                if self._reset_requested.is_set():
                    return
                h = ds.current_distance_m
                if h == h:  # 排除NaN
                    with self._post_handover_lock:
                        self._post_handover_height_m = h
                        self._post_handover_updated_at = time.monotonic()

        async def _watch_armed():
            async for is_armed in self.drone.telemetry.armed():
                if self._reset_requested.is_set():
                    return
                with self._post_handover_lock:
                    self._post_handover_armed = is_armed

        task_d = asyncio.create_task(_watch_distance())
        task_a = asyncio.create_task(_watch_armed())
        try:
            while not self._reset_requested.is_set():
                await asyncio.sleep(0.2)
        finally:
            for t in (task_d, task_a):
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    print(f"[FlightExecutor][接管监听清理异常，忽略] {e}")

    async def _cleanup_background_tasks(self):
        """[安全] 不管走的是哪条收尾路径，都要把自己开的后台任务(setpoint发送、
        两个看门狗)彻底取消掉，不留孤儿任务。_watchdog_task可能已经在
        _land_sequence()里被cancel并置None了，这里对None做了保护，不会重复处理。"""
        for task in (self._sender_task, self._watchdog_task, self._armed_watchdog_task,
                     self._idle_watcher_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    print(f"[FlightExecutor][清理任务异常，忽略] {e}")
        self._sender_task = None
        self._watchdog_task = None
        self._armed_watchdog_task = None
        self._idle_watcher_task = None


# 全局单例
flight_executor = FlightExecutor()