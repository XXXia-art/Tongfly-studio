from __future__ import annotations

import argparse
from pathlib import Path
import time

import cv2
import mediapipe as mp
import numpy as np

from .commands import CommandKind, ConsoleCommandSink, MotionCommand
from .gestures import (
    GestureKind,
    GestureObservation,
    GestureStabilizer,
    Point,
    classify_landmarks,
)
from .motion import MotionController
from .motion import MotionConfig


MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)

HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20), (0, 17),
)

COMMAND_LABELS = {
    CommandKind.HOVER: "HOVER",
    CommandKind.MOVE_LEFT: "LEFT",
    CommandKind.MOVE_RIGHT: "RIGHT",
    CommandKind.ASCEND: "UP",
    CommandKind.DESCEND: "DOWN",
    CommandKind.FORWARD: "FORWARD",
    CommandKind.BACKWARD: "BACKWARD",
}

GESTURE_LABELS = {
    GestureKind.NONE: "NO HAND",
    GestureKind.UNKNOWN: "UNKNOWN",
    GestureKind.TWO_FINGER: "TWO FINGERS",
    GestureKind.OPEN_PALM: "OPEN PALM",
    GestureKind.FIST: "FIST",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Webcam gesture control prototype")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--model", type=Path, default=Path("models/hand_landmarker.task"))
    parser.add_argument("--no-mirror", action="store_true")
    parser.add_argument("--detection-confidence", type=float, default=0.45)
    parser.add_argument("--presence-confidence", type=float, default=0.45)
    parser.add_argument("--tracking-confidence", type=float, default=0.45)
    parser.add_argument("--missing-frames", type=int, default=3)
    parser.add_argument("--stable-window-frames", type=int, default=9)
    parser.add_argument("--stable-minimum-votes", type=int, default=7)
    parser.add_argument("--action-duration", type=float, default=0.70)
    parser.add_argument("--fixed-intensity", type=float, default=0.55)
    parser.add_argument("--movement-threshold", type=float, default=0.12)
    parser.add_argument("--direction-dominance", type=float, default=1.12)
    parser.add_argument("--trajectory-window", type=float, default=0.220)
    parser.add_argument("--velocity-smoothing", type=float, default=0.55)
    return parser.parse_args()


def _open_camera(index: int, width: int, height: int) -> cv2.VideoCapture:
    """Try common Windows backends before falling back to OpenCV's default."""
    backends = (cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY)
    for backend in backends:
        capture = cv2.VideoCapture(index, backend)
        if capture.isOpened():
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            return capture
        capture.release()
    return cv2.VideoCapture()


def _draw_hand(frame: np.ndarray, points: tuple[Point, ...]) -> None:
    height, width = frame.shape[:2]
    pixels = [(int(point.x * width), int(point.y * height)) for point in points]
    for start, end in HAND_CONNECTIONS:
        cv2.line(frame, pixels[start], pixels[end], (60, 210, 255), 2, cv2.LINE_AA)
    for index, pixel in enumerate(pixels):
        color = (80, 255, 120) if index in (8, 12) else (255, 180, 60)
        cv2.circle(frame, pixel, 4, color, -1, cv2.LINE_AA)


