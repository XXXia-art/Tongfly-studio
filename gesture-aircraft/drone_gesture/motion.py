from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .commands import CommandKind, MotionCommand
from .gestures import GestureKind, GestureObservation, Point


@dataclass(slots=True)
class MotionConfig:
    action_duration_s: float = 0.700
    transient_loss_grace_s: float = 0.120
    trajectory_window_s: float = 0.180
    movement_threshold: float = 0.16
    direction_dominance: float = 1.25
    fixed_action_intensity: float = 0.55
    velocity_smoothing: float = 0.45


class MotionController:
    def __init__(self, config: MotionConfig | None = None):
        self.config = config or MotionConfig()
        self._trajectory: deque[tuple[float, Point]] = deque()
        self._last_command = MotionCommand.hover(0.0, "startup")
        self._smoothed_vx = 0.0
        self._smoothed_vy = 0.0
        self._previous_gesture = GestureKind.NONE
        self._last_seen_time: float | None = None
        self._executing_until: float | None = None
        self._executing_kind: CommandKind | None = None
        self._waiting_for_rearm = False

    @property
    def last_command(self) -> MotionCommand:
        return self._last_command

    def is_executing(self, timestamp: float) -> bool:
        return self._executing_until is not None and timestamp < self._executing_until

    def reset(self, timestamp: float = 0.0) -> MotionCommand:
        self._trajectory.clear()
        self._smoothed_vx = 0.0
        self._smoothed_vy = 0.0
        self._previous_gesture = GestureKind.NONE
        self._last_seen_time = None
        self._executing_until = None
        self._executing_kind = None
        self._waiting_for_rearm = False
        self._last_command = MotionCommand.hover(timestamp, "reset")
        return self._last_command

    def update(self, observation: GestureObservation) -> MotionCommand:
        gesture = observation.gesture
        timestamp = observation.timestamp

        if self.is_executing(timestamp) and self._executing_kind is not None:
            self._last_command = MotionCommand(
                self._executing_kind,
                self.config.fixed_action_intensity,
                timestamp,
                "executing_ignore_recognition",
            )
            return self._last_command

        if self._executing_until is not None and timestamp >= self._executing_until:
            self._finish_action(timestamp)
            return self._last_command

        if self._waiting_for_rearm:
            if gesture in (GestureKind.NONE, GestureKind.UNKNOWN):
                self._waiting_for_rearm = False
            else:
                self._last_command = MotionCommand.hover(timestamp, "waiting_for_rearm")
                return self._last_command

        if gesture == GestureKind.NONE:
            if (
                self._last_seen_time is not None
                and timestamp - self._last_seen_time <= self.config.transient_loss_grace_s
            ):
                self._last_command = MotionCommand(
                    self._last_command.kind,
                    self._last_command.intensity,
                    timestamp,
                    "transient_hand_loss",
                )
                return self._last_command
            return self._hover_and_clear(timestamp, "hand_lost")
        self._last_seen_time = timestamp
        if gesture == GestureKind.OPEN_PALM:
            self._clear_swipe()
            return self._start_action(CommandKind.FORWARD, timestamp, "open_palm")
        if gesture == GestureKind.FIST:
            self._clear_swipe()
            return self._start_action(CommandKind.BACKWARD, timestamp, "fist")
        if gesture != GestureKind.TWO_FINGER or observation.tracking_point is None:
            return self._hover_and_clear(timestamp, "gesture_unknown")

        if self._previous_gesture != GestureKind.TWO_FINGER:
            self._clear_swipe()
        self._previous_gesture = GestureKind.TWO_FINGER
        self._trajectory.append((timestamp, observation.tracking_point))
        cutoff = timestamp - self.config.trajectory_window_s
        while len(self._trajectory) > 2 and self._trajectory[0][0] < cutoff:
            self._trajectory.popleft()

        if len(self._trajectory) < 2:
            self._last_command = MotionCommand.hover(timestamp, "two_finger_ready")
            return self._last_command

        start_t, start_point = self._trajectory[0]
        end_t, end_point = self._trajectory[-1]
        elapsed = end_t - start_t
        if elapsed <= 1e-4:
            return self._last_command

        raw_vx = (end_point.x - start_point.x) / elapsed
        raw_vy = (end_point.y - start_point.y) / elapsed
        alpha = self.config.velocity_smoothing
        self._smoothed_vx = alpha * raw_vx + (1.0 - alpha) * self._smoothed_vx
        self._smoothed_vy = alpha * raw_vy + (1.0 - alpha) * self._smoothed_vy

        abs_x = abs(self._smoothed_vx)
        abs_y = abs(self._smoothed_vy)
        dominant_speed = max(abs_x, abs_y)
        if dominant_speed >= self.config.movement_threshold:
            command_kind: CommandKind | None = None
            if abs_x >= abs_y * self.config.direction_dominance:
                command_kind = (
                    CommandKind.MOVE_RIGHT if self._smoothed_vx > 0 else CommandKind.MOVE_LEFT
                )
            elif abs_y >= abs_x * self.config.direction_dominance:
                # Image y grows downward.
                command_kind = CommandKind.DESCEND if self._smoothed_vy > 0 else CommandKind.ASCEND

            if command_kind is not None:
                return self._start_action(command_kind, timestamp, "two_finger_swipe")

        self._last_command = MotionCommand.hover(timestamp, "two_finger_stationary")
        return self._last_command

    def velocity(self) -> tuple[float, float]:
        return self._smoothed_vx, self._smoothed_vy

    def _start_action(
        self, kind: CommandKind, timestamp: float, reason: str
    ) -> MotionCommand:
        self._previous_gesture = (
            GestureKind.OPEN_PALM if kind == CommandKind.FORWARD else
            GestureKind.FIST if kind == CommandKind.BACKWARD else
            self._previous_gesture
        )
        self._clear_swipe()
        self._executing_kind = kind
        self._executing_until = timestamp + self.config.action_duration_s
        self._last_command = MotionCommand(
            kind,
            self.config.fixed_action_intensity,
            timestamp,
            f"{reason}_action_started",
        )
        return self._last_command

    def _finish_action(self, timestamp: float) -> None:
        self._executing_until = None
        self._executing_kind = None
        self._waiting_for_rearm = True
        self._previous_gesture = GestureKind.NONE
        self._last_seen_time = None
        self._last_command = MotionCommand.hover(timestamp, "action_complete")

    def _hover_and_clear(self, timestamp: float, reason: str) -> MotionCommand:
        self._clear_swipe()
        self._previous_gesture = GestureKind.NONE
        self._last_seen_time = None
        self._last_command = MotionCommand.hover(timestamp, reason)
        return self._last_command

    def _clear_swipe(self) -> None:
        self._trajectory.clear()
        self._smoothed_vx = 0.0
        self._smoothed_vy = 0.0
