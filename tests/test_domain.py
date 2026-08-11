from __future__ import annotations

import unittest

from legion_control.domain import (
    DEFAULT_CURVE,
    CriticalTemperatureError,
    CurvePoint,
    DomainError,
    FanBounds,
    FanController,
    FanCurve,
    FanMode,
    FanPolicy,
    FanTargets,
    TemperatureUnavailableError,
    ThermalSnapshot,
)


class FanCurveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bounds = FanBounds(1700, 5300, 100)

    def test_interpolates_and_quantizes_intermediate_temperature(self) -> None:
        self.assertEqual(DEFAULT_CURVE.target_at(70, self.bounds), 3200)

    def test_clamps_outside_curve_to_endpoints(self) -> None:
        self.assertEqual(DEFAULT_CURVE.target_at(30, self.bounds), 1700)
        self.assertEqual(DEFAULT_CURVE.target_at(95, self.bounds), 5300)

    def test_rejects_decreasing_rpm(self) -> None:
        with self.assertRaisesRegex(DomainError, "no pueden bajar"):
            FanCurve((CurvePoint(40, 2500), CurvePoint(60, 2000)))

    def test_rejects_duplicate_temperature(self) -> None:
        with self.assertRaisesRegex(DomainError, "sin repetirse"):
            FanCurve((CurvePoint(40, 2000), CurvePoint(40, 2500)))

    def test_rejects_target_outside_detected_bounds(self) -> None:
        curve = FanCurve((CurvePoint(40, 1600), CurvePoint(60, 2500)))
        with self.assertRaisesRegex(DomainError, "fuera"):
            curve.validate_for(self.bounds)


class FanPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bounds = FanBounds(1700, 5300, 100)
        self.policy = FanPolicy(FanMode.CURVE, 2500, DEFAULT_CURVE)

    def test_forces_maximum_at_emergency_temperature(self) -> None:
        self.assertEqual(self.policy.target_for(92, self.bounds), 5300)

    def test_returns_firmware_control_at_critical_temperature(self) -> None:
        with self.assertRaises(CriticalTemperatureError):
            self.policy.target_for(98, self.bounds)

    def test_auto_mode_returns_no_manual_target(self) -> None:
        policy = FanPolicy(FanMode.AUTO, 2500, DEFAULT_CURVE)
        self.assertIsNone(policy.target_for(60, self.bounds))

    def test_single_hot_sample_is_filtered_after_stable_readings(self) -> None:
        controller = FanController(self.policy, self.bounds)
        for _ in range(3):
            stable = controller.next_targets(_snapshot(60))

        spike = controller.next_targets(_snapshot(80))

        self.assertEqual(stable, FanTargets(2500, 2500))
        self.assertEqual(spike, stable)

    def test_two_hot_samples_raise_target_without_downward_delay(self) -> None:
        controller = FanController(self.policy, self.bounds)
        for _ in range(3):
            controller.next_targets(_snapshot(60))

        first_spike = controller.next_targets(_snapshot(80))
        second_spike = controller.next_targets(_snapshot(80))

        self.assertEqual(first_spike, FanTargets(2500, 2500))
        self.assertEqual(second_spike, FanTargets(4100, 4100))

    def test_cooling_requires_confirmation_and_descends_gradually(self) -> None:
        controller = FanController(self.policy, self.bounds)
        hot = controller.next_targets(_snapshot(80))
        held = [controller.next_targets(_snapshot(70)) for _ in range(3)]
        first_drop = controller.next_targets(_snapshot(70))

        self.assertEqual(hot, FanTargets(4100, 4100))
        self.assertEqual(held, [hot, hot, hot])
        self.assertEqual(first_drop, FanTargets(3800, 3800))

    def test_emergency_temperature_bypasses_filter(self) -> None:
        controller = FanController(self.policy, self.bounds)
        for _ in range(3):
            controller.next_targets(_snapshot(60))

        emergency = controller.next_targets(_snapshot(92))

        self.assertEqual(emergency, FanTargets(5300, 5300))

    def test_missing_temperatures_never_apply_manual_target(self) -> None:
        controller = FanController(self.policy, self.bounds)
        with self.assertRaises(TemperatureUnavailableError):
            controller.next_targets(ThermalSnapshot(None, None, 2100, 2100))


def _snapshot(temperature: int) -> ThermalSnapshot:
    return ThermalSnapshot(temperature, temperature - 10, 2100, 2100)


if __name__ == "__main__":
    unittest.main()