def _draw_hud(
    frame: np.ndarray,
    gesture: GestureKind,
    command: MotionCommand,
    fps: float,
    tracking_point: Point | None,
    velocity: tuple[float, float],
) -> None:
    overlay = frame.copy()
    cv2.rectangle(overlay, (15, 15), (390, 150), (15, 20, 28), -1)
    cv2.addWeighted(overlay, 0.72, frame, 0.28, 0.0, frame)
    cv2.putText(frame, f"GESTURE  {GESTURE_LABELS[gesture]}", (32, 51),
                cv2.FONT_HERSHEY_SIMPLEX, 0.72, (230, 235, 240), 2, cv2.LINE_AA)
    command_color = (80, 240, 120) if command.kind == CommandKind.HOVER else (60, 190, 255)
    cv2.putText(frame, f"COMMAND  {COMMAND_LABELS[command.kind]}", (32, 88),
                cv2.FONT_HERSHEY_SIMPLEX, 0.78, command_color, 2, cv2.LINE_AA)
    cv2.putText(frame, f"INTENSITY {command.intensity:.2f}    FPS {fps:.1f}", (32, 124),
                cv2.FONT_HERSHEY_SIMPLEX, 0.62, (190, 200, 210), 2, cv2.LINE_AA)

    if tracking_point is not None and gesture == GestureKind.TWO_FINGER:
        height, width = frame.shape[:2]
        origin = (int(tracking_point.x * width), int(tracking_point.y * height))
        vx, vy = velocity
        scale = 100
        target = (int(origin[0] + vx * scale), int(origin[1] + vy * scale))
        cv2.arrowedLine(frame, origin, target, (70, 90, 255), 4, cv2.LINE_AA, tipLength=0.3)

    cv2.putText(frame, "Q/ESC quit   R reset", (20, frame.shape[0] - 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (225, 225, 225), 1, cv2.LINE_AA)


def run() -> int:
    args = parse_args()
    model_path = args.model.resolve()
    if not model_path.exists():
        print(f"Model not found: {model_path}")
        print("Run: python scripts/download_model.py")
        print(f"Source: {MODEL_URL}")
        return 2

    capture = _open_camera(args.camera, args.width, args.height)
    if not capture.isOpened():
        print(f"Cannot open camera index {args.camera}.")
        return 3

    options = mp.tasks.vision.HandLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_hands=1,
        min_hand_detection_confidence=args.detection_confidence,
        min_hand_presence_confidence=args.presence_confidence,
        min_tracking_confidence=args.tracking_confidence,
    )
    controller = MotionController(MotionConfig(
        action_duration_s=args.action_duration,
        fixed_action_intensity=args.fixed_intensity,
        movement_threshold=args.movement_threshold,
        direction_dominance=args.direction_dominance,
        trajectory_window_s=args.trajectory_window,
        velocity_smoothing=args.velocity_smoothing,
    ))
    stabilizer = GestureStabilizer(
        window_size=args.stable_window_frames,
        minimum_votes=args.stable_minimum_votes,
        max_missing_frames=args.missing_frames,
    )
    sink = ConsoleCommandSink()
    started = time.monotonic()
    previous_frame_time = started
    fps = 0.0

    print("Camera started. This prototype emits simulated commands only.")
    try:
        with mp.tasks.vision.HandLandmarker.create_from_options(options) as landmarker:
            while True:
                ok, frame = capture.read()
                if not ok:
                    print("Camera frame read failed.")
                    break
                if not args.no_mirror:
                    frame = cv2.flip(frame, 1)

                now = time.monotonic()
                timestamp = now - started
                frame_delta = max(now - previous_frame_time, 1e-6)

                raw_gesture = GestureKind.NONE
                tracking_point: Point | None = None
                points: tuple[Point, ...] = ()
                recognition_enabled = not controller.is_executing(timestamp)
                if recognition_enabled:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                    result = landmarker.detect_for_video(mp_image, int(timestamp * 1000))
                    if result.hand_landmarks:
                        raw_gesture, tracking_point = classify_landmarks(result.hand_landmarks[0])
                        points = tuple(
                            Point(float(p.x), float(p.y), float(p.z))
                            for p in result.hand_landmarks[0]
                        )
                        _draw_hand(frame, points)
                    stable_gesture = stabilizer.update(raw_gesture)
                else:
                    stabilizer.reset()
                    stable_gesture = GestureKind.NONE

                # Use the fresh tracking point only when the stabilized gesture agrees.
                if stable_gesture != GestureKind.TWO_FINGER:
                    tracking_point = None
                observation = GestureObservation(
                    timestamp=timestamp,
                    gesture=stable_gesture,
                    tracking_point=tracking_point,
                    landmarks=points,
                )
                command = controller.update(observation)
                sink.send(command)

                instant_fps = 1.0 / frame_delta
                fps = instant_fps if fps == 0.0 else fps * 0.9 + instant_fps * 0.1
                previous_frame_time = now
                _draw_hud(
                    frame,
                    stable_gesture,
                    command,
                    fps,
                    tracking_point,
                    controller.velocity(),
                )
                cv2.imshow("Drone Gesture Control - PC Prototype", frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q"), ord("Q")):
                    break
                if key in (ord("r"), ord("R")):
                    stabilizer.reset()
                    sink.send(controller.reset(timestamp))
    finally:
        capture.release()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
