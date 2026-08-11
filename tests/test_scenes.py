from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from legion_control.domain import DEFAULT_CURVE, FanMode
from legion_control.power import CustomPowerLimits
from legion_control.rgb import RgbColor, solid_rgb_configuration
from legion_control.scenes import (
    Scene,
    SceneSlot,
    SceneStore,
    default_scenes,
)


class SceneStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "scenes.json"
        self.store = SceneStore(self.path)
        self.power_limits = CustomPowerLimits(70, 125)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_defaults_cover_silence_work_and_game(self) -> None:
        scenes = default_scenes(self.power_limits)
        self.assertEqual(set(scenes), set(SceneSlot))
        self.assertEqual(scenes[SceneSlot.SILENCE].profile, "low-power")
        self.assertEqual(scenes[SceneSlot.WORK].profile, "balanced")
        self.assertEqual(scenes[SceneSlot.GAME].fan_policy.mode, FanMode.CURVE)
        self.assertEqual(scenes[SceneSlot.GAME].fan_policy.curve, DEFAULT_CURVE)

    def test_saves_and_loads_one_replaced_scene(self) -> None:
        scenes = default_scenes(self.power_limits)
        custom = Scene(
            slot=SceneSlot.WORK,
            profile="performance",
            fan_policy=scenes[SceneSlot.WORK].fan_policy,
            power_limits=None,
            rgb_configuration=solid_rgb_configuration(RgbColor(10, 20, 30), 40),
        )
        scenes[SceneSlot.WORK] = custom

        self.store.save(scenes)

        self.assertEqual(self.store.load(), scenes)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_rejects_unknown_scene_keys(self) -> None:
        self.path.write_text(
            '{"version":1,"scenes":[],"command":"sh"}',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "claves"):
            self.store.load()


if __name__ == "__main__":
    unittest.main()
