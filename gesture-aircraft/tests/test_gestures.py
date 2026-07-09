import unittest

from drone_gesture.gestures import GestureKind, GestureStabilizer


class GestureStabilizerTests(unittest.TestCase):
    def test_default_requires_full_three_tenths_second_window(self):
        stabilizer = GestureStabilizer()
        for _ in range(8):
            self.assertEqual(stabilizer.update(GestureKind.FIST), GestureKind.NONE)
        self.assertEqual(stabilizer.update(GestureKind.FIST), GestureKind.FIST)

    def test_default_allows_two_noisy_frames(self):
        stabilizer = GestureStabilizer()
        sequence = [GestureKind.FIST] * 7 + [GestureKind.UNKNOWN] * 2
        for gesture in sequence[:-1]:
            self.assertEqual(stabilizer.update(gesture), GestureKind.NONE)
        self.assertEqual(stabilizer.update(sequence[-1]), GestureKind.FIST)

    def test_can_require_full_window_consistency(self):
        stabilizer = GestureStabilizer(window_size=9, minimum_votes=9)
        for _ in range(8):
            self.assertEqual(stabilizer.update(GestureKind.OPEN_PALM), GestureKind.NONE)
        self.assertEqual(stabilizer.update(GestureKind.OPEN_PALM), GestureKind.OPEN_PALM)

    def test_bridges_short_hand_loss(self):
        stabilizer = GestureStabilizer(window_size=3, minimum_votes=3, max_missing_frames=2)
        for _ in range(3):
            stabilizer.update(GestureKind.OPEN_PALM)
        self.assertEqual(stabilizer.update(GestureKind.NONE), GestureKind.OPEN_PALM)
        self.assertEqual(stabilizer.update(GestureKind.NONE), GestureKind.OPEN_PALM)
        self.assertEqual(stabilizer.update(GestureKind.NONE), GestureKind.NONE)


if __name__ == "__main__":
    unittest.main()
