"""GTK page for a strictly read-only support report."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gtk  # noqa: E402

from legion_control.doctor import DoctorReport, DoctorSeverity, build_doctor_report  # noqa: E402
from legion_control.i18n import translate  # noqa: E402
from legion_control.ui_files import choose_save_path  # noqa: E402


class DoctorPage(Adw.PreferencesPage):
    def __init__(
        self,
        show_error: Callable[[str], None],
        show_message: Callable[[str], None],
    ) -> None:
        super().__init__()
        self.add_css_class("control-page")
        self.set_title("Doctor")
        self.set_icon_name("system-search-symbolic")
        self._show_error = show_error
        self._show_message = show_message
        self._report = DoctorReport(())
        self._values: dict[str, Gtk.Label] = {}

        overview = Adw.PreferencesGroup()
        overview.set_title("Diagnóstico solo lectura")
        overview.set_description("No solicita permisos ni modifica ventiladores, potencia o RGB")
        self._summary = Gtk.Label(label="Esperando lecturas")
        self._summary.add_css_class("status-pill")
        self._summary.set_halign(Gtk.Align.START)
        overview.add(self._summary)
        self.add(overview)

        results = Adw.PreferencesGroup()
        results.set_title("Informe")
        for key, title in (
            ("version", "Versión"),
            ("identity", "Equipo"),
            ("kernel", "Kernel"),
            ("fan_control", "Ventilación"),
            ("thermal", "Lecturas"),
            ("fan_service", "Servicio"),
            ("rgb", "RGB"),
        ):
            row = Adw.ActionRow()
            row.set_title(title)
            value = Gtk.Label(label="—", xalign=1)
            value.set_wrap(True)
            value.set_max_width_chars(48)
            # Claim the free width of the row so short values stay on one line.
            value.set_hexpand(True)
            value.add_css_class("measurement")
            row.add_suffix(value)
            results.add(row)
            self._values[key] = value
        self.add(results)

        actions = Adw.PreferencesGroup()
        actions.set_title("Compartir")
        copy = Gtk.Button(label="Copiar informe")
        copy.add_css_class("suggested-action")
        copy.connect("clicked", self._on_copy_clicked)
        save = Gtk.Button(label="Guardar informe")
        save.connect("clicked", self._on_save_clicked)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_halign(Gtk.Align.END)
        box.append(copy)
        box.append(save)
        actions.add(box)
        self.add(actions)

    def update_status(self, status: dict[str, object]) -> None:
        self._report = build_doctor_report(status)
        labels = {
            DoctorSeverity.OK: translate("Listo"),
            DoctorSeverity.WARNING: translate("Revisar"),
            DoctorSeverity.ERROR: translate("Atención"),
        }
        self._summary.set_label(labels[self._report.severity])
        for finding in self._report.findings:
            value = self._values.get(finding.key)
            if value is not None:
                value.set_label(finding.value)

    def _on_copy_clicked(self, _button: Gtk.Button) -> None:
        self.get_clipboard().set(self._report.to_text())
        self._show_message(translate("Informe Doctor copiado."))

    def _on_save_clicked(self, _button: Gtk.Button) -> None:
        choose_save_path(
            self,
            title=translate("Guardar informe Doctor"),
            suggested_name="legion-control-doctor.txt",
            on_path=self._save_to,
            on_error=self._show_error,
        )

    def _save_to(self, path: Path) -> None:
        try:
            path.write_text(self._report.to_text(), encoding="utf-8")
        except OSError as error:
            self._show_error(translate("No se guardó el informe: {error}", error=error))
            return
        self._show_message(translate("Informe Doctor guardado."))
