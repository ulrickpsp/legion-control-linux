from __future__ import annotations

import unittest

from legion_control import __version__
from legion_control.doctor import DoctorSeverity, build_doctor_report
from legion_control.i18n import translate


class DoctorReportTests(unittest.TestCase):
    def test_report_marks_supported_cool_hardware_as_ready(self) -> None:
        report = build_doctor_report(_status(), kernel_release="7.0.0-test")

        self.assertEqual(report.severity, DoctorSeverity.OK)
        self.assertIn("Kernel: 7.0.0-test", report.to_text())
        self.assertEqual(report.to_dict()["version"], 1)

    def test_report_flags_unsupported_hardware_and_critical_temperature(self) -> None:
        status = _status()
        capabilities = status["capabilities"]
        assert isinstance(capabilities, dict)
        capabilities["supported"] = False
        status["cpu_temperature_c"] = 96

        report = build_doctor_report(status, kernel_release="test")

        self.assertEqual(report.severity, DoctorSeverity.ERROR)
        severities = {item.key: item.severity for item in report.findings}
        self.assertEqual(severities["identity"], DoctorSeverity.ERROR)
        self.assertEqual(severities["thermal"], DoctorSeverity.ERROR)


def _status() -> dict[str, object]:
    return {
        "capabilities": {
            "product": "83LU",
            "product_version": "Legion Pro 5",
            "supported": True,
            "fan_control": True,
            "fan_minimum_rpm": 1700,
            "fan_maximum_rpm": 5300,
            "fan_step_rpm": 100,
            "rgb_control": True,
        },
        "cpu_temperature_c": 62,
        "gpu_temperature_c": 49,
        "fan1_rpm": 2100,
        "fan2_rpm": 2100,
        "fan_service_active": False,
    }


class DoctorEffectTests(unittest.TestCase):
    def test_a_running_effect_is_named_in_the_report(self) -> None:
        status = _status()
        status["rgb_effect_active"] = True
        status["rgb_effect"] = {"kind": "aurora", "speed_percent": 55}

        report = build_doctor_report(status, kernel_release="7.0.0-29-generic")

        effect = next(item for item in report.findings if item.key == "rgb_effect")
        self.assertIn("aurora", effect.value)
        self.assertIn("55", effect.value)

    def test_no_effect_reads_as_none(self) -> None:
        report = build_doctor_report(_status(), kernel_release="7.0.0-29-generic")

        # Another test may have left a different language active, so assert the
        # branch rather than the Spanish spelling of it.
        effect = next(item for item in report.findings if item.key == "rgb_effect")
        self.assertEqual(effect.value, translate("ninguno"))
        self.assertNotIn("aurora", effect.value)


if __name__ == "__main__":
    unittest.main()


class DoctorVersionTests(unittest.TestCase):
    """A support report has to say which build produced it."""

    def test_report_states_the_installed_version(self) -> None:
        report = build_doctor_report({}, kernel_release="7.0.0-test")

        version = next(item for item in report.findings if item.key == "version")

        self.assertIn(__version__, version.value)
        self.assertIn(__version__, report.to_text())
        self.assertIn(__version__, report.to_json())
