from __future__ import annotations

import unittest

from legion_control.history import TelemetryHistory


class TelemetryHistoryTests(unittest.TestCase):
    def test_keeps_only_the_requested_time_window(self) -> None:
        history = TelemetryHistory(max_age_seconds=600)
        history.append_status(_status(50, 2000), timestamp=100)
        history.append_status(_status(60, 3000), timestamp=500)
        history.append_status(_status(70, 4000), timestamp=701)

        samples = history.samples

        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[0].cpu_temperature_c, 60)
        self.assertEqual(samples[-1].fan1_rpm, 4000)

    def test_ignores_status_without_thermal_or_fan_values(self) -> None:
        history = TelemetryHistory(max_age_seconds=600)
        history.append_status({}, timestamp=100)
        self.assertEqual(history.samples, ())


def _status(temperature_c: int, rpm: int) -> dict[str, object]:
    return {
        "cpu_temperature_c": temperature_c,
        "gpu_temperature_c": temperature_c - 5,
        "fan1_rpm": rpm,
        "fan2_rpm": rpm,
    }


if __name__ == "__main__":
    unittest.main()
