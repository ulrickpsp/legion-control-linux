from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from legion_control.automation import (
    AutomationConfig,
    AutomationStore,
    PowerSourceAutomation,
    source_from_status,
)
from legion_control.scenes import SceneSlot


class AutomationTests(unittest.TestCase):
    def test_transition_applies_only_enabled_target_scene(self) -> None:
        controller = PowerSourceAutomation()
        configuration = AutomationConfig(
            ac_enabled=True,
            ac_scene=SceneSlot.GAME,
            battery_enabled=True,
            battery_scene=SceneSlot.SILENCE,
        )

        self.assertIsNone(controller.observe(_status("Charging"), configuration))
        self.assertEqual(
            controller.observe(_status("Discharging"), configuration),
            SceneSlot.SILENCE,
        )
        self.assertIsNone(controller.observe(_status("Discharging"), configuration))
        self.assertEqual(
            controller.observe(_status("Full"), configuration),
            SceneSlot.GAME,
        )

    def test_unknown_battery_status_never_triggers(self) -> None:
        self.assertIsNone(source_from_status(_status("Unknown")))

    def test_store_round_trip_is_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "automation.json"
            store = AutomationStore(path)
            configuration = AutomationConfig(ac_enabled=True, ac_scene=SceneSlot.GAME)

            store.save(configuration)

            self.assertEqual(store.load(), configuration)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


def _status(battery_status: str) -> dict[str, object]:
    return {"battery_status": battery_status}


if __name__ == "__main__":
    unittest.main()
