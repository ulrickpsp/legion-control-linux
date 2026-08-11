from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from legion_control.config import ConfigStore
from legion_control.daemon import FanDaemon
from legion_control.domain import (
    DEFAULT_CURVE,
    FanBounds,
    FanMode,
    FanPolicy,
    FanTargets,
    ThermalSnapshot,
)
from legion_control.linux import HardwareError


class FakeDaemonHardware:
    def __init__(self) -> None:
        self.daemon: FanDaemon | None = None
        self.targets: list[FanTargets] = []
        self.restore_count = 0
        self.profile = "custom"
        self.events: list[object] = []

    def require_supported(self) -> None:
        return None

    def fan_bounds(self) -> FanBounds:
        return FanBounds(1700, 5300, 100)

    def current_profile(self) -> str:
        return self.profile

    def set_profile(self, profile: str) -> None:
        self.events.append(("profile", profile))
        self.profile = profile

    def thermal_snapshot(self) -> ThermalSnapshot:
        return ThermalSnapshot(65, 55, 2100, 2100)

    def set_fan_targets(self, targets: FanTargets) -> None:
        self.events.append(("targets", targets))
        self.targets.append(targets)
        assert self.daemon is not None
        self.daemon.request_stop(15, None)

    def restore_firmware_control(self) -> None:
        self.restore_count += 1


class SnapshotDaemonHardware(FakeDaemonHardware):
    def __init__(self, snapshot: ThermalSnapshot) -> None:
        super().__init__()
        self.snapshot = snapshot

    def thermal_snapshot(self) -> ThermalSnapshot:
        return self.snapshot


class FailingWriteHardware(FakeDaemonHardware):
    def set_fan_targets(self, targets: FanTargets) -> None:
        self.targets.append(targets)
        raise HardwareError("fallo simulado escribiendo objetivos")


class FailingRestoreHardware(FakeDaemonHardware):
    def restore_firmware_control(self) -> None:
        self.restore_count += 1
        raise HardwareError("fallo simulado restaurando firmware")


class FanDaemonTests(unittest.TestCase):
    @staticmethod
    def _curve_store(directory: str) -> ConfigStore:
        store = ConfigStore(Path(directory) / "fan-config.json")
        store.save(FanPolicy(FanMode.CURVE, 2500, DEFAULT_CURVE))
        return store

    def test_curve_cycle_applies_target_and_always_restores(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "fan-config.json")
            store.save(FanPolicy(FanMode.CURVE, 2500, DEFAULT_CURVE))
            hardware = FakeDaemonHardware()
            daemon = FanDaemon(hardware, store)
            hardware.daemon = daemon
            self.assertEqual(daemon.run(), 0)
            self.assertEqual(hardware.targets, [FanTargets(2900, 2900)])
            self.assertEqual(hardware.restore_count, 1)

    def test_restart_reasserts_custom_before_first_manual_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hardware = FakeDaemonHardware()
            hardware.profile = "balanced"
            daemon = FanDaemon(hardware, self._curve_store(directory))
            hardware.daemon = daemon

            self.assertEqual(daemon.run(), 0)

            self.assertEqual(
                hardware.events[:2],
                [
                    ("profile", "custom"),
                    ("targets", FanTargets(2900, 2900)),
                ],
            )

    def test_auto_configuration_exits_and_restores(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "fan-config.json")
            store.save(FanPolicy(FanMode.AUTO, 2500, DEFAULT_CURVE))
            hardware = FakeDaemonHardware()
            daemon = FanDaemon(hardware, store)
            hardware.daemon = daemon
            self.assertEqual(daemon.run(), 0)
            self.assertEqual(hardware.targets, [])
            self.assertEqual(hardware.restore_count, 1)

    def test_critical_temperature_returns_three_without_writing_and_restores(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hardware = SnapshotDaemonHardware(ThermalSnapshot(98, 72, 3100, 3100))
            daemon = FanDaemon(hardware, self._curve_store(directory))

            self.assertEqual(daemon.run(), 3)

            self.assertEqual(hardware.targets, [])
            self.assertEqual(hardware.restore_count, 1)

    def test_missing_temperature_returns_three_without_writing_and_restores(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hardware = SnapshotDaemonHardware(ThermalSnapshot(None, None, 2100, 2100))
            daemon = FanDaemon(hardware, self._curve_store(directory))

            self.assertEqual(daemon.run(), 3)

            self.assertEqual(hardware.targets, [])
            self.assertEqual(hardware.restore_count, 1)

    def test_target_write_error_propagates_after_restoring_firmware(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hardware = FailingWriteHardware()
            daemon = FanDaemon(hardware, self._curve_store(directory))

            with self.assertRaisesRegex(HardwareError, "objetivos"):
                daemon.run()

            self.assertEqual(hardware.targets, [FanTargets(2900, 2900)])
            self.assertEqual(hardware.restore_count, 1)

    def test_invalid_persisted_policy_propagates_after_restoring_firmware(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "fan-config.json")
            store.path.write_text("{no es json}\n", encoding="utf-8")
            hardware = FakeDaemonHardware()
            daemon = FanDaemon(hardware, store)

            with self.assertRaisesRegex(ValueError, "JSON inválido"):
                daemon.run()

            self.assertEqual(hardware.targets, [])
            self.assertEqual(hardware.restore_count, 1)

    def test_restore_hardware_error_does_not_mask_successful_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "fan-config.json")
            store.save(FanPolicy(FanMode.AUTO, 2500, DEFAULT_CURVE))
            hardware = FailingRestoreHardware()
            daemon = FanDaemon(hardware, store)

            self.assertEqual(daemon.run(), 0)
            self.assertEqual(hardware.restore_count, 1)


if __name__ == "__main__":
    unittest.main()
