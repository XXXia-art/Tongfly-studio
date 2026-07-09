import unittest

from drone_gesture.commands import CommandKind
from drone_gesture.gestures import GestureKind, GestureObservation, Point
from drone_gesture.motion import MotionConfig, MotionController


def observation(t: float, gesture: GestureKind, x: float = 0.5, y: float = 0.5):
    point = Point(x, y) if gesture == GestureKind.TWO_FINGER else None
    return GestureObservation(t, gesture, point)


class MotionControllerTests(unittest.TestCase):
    def setUp(self):
        config = MotionConfig(
            action_duration_s=0.50,
            fixed_action_intensity=0.55,
            velocity_smoothing=1.0,
            movement_threshold=0.10,
        )
        self.controller = MotionController(config)

    def test_open_palm_starts_fixed_forward_action(self):
        command = self.controller.update(observation(0.0, GestureKind.OPEN_PALM))
        self.assertEqual(command.kind, CommandKind.FORWARD)
        self.assertEqual(command.intensity, 0.55)
        self.assertEqual(command.reason, "open_palm_action_started")

    def test_fist_starts_fixed_backward_action(self):
        command = self.controller.update(observation(0.0, GestureKind.FIST))
        self.assertEqual(command.kind, CommandKind.BACKWARD)
        self.assertEqual(command.intensity, 0.55)

    def test_hand_loss_immediately_hovers(self):
        self.controller.update(observation(0.0, GestureKind.TWO_FINGER, 0.5, 0.5))
        command = self.controller.update(observation(0.2, GestureKind.NONE))
        self.assertEqual(command.kind, CommandKind.HOVER)

    def test_transient_hand_loss_keeps_last_command(self):
        self.controller.update(observation(0.0, GestureKind.TWO_FINGER, 0.5, 0.5))
        command = self.controller.update(observation(0.05, GestureKind.NONE))
        self.assertEqual(command.kind, CommandKind.HOVER)
        self.assertEqual(command.reason, "transient_hand_loss")

    def test_right_swipe_starts_fixed_action_and_ignores_recognition(self):
        self.controller.update(observation(0.00, GestureKind.TWO_FINGER, 0.40, 0.50))
        moving = self.controller.update(observation(0.10, GestureKind.TWO_FINGER, 0.48, 0.50))
        self.assertEqual(moving.kind, CommandKind.MOVE_RIGHT)
        self.assertEqual(moving.intensity, 0.55)
        self.assertEqual(moving.reason, "two_finger_swipe_action_started")

        ignored = self.controller.update(observation(0.30, GestureKind.FIST))
        self.assertEqual(ignored.kind, CommandKind.MOVE_RIGHT)
        self.assertEqual(ignored.reason, "executing_ignore_recognition")

        stopped = self.controller.update(observation(0.61, GestureKind.TWO_FINGER, 0.48, 0.50))
        self.assertEqual(stopped.kind, CommandKind.HOVER)
        self.assertEqual(stopped.reason, "action_complete")

    def test_action_requires_rearm_before_next_trigger(self):
        self.controller.update(observation(0.00, GestureKind.OPEN_PALM))
        self.controller.update(observation(0.60, GestureKind.OPEN_PALM))
        waiting = self.controller.update(observation(0.70, GestureKind.OPEN_PALM))
        self.assertEqual(waiting.kind, CommandKind.HOVER)
        self.assertEqual(waiting.reason, "waiting_for_rearm")

        rearmed = self.controller.update(observation(0.80, GestureKind.NONE))
        self.assertEqual(rearmed.kind, CommandKind.HOVER)

        next_action = self.controller.update(observation(0.90, GestureKind.OPEN_PALM))
        self.assertEqual(next_action.kind, CommandKind.FORWARD)

    def test_upward_image_motion_ascends(self):
        self.controller.update(observation(0.0, GestureKind.TWO_FINGER, 0.5, 0.6))
        command = self.controller.update(observation(0.1, GestureKind.TWO_FINGER, 0.5, 0.5))
        self.assertEqual(command.kind, CommandKind.ASCEND)
        self.assertEqual(command.intensity, 0.55)

    def test_diagonal_motion_is_rejected(self):
        self.controller.update(observation(0.0, GestureKind.TWO_FINGER, 0.4, 0.4))
        command = self.controller.update(observation(0.1, GestureKind.TWO_FINGER, 0.5, 0.5))
        self.assertEqual(command.kind, CommandKind.HOVER)


if __name__ == "__main__":
    unittest.main()
