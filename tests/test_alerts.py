from __future__ import annotations

import unittest

from legion_control.alerts import ThermalAlertController, ThermalLevel


class ThermalAlertTests(unittest.TestCase):
    def test_alerts_on_escalation_then_rate_limits(self) -> None:
        controller = ThermalAlertController(cooldown_seconds=600)

        elevated = controller.observe(_status(83), timestamp=10)
        self.assertIsNotNone(elevated)
        assert elevated is not None
        self.assertEqual(elevated.level, ThermalLevel.ELEVATED)
        self.assertIsNone(controller.observe(_status(84), timestamp=20))

        critical = controller.observe(_status(93), timestamp=30)
        self.assertIsNotNone(critical)
        assert critical is not None
        self.assertEqual(critical.level, ThermalLevel.CRITICAL)

    def test_alert_can_notify_again_after_cooldown(self) -> None:
        controller = ThermalAlertController(cooldown_seconds=60)
        self.assertIsNotNone(controller.observe(_status(82), timestamp=10))
        self.assertIsNone(controller.observe(_status(82), timestamp=69))
        self.assertIsNotNone(controller.observe(_status(82), timestamp=70))


def _status(temperature_c: int) -> dict[str, object]:
    return {"cpu_temperature_c": temperature_c, "gpu_temperature_c": 50}


if __name__ == "__main__":
    unittest.main()
