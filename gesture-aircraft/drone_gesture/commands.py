from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import time
from typing import Protocol


class CommandKind(str, Enum):
    HOVER = "hover"
    MOVE_LEFT = "move_left"
    MOVE_RIGHT = "move_right"
    ASCEND = "ascend"
    DESCEND = "descend"
    FORWARD = "forward"
    BACKWARD = "backward"


@dataclass(frozen=True, slots=True)
class MotionCommand:
    kind: CommandKind
    intensity: float = 0.0
    timestamp: float = 0.0
    reason: str = ""

    @staticmethod
    def hover(timestamp: float, reason: str = "") -> "MotionCommand":
        return MotionCommand(CommandKind.HOVER, 0.0, timestamp, reason)


class CommandSink(Protocol):
    def send(self, command: MotionCommand) -> None:
        """Send one normalized motion command."""


class ConsoleCommandSink:
    """Rate-limited console output; replace this class when connecting a flight controller."""

    def __init__(self, min_interval_s: float = 0.15, intensity_delta: float = 0.08):
        self.min_interval_s = min_interval_s
        self.intensity_delta = intensity_delta
        self._last_command: MotionCommand | None = None
        self._last_print_time = 0.0

    def send(self, command: MotionCommand) -> None:
        now = time.monotonic()
        changed = self._last_command is None or command.kind != self._last_command.kind
        strength_changed = (
            self._last_command is None
            or abs(command.intensity - self._last_command.intensity) >= self.intensity_delta
        )
        if changed or (strength_changed and now - self._last_print_time >= self.min_interval_s):
            print(
                f"[COMMAND] {command.kind.value:<10} "
                f"intensity={command.intensity:.2f} reason={command.reason}"
            )
            self._last_print_time = now
        self._last_command = command
