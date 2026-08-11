from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from legion_control.domain import FanTargets
from legion_control.linux import HardwareError, SysfsHardware, UnsupportedHardwareError
from legion_control.power import CustomPowerLimits
from tests.support import build_fake_sysfs


class IgnoredFan2TargetHardware(SysfsHardware):
    @staticmethod
    def _write_text(path: Path, value: str) -> None:
        if path.name == "fan2_target" and value != "0":
            return
        SysfsHardware._write_text(path, value)


class SysfsHardwareTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        build_fake_sysfs(self.root)
        self.hardware = SysfsHardware(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_discovers_exact_lenovo_drivers_and_capabilities(self) -> None:
        report = self.hardware.capabilities()
        self.assertTrue(report.supported)
        self.assertTrue(report.fan_control)
        self.assertEqual(report.fan_minimum_rpm, 1700)
        self.assertEqual(report.fan_maximum_rpm, 5300)
        self.assertIn("custom", report.platform_profiles)
        self.assertTrue(report.power_control)
        self.assertEqual(report.power_limits.sustained.default_w, 70)
        self.assertEqual(
            set(report.features),
            {"conservation_mode", "fn_lock", "camera_power"},
        )

    def test_reads_status_without_privileges(self) -> None:
        status = self.hardware.status()
        self.assertEqual(status.cpu_temperature_c, 61)
        self.assertEqual(status.gpu_temperature_c, None)
        self.assertEqual(status.fan1_rpm, 2100)
        self.assertEqual(status.battery_percent, 78)
        self.assertEqual(status.features["camera_power"], True)
        self.assertEqual(status.power_limits, CustomPowerLimits(60, 119))

    def test_writes_targets_then_restores_zero(self) -> None:
        self.hardware.set_fan_targets(FanTargets(2500, 2500))
        fan = self.root / "sys/class/hwmon/hwmon0"
        self.assertEqual((fan / "fan1_target").read_text(), "2500")
        self.assertEqual((fan / "fan2_target").read_text(), "2500")
        self.hardware.restore_firmware_control()
        self.assertEqual((fan / "fan1_target").read_text(), "0")
        self.assertEqual((fan / "fan2_target").read_text(), "0")

    def test_unconfirmed_target_restores_both_fans_and_fails(self) -> None:
        hardware = IgnoredFan2TargetHardware(self.root)
        fan = self.root / "sys/class/hwmon/hwmon0"

        with self.assertRaisesRegex(HardwareError, "no confirmó"):
            hardware.set_fan_targets(FanTargets(2500, 2500))

        self.assertEqual((fan / "fan1_target").read_text(), "0")
        self.assertEqual((fan / "fan2_target").read_text(), "0")

    def test_profile_uses_class_device_that_accepts_custom(self) -> None:
        self.hardware.set_profile("custom")
        profile = self.root / "sys/class/platform-profile/platform-profile-0/profile"
        self.assertEqual(profile.read_text(), "custom")

    def test_power_limits_require_custom_and_verify_both_values(self) -> None:
        self.assertEqual(
            self.hardware.current_power_limits(),
            CustomPowerLimits(60, 119),
        )
        with self.assertRaisesRegex(HardwareError, "Custom"):
            self.hardware.set_power_limits(CustomPowerLimits(70, 125))

        self.hardware.set_profile("custom")
        self.hardware.set_power_limits(CustomPowerLimits(70, 125))

        power = self.root / "sys/class/firmware-attributes/lenovo-wmi-other-0/attributes"
        self.assertEqual(
            (power / "ppt_pl1_spl/current_value").read_text(),
            "70",
        )
        self.assertEqual(
            (power / "ppt_pl2_sppt/current_value").read_text(),
            "125",
        )
        self.assertEqual(
            self.hardware.current_power_limits(),
            CustomPowerLimits(70, 125),
        )

    def test_feature_write_is_verified(self) -> None:
        self.hardware.set_feature("conservation_mode", True)
        path = self.root / "sys/bus/platform/devices/VPC2004:00/conservation_mode"
        self.assertEqual(path.read_text(), "1")

    def test_unsupported_product_blocks_mutation(self) -> None:
        (self.root / "sys/devices/virtual/dmi/id/product_name").write_text("OTHER")
        hardware = SysfsHardware(self.root)
        with self.assertRaises(UnsupportedHardwareError):
            hardware.set_profile("balanced")


if __name__ == "__main__":
    unittest.main()
