from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from legion_control import __version__
from legion_control.doctor import (
    DOCTOR_REPORT_VERSION,
    VALIDATED_BIOS_VERSION,
    DoctorSeverity,
    SystemProbe,
    build_doctor_report,
    probe_system,
)


class DoctorReportTests(unittest.TestCase):
    def test_report_marks_supported_cool_hardware_as_ready(self) -> None:
        report = build_doctor_report(_status(), kernel_release="7.0.0-test")

        self.assertEqual(report.severity, DoctorSeverity.OK)
        self.assertIn("Kernel: 7.0.0-test", report.to_text())
        self.assertEqual(report.to_dict()["version"], DOCTOR_REPORT_VERSION)

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

    def test_environment_checks_are_absent_without_a_probe(self) -> None:
        """A status poll must not pay for filesystem and systemd reads."""

        report = build_doctor_report(_status(), kernel_release="test")

        keys = {item.key for item in report.findings}
        self.assertNotIn("privileges", keys)
        self.assertNotIn("profile_conflict", keys)


class EnvironmentFindingTests(unittest.TestCase):
    def test_healthy_installation_adds_checks_without_raising_severity(self) -> None:
        report = build_doctor_report(_status(), kernel_release="test", probe=_probe())

        self.assertEqual(report.severity, DoctorSeverity.OK)
        keys = [item.key for item in report.findings]
        self.assertIn("bios", keys)
        self.assertIn("modules", keys)
        self.assertIn("privileges", keys)
        self.assertIn("profile_conflict", keys)
        self.assertIn("rgb_conflict", keys)

    def test_missing_helper_is_an_error_because_no_write_can_land(self) -> None:
        report = build_doctor_report(
            _status(),
            kernel_release="test",
            probe=_probe(helper_installed=False),
        )

        finding = _finding(report, "privileges")
        self.assertEqual(finding.severity, DoctorSeverity.ERROR)
        self.assertIn("legion-control-helper", finding.value)
        self.assertTrue(finding.remedy)

    def test_a_competing_profile_daemon_is_reported(self) -> None:
        report = build_doctor_report(
            _status(),
            kernel_release="test",
            probe=_probe(active_profile_competitors=("power-profiles-daemon.service",)),
        )

        finding = _finding(report, "profile_conflict")
        self.assertEqual(finding.severity, DoctorSeverity.WARNING)
        self.assertIn("power-profiles-daemon.service", finding.value)

    def test_a_competing_out_of_tree_driver_counts_as_a_profile_conflict(self) -> None:
        report = build_doctor_report(
            _status(),
            kernel_release="test",
            probe=_probe(competing_modules=("legion_laptop",)),
        )

        self.assertIn("legion_laptop", _finding(report, "profile_conflict").value)

    def test_a_failed_fan_service_is_an_error_rather_than_firmware_control(self) -> None:
        report = build_doctor_report(
            _status(),
            kernel_release="test",
            probe=_probe(fan_service_state="failed"),
        )

        finding = _finding(report, "fan_service")
        self.assertEqual(finding.severity, DoctorSeverity.ERROR)
        self.assertIn("legion-control-fand.service", finding.remedy)

    def test_missing_kernel_modules_are_named(self) -> None:
        report = build_doctor_report(
            _status(),
            kernel_release="test",
            probe=_probe(loaded_modules=("lenovo_wmi_gamezone",)),
        )

        finding = _finding(report, "modules")
        self.assertEqual(finding.severity, DoctorSeverity.WARNING)
        self.assertIn("lenovo_wmi_other", finding.value)

    def test_a_newer_published_release_is_reported_next_to_the_installed_one(self) -> None:
        report = build_doctor_report(
            _status(),
            kernel_release="test",
            probe=_probe(available_version="99.0.0"),
        )

        finding = _finding(report, "version")
        self.assertEqual(finding.severity, DoctorSeverity.WARNING)
        self.assertIn("99.0.0", finding.value)
        self.assertIn(__version__, finding.value)
        self.assertTrue(finding.remedy)

    def test_the_installed_release_alone_is_not_a_finding(self) -> None:
        report = build_doctor_report(
            _status(),
            kernel_release="test",
            probe=_probe(available_version=__version__),
        )

        self.assertEqual(_finding(report, "version").severity, DoctorSeverity.OK)

    def test_an_unvalidated_bios_warns_but_only_on_supported_hardware(self) -> None:
        report = build_doctor_report(
            _status(),
            kernel_release="test",
            probe=_probe(bios_version="Q6CN01WW"),
        )

        self.assertEqual(_finding(report, "bios").severity, DoctorSeverity.WARNING)

    def test_the_exported_text_carries_the_remedy_for_every_problem(self) -> None:
        report = build_doctor_report(
            _status(),
            kernel_release="test",
            probe=_probe(helper_installed=False),
        )

        text = report.to_text()

        self.assertIn("[ERROR]", text)
        self.assertIn("    → ", text)
        remedies = {item["key"]: item["remedy"] for item in report.to_dict()["findings"]}
        self.assertTrue(remedies["privileges"])


