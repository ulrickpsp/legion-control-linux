from __future__ import annotations

import unittest

from legion_control.tray import _tooltip_from_status


class TrayTooltipTests(unittest.TestCase):
    def test_includes_available_live_measurements(self) -> None:
        tooltip = _tooltip_from_status(
            {"cpu_temperature_c": 62, "gpu_temperature_c": 49, "battery_percent": 78}
        )
        self.assertEqual(tooltip, "CPU 62 °C · GPU 49 °C · Batería 78%")

    def test_uses_app_name_when_no_measurement_is_available(self) -> None:
        self.assertEqual(_tooltip_from_status({}), "Legion Control")


if __name__ == "__main__":
    unittest.main()
