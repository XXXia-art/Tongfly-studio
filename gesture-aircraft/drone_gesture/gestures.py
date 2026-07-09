from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from enum import Enum
import math
from typing import Iterable, Sequence


class GestureKind(str, Enum):
    NONE = "none"
    UNKNOWN = "unknown"
    TWO_FINGER = "two_finger"
    OPEN_PALM = "open_palm"
    FIST = "fist"


@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float
    z: float = 0.0


@dataclass(frozen=True, slots=True)
class GestureObservation:
    timestamp: float
    gesture: GestureKind
    tracking_point: Point | None = None
    landmarks: tuple[Point, ...] = ()


def _distance(a: Point, b: Point) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _angle(a: Point, b: Point, c: Point) -> float:
    """Angle ABC in degrees."""
    ab = (a.x - b.x, a.y - b.y)
    cb = (c.x - b.x, c.y - b.y)
    denominator = math.hypot(*ab) * math.hypot(*cb)
    if denominator < 1e-8:
        return 0.0
    cosine = max(-1.0, min(1.0, (ab[0] * cb[0] + ab[1] * cb[1]) / denominator))
    return math.degrees(math.acos(cosine))


def _finger_extended(points: Sequence[Point], mcp: int, pip: int, dip: int, tip: int) -> bool:
    straight = _angle(points[mcp], points[pip], points[dip]) > 150.0
    tip_straight = _angle(points[pip], points[dip], points[tip]) > 145.0
    reaches_out = _distance(points[tip], points[0]) > _distance(points[pip], points[0]) * 1.08
    return straight and tip_straight and reaches_out


def classify_landmarks(landmarks: Iterable[object]) -> tuple[GestureKind, Point]:
    """Classify one hand from MediaPipe-like landmarks containing x/y/z attributes."""
    points = tuple(
        Point(float(item.x), float(item.y), float(getattr(item, "z", 0.0)))
        for item in landmarks
    )
    if len(points) != 21:
        raise ValueError(f"Expected 21 hand landmarks, got {len(points)}")

    index = _finger_extended(points, 5, 6, 7, 8)
    middle = _finger_extended(points, 9, 10, 11, 12)
    ring = _finger_extended(points, 13, 14, 15, 16)
    pinky = _finger_extended(points, 17, 18, 19, 20)

    palm_width = max(_distance(points[5], points[17]), 1e-5)
    palm_center = Point(
        (points[0].x + points[5].x + points[9].x + points[13].x + points[17].x) / 5.0,
        (points[0].y + points[5].y + points[9].y + points[13].y + points[17].y) / 5.0,
    )
    thumb_extended = _distance(points[4], palm_center) > palm_width * 0.85
    two_fingers_together = _distance(points[8], points[12]) < palm_width * 0.72
    tracking_point = Point(
        (points[8].x + points[12].x) / 2.0,
        (points[8].y + points[12].y) / 2.0,
        (points[8].z + points[12].z) / 2.0,
    )

    if index and middle and not ring and not pinky and two_fingers_together:
        return GestureKind.TWO_FINGER, tracking_point
    if index and middle and ring and pinky and thumb_extended:
        return GestureKind.OPEN_PALM, palm_center
    if not index and not middle and not ring and not pinky:
        return GestureKind.FIST, palm_center
    return GestureKind.UNKNOWN, palm_center


class GestureStabilizer:
    """Small majority filter that bridges very short detector dropouts."""

    def __init__(
        self,
        window_size: int = 9,
        minimum_votes: int = 7,
        max_missing_frames: int = 3,
    ):
        self.window_size = window_size
        self.minimum_votes = minimum_votes
        self.max_missing_frames = max_missing_frames
        self._history: deque[GestureKind] = deque(maxlen=window_size)
        self._stable = GestureKind.NONE
        self._missing_frames = 0

    def reset(self) -> None:
        self._history.clear()
        self._stable = GestureKind.NONE
        self._missing_frames = 0

    def update(self, gesture: GestureKind) -> GestureKind:
        if gesture == GestureKind.NONE:
            self._missing_frames += 1
            if self._stable != GestureKind.NONE and self._missing_frames <= self.max_missing_frames:
                return self._stable
            self.reset()
            return GestureKind.NONE
        self._missing_frames = 0
        self._history.append(gesture)
        candidate, votes = Counter(self._history).most_common(1)[0]
        if len(self._history) >= self.window_size and votes >= self.minimum_votes:
            self._stable = candidate
        return self._stable
