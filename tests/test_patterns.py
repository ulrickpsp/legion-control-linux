from __future__ import annotations

import unittest

from legion_control.patterns import (
    COLOR_AWARE_KINDS,
    PatternKind,
    pattern_configuration,
    pattern_zones,
)
from legion_control.rgb import RGB_ZONE_COUNT, RgbColor


COLOR = RgbColor(0, 229, 255)


def _luminance(color: RgbColor) -> float:
    return 0.2126 * color.red + 0.7152 * color.green + 0.0722 * color.blue


class PatternRenderingTests(unittest.TestCase):
    def test_every_pattern_fills_all_twenty_four_zones(self) -> None:
        for kind in PatternKind:
            with self.subTest(pattern=kind.value):
                zones = pattern_zones(kind, COLOR, 0.37)
                self.assertEqual(len(zones), RGB_ZONE_COUNT)
                self.assertTrue(all(isinstance(color, RgbColor) for color in zones))

    def test_rendering_is_deterministic(self) -> None:
        """A preset must look the same every time it is applied."""

        for kind in PatternKind:
            with self.subTest(pattern=kind.value):
                self.assertEqual(
                    pattern_zones(kind, COLOR, 0.42),
                    pattern_zones(kind, COLOR, 0.42),
                )

    def test_the_phase_wraps_instead_of_being_rejected(self) -> None:
        for kind in PatternKind:
            with self.subTest(pattern=kind.value):
                self.assertEqual(
                    pattern_zones(kind, COLOR, 0.3),
                    pattern_zones(kind, COLOR, 1.3),
                )
                self.assertEqual(
                    pattern_zones(kind, COLOR, 0.3),
                    pattern_zones(kind, COLOR, -0.7),
                )

    def test_a_pattern_is_not_a_flat_colour(self) -> None:
        """A uniform frame would be a solid preset wearing a pattern's name."""

        for kind in PatternKind:
            with self.subTest(pattern=kind.value):
                zones = pattern_zones(kind, COLOR, 0.37)
                self.assertGreater(len(set(zones)), 4)

    def test_only_colour_aware_patterns_follow_the_chosen_colour(self) -> None:
        for kind in PatternKind:
            with self.subTest(pattern=kind.value):
                red = pattern_zones(kind, RgbColor(255, 0, 0), 0.37)
                blue = pattern_zones(kind, RgbColor(0, 0, 255), 0.37)
                if kind in COLOR_AWARE_KINDS:
                    self.assertNotEqual(red, blue)
                else:
                    self.assertEqual(red, blue)

    def test_no_pattern_leaves_the_keyboard_looking_switched_off(self) -> None:
        """A comet or a crest on a black bed reads as a fault, not as design."""

        for kind in PatternKind:
            with self.subTest(pattern=kind.value):
                zones = pattern_zones(kind, COLOR, 0.37)
                average = sum(_luminance(color) for color in zones) / len(zones)
                self.assertGreater(average, 30)

    def test_a_pattern_has_a_clear_bright_point(self) -> None:
        for kind in PatternKind:
            with self.subTest(pattern=kind.value):
                zones = pattern_zones(kind, COLOR, 0.37)
                self.assertGreater(max(_luminance(color) for color in zones), 150)

    def test_configuration_carries_brightness_and_enabled_state(self) -> None:
        configuration = pattern_configuration(PatternKind.AURORA, COLOR, 35, 0.5)

        self.assertEqual(configuration.brightness_percent, 35)
        self.assertTrue(configuration.enabled)
        self.assertEqual(len(configuration.zones), RGB_ZONE_COUNT)

    def test_an_unknown_pattern_or_colour_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            pattern_zones("aurora", COLOR, 0.5)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            pattern_zones(PatternKind.AURORA, (0, 229, 255), 0.5)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
