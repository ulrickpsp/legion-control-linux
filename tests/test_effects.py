from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from legion_control.effects import (
    COLOR_AWARE_KINDS,
    FASTEST_CYCLE_SECONDS,
    SLOWEST_CYCLE_SECONDS,
    EffectConfigStore,
    EffectKind,
    EffectSettings,
    default_effect_settings,
    effect_frame,
    effect_settings_from_document,
    effect_settings_from_json,
    effect_settings_to_json,
    effect_zones,
)
from legion_control.rgb import RGB_ZONE_COUNT, RgbColor


def _settings(kind: EffectKind, **overrides: object) -> EffectSettings:
    values: dict[str, object] = {
        "kind": kind,
        "speed_percent": 50,
        "brightness_percent": 70,
        "color": RgbColor(229, 32, 47),
        "enabled": True,
    }
    values.update(overrides)
    return EffectSettings(**values)  # type: ignore[arg-type]


class EffectRenderingTests(unittest.TestCase):
    def test_every_effect_fills_all_twenty_four_zones(self) -> None:
        for kind in EffectKind:
            with self.subTest(effect=kind.value):
                zones = effect_zones(_settings(kind), 1.7)
                self.assertEqual(len(zones), RGB_ZONE_COUNT)
                self.assertTrue(all(isinstance(color, RgbColor) for color in zones))

    def test_rendering_is_deterministic(self) -> None:
        """A restarted daemon must resume the same animation, not a new one."""

        for kind in EffectKind:
            with self.subTest(effect=kind.value):
                settings = _settings(kind)
                self.assertEqual(
                    effect_zones(settings, 4.25),
                    effect_zones(settings, 4.25),
                )

    def test_animation_loops_over_its_cycle(self) -> None:
        for kind in EffectKind:
            with self.subTest(effect=kind.value):
                settings = _settings(kind)
                period = settings.cycle_seconds
                self.assertEqual(
                    effect_zones(settings, 0.4),
                    effect_zones(settings, 0.4 + period),
                )

    def test_frames_actually_change_over_time(self) -> None:
        """A still frame would be a static preset wearing an effect's name."""

        for kind in EffectKind:
            with self.subTest(effect=kind.value):
                settings = _settings(kind)
                quarter = settings.cycle_seconds / 4
                self.assertNotEqual(
                    effect_zones(settings, 0.0),
                    effect_zones(settings, quarter),
                )

    def test_only_colour_aware_effects_follow_the_chosen_colour(self) -> None:
        for kind in EffectKind:
            with self.subTest(effect=kind.value):
                red = effect_zones(_settings(kind, color=RgbColor(255, 0, 0)), 1.3)
                blue = effect_zones(_settings(kind, color=RgbColor(0, 0, 255)), 1.3)
                if kind in COLOR_AWARE_KINDS:
                    self.assertNotEqual(red, blue)
                else:
                    self.assertEqual(red, blue)

    def test_speed_maps_to_the_documented_cycle_bounds(self) -> None:
        self.assertAlmostEqual(
            _settings(EffectKind.WAVE, speed_percent=1).cycle_seconds, SLOWEST_CYCLE_SECONDS
        )
        self.assertAlmostEqual(
            _settings(EffectKind.WAVE, speed_percent=100).cycle_seconds,
            FASTEST_CYCLE_SECONDS,
        )
        self.assertLess(
            _settings(EffectKind.WAVE, speed_percent=90).cycle_seconds,
            _settings(EffectKind.WAVE, speed_percent=10).cycle_seconds,
        )

    def test_breathing_reaches_a_dim_floor_and_a_bright_peak(self) -> None:
        settings = _settings(EffectKind.BREATHING, color=RgbColor(255, 255, 255))
        floor = effect_zones(settings, 0.0)[0]
        peak = effect_zones(settings, settings.cycle_seconds / 2)[0]
        self.assertLess(floor.red, 40)
        self.assertGreater(peak.red, 240)

    def test_frame_carries_the_brightness_and_enabled_state(self) -> None:
        settings = _settings(EffectKind.AURORA, brightness_percent=35)
        frame = effect_frame(settings, 2.0)
        self.assertEqual(frame.brightness_percent, 35)
        self.assertTrue(frame.enabled)
        self.assertEqual(len(frame.zones), RGB_ZONE_COUNT)

    def test_negative_elapsed_time_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            effect_zones(_settings(EffectKind.FIRE), -0.1)


class EffectSettingsValidationTests(unittest.TestCase):
    def test_speed_and_brightness_stay_inside_their_range(self) -> None:
        for overrides in (
            {"speed_percent": 0},
            {"speed_percent": 101},
            {"brightness_percent": -1},
            {"brightness_percent": 101},
        ):
            with self.subTest(**overrides):
                with self.assertRaises(ValueError):
                    _settings(EffectKind.WAVE, **overrides)

    def test_non_integer_and_non_boolean_fields_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _settings(EffectKind.WAVE, speed_percent=True)
        with self.assertRaises(ValueError):
            _settings(EffectKind.WAVE, enabled=1)
        with self.assertRaises(ValueError):
            _settings(EffectKind.WAVE, color=(1, 2, 3))


class EffectSerializationTests(unittest.TestCase):
    def test_round_trip_preserves_every_field(self) -> None:
        settings = _settings(EffectKind.COMET, speed_percent=88, brightness_percent=15)
        self.assertEqual(effect_settings_from_json(effect_settings_to_json(settings)), settings)

    def test_unknown_effect_names_are_refused(self) -> None:
        payload = effect_settings_to_json(default_effect_settings())
        with self.assertRaises(ValueError):
            effect_settings_from_json(payload.replace('"rainbow"', '"firmware_wave"'))

    def test_documents_with_wrong_keys_are_refused(self) -> None:
        for document in (
            {"kind": "wave"},
            {
                "kind": "wave",
                "speed_percent": 50,
                "brightness_percent": 70,
                "color": {"red": 1, "green": 2, "blue": 3},
                "enabled": True,
                "extra": 1,
            },
        ):
            with self.subTest(document=document):
                with self.assertRaises(ValueError):
                    effect_settings_from_document(document)

    def test_oversized_payload_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            effect_settings_from_json(" " * 2048)

    def test_version_must_match(self) -> None:
        payload = effect_settings_to_json(default_effect_settings())
        with self.assertRaises(ValueError):
            effect_settings_from_json(payload.replace('"version":1', '"version":2'))


class EffectConfigStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.store = EffectConfigStore(Path(self.temporary.name) / "rgb-effect.json")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_missing_file_reads_as_no_effect(self) -> None:
        self.assertIsNone(self.store.load())

    def test_saved_settings_survive_a_reload(self) -> None:
        settings = _settings(EffectKind.FIRE, speed_percent=12)
        self.store.save(settings)
        self.assertEqual(self.store.load(), settings)

    def test_clear_removes_the_file_and_is_idempotent(self) -> None:
        self.store.save(default_effect_settings())
        self.store.clear()
        self.store.clear()
        self.assertIsNone(self.store.load())

    def test_oversized_file_is_refused_instead_of_parsed(self) -> None:
        self.store.path.parent.mkdir(parents=True, exist_ok=True)
        self.store.path.write_text("x" * 4096, encoding="utf-8")
        with self.assertRaises(ValueError):
            self.store.load()


if __name__ == "__main__":
    unittest.main()