class SystemProbeTests(unittest.TestCase):
    """The probe reads a filesystem root and systemd, and never writes."""

    def test_probe_reads_installation_state_from_the_given_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _touch(root / "usr/libexec/legion-control-helper")
            _touch(root / "usr/share/polkit-1/actions/io.github.ulrickpsp.policy")
            _touch(root / "sys/devices/virtual/dmi/id/bios_version", VALIDATED_BIOS_VERSION)
            (root / "sys/module/lenovo_wmi_other").mkdir(parents=True)

            probe = probe_system(root=root, run_systemctl=_fake_systemctl)

        self.assertTrue(probe.helper_installed)
        self.assertTrue(probe.polkit_action_installed)
        self.assertEqual(probe.bios_version, VALIDATED_BIOS_VERSION)
        self.assertEqual(probe.loaded_modules, ("lenovo_wmi_other",))
        self.assertEqual(probe.competing_modules, ())
        self.assertEqual(probe.fan_service_state, "inactive")
        self.assertEqual(probe.active_profile_competitors, ("power-profiles-daemon.service",))
        self.assertEqual(probe.active_rgb_competitors, ())

    def test_probe_reports_unknown_state_when_nothing_is_installed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            probe = probe_system(
                root=Path(directory),
                run_systemctl=lambda _command, units: tuple("unknown" for _ in units),
            )

        self.assertFalse(probe.helper_installed)
        self.assertIsNone(probe.bios_version)
        self.assertEqual(probe.fan_service_state, "unknown")

        report = build_doctor_report(_status(), kernel_release="test", probe=probe)
        self.assertEqual(_finding(report, "fan_service").severity, DoctorSeverity.WARNING)


class DoctorVersionTests(unittest.TestCase):
    """A support report has to say which build produced it."""

    def test_report_states_the_installed_version(self) -> None:
        report = build_doctor_report({}, kernel_release="7.0.0-test")

        version = next(item for item in report.findings if item.key == "version")

        self.assertIn(__version__, version.value)
        self.assertIn(__version__, report.to_text())
        self.assertIn(__version__, report.to_json())


def _fake_systemctl(command: str, units: tuple[str, ...]) -> tuple[str, ...]:
    if command == "is-enabled":
        return tuple("disabled" for _ in units)
    active = {"power-profiles-daemon.service"}
    return tuple("active" if unit in active else "inactive" for unit in units)


def _probe(**overrides: object) -> SystemProbe:
    defaults: dict[str, object] = {
        "helper_installed": True,
        "polkit_action_installed": True,
        "loaded_modules": ("lenovo_wmi_gamezone", "lenovo_wmi_other"),
        "competing_modules": (),
        "fan_service_state": "inactive",
        "fan_service_enabled": "disabled",
        "active_profile_competitors": (),
        "active_rgb_competitors": (),
        "bios_version": VALIDATED_BIOS_VERSION,
    }
    return SystemProbe(**(defaults | overrides))  # type: ignore[arg-type]


def _finding(report: object, key: str):
    assert hasattr(report, "findings")
    return next(item for item in report.findings if item.key == key)


def _touch(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


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


if __name__ == "__main__":
    unittest.main()
