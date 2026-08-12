from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from legion_control.doctor import SystemProbe  # noqa: E402
from legion_control.history import TelemetryArchive  # noqa: E402
from legion_control.mock import MockControlClient  # noqa: E402
from legion_control.ui_doctor import DoctorPage  # noqa: E402
from legion_control.ui_files import _is_cancelled  # noqa: E402
from legion_control.ui_history import TelemetryHistoryPanel  # noqa: E402


def _stub_probe() -> SystemProbe:
    """Keep the export tests off the real filesystem and systemd."""

    return SystemProbe(
        helper_installed=True,
        polkit_action_installed=True,
        loaded_modules=("lenovo_wmi_gamezone", "lenovo_wmi_other"),
        fan_service_state="inactive",
        fan_service_enabled="disabled",
        bios_version="Q6CN79WW",
    )


class SaveDestinationTests(unittest.TestCase):
    """The export actions must reach disk instead of dying inside the handler."""

    @classmethod
    def setUpClass(cls) -> None:
        if Gdk.Display.get_default() is None:
            raise unittest.SkipTest(
                "Los tests GTK necesitan un display; usa un runner Wayland/X11 virtual."
            )
        Adw.init()

    def setUp(self) -> None:
        self.errors: list[str] = []
        self.messages: list[str] = []

    def test_doctor_report_is_written_to_the_chosen_path(self) -> None:
        page = DoctorPage(self.errors.append, self.messages.append, _stub_probe)
        page.update_status(MockControlClient().read_status())
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "doctor.txt"

            page._save_to(destination)

            self.assertIn("Legion Control Doctor", destination.read_text(encoding="utf-8"))
        self.assertEqual(self.errors, [])
        self.assertEqual(len(self.messages), 1)

    def test_doctor_report_reports_a_write_failure_instead_of_raising(self) -> None:
        page = DoctorPage(self.errors.append, self.messages.append, _stub_probe)
        page.update_status(MockControlClient().read_status())
        with TemporaryDirectory() as directory:
            page._save_to(Path(directory))

        self.assertEqual(self.messages, [])
        self.assertEqual(len(self.errors), 1)

    def test_doctor_report_reaches_the_clipboard(self) -> None:
        page = DoctorPage(self.errors.append, self.messages.append, _stub_probe)
        page.update_status(MockControlClient().read_status())

        page._on_copy_clicked(Gtk.Button())

        self.assertEqual(self.errors, [])
        self.assertEqual(len(self.messages), 1)

    def test_history_export_writes_a_csv_with_the_archived_samples(self) -> None:
        with TemporaryDirectory() as directory:
            archive = TelemetryArchive(Path(directory) / "telemetry.jsonl")
            archive.append_status(_status(50, 2000), timestamp=100)
            archive.append_status(_status(60, 2400), timestamp=200)
            panel = TelemetryHistoryPanel(archive, self.errors.append, self.messages.append)
            destination = Path(directory) / "telemetry.csv"

            panel._export_to(destination)

            content = destination.read_text(encoding="utf-8")
        self.assertIn("cpu_temperature_c", content)
        self.assertEqual(self.errors, [])
        self.assertEqual(len(self.messages), 1)

    def test_history_export_reports_a_write_failure_instead_of_raising(self) -> None:
        with TemporaryDirectory() as directory:
            archive = TelemetryArchive(Path(directory) / "telemetry.jsonl")
            panel = TelemetryHistoryPanel(archive, self.errors.append, self.messages.append)

            panel._export_to(Path(directory))

        self.assertEqual(self.messages, [])
        self.assertEqual(len(self.errors), 1)

    def test_a_dismissed_save_dialog_is_not_reported_as_an_error(self) -> None:
        dismissed = GLib.Error.new_literal(
            Gtk.dialog_error_quark(), "cancelled", int(Gtk.DialogError.DISMISSED)
        )
        failed = GLib.Error.new_literal(
            Gtk.dialog_error_quark(), "broken", int(Gtk.DialogError.FAILED)
        )

        self.assertTrue(_is_cancelled(dismissed))
        self.assertFalse(_is_cancelled(failed))


def _status(temperature_c: int, rpm: int) -> dict[str, object]:
    return {
        "cpu_temperature_c": temperature_c,
        "gpu_temperature_c": temperature_c - 5,
        "fan1_rpm": rpm,
        "fan2_rpm": rpm,
    }


if __name__ == "__main__":
    unittest.main()
