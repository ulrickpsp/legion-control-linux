"""GTK page for a strictly read-only support report."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from legion_control.doctor import (  # noqa: E402
    DoctorFinding,
    DoctorReport,
    DoctorSeverity,
    SystemProbe,
    build_doctor_report,
    probe_system,
)
from legion_control.i18n import translate  # noqa: E402
from legion_control.ui_files import choose_save_path  # noqa: E402
from legion_control.updates import (  # noqa: E402
    RELEASES_PAGE_URL,
    ReleaseFetcher,
    UpdateConfig,
    UpdateResult,
    UpdateState,
    UpdateStore,
    check_for_update,
    default_update_path,
)


SEVERITY_ICONS: dict[DoctorSeverity, str] = {
    DoctorSeverity.OK: "emblem-ok-symbolic",
    DoctorSeverity.WARNING: "dialog-warning-symbolic",
    DoctorSeverity.ERROR: "dialog-error-symbolic",
}
SEVERITY_TONES: dict[DoctorSeverity, str] = {
    DoctorSeverity.OK: "status-stable",
    DoctorSeverity.WARNING: "status-warm",
    DoctorSeverity.ERROR: "status-critical",
}


class DoctorPage(Adw.PreferencesPage):
    def __init__(
        self,
        show_error: Callable[[str], None],
        show_message: Callable[[str], None],
        probe_reader: Callable[[], SystemProbe] = probe_system,
        update_store: UpdateStore | None = None,
        fetch_version: ReleaseFetcher | None = None,
    ) -> None:
        super().__init__()
        self.add_css_class("control-page")
        self.set_title("Doctor")
        self.set_icon_name("system-search-symbolic")
        self._show_error = show_error
        self._show_message = show_message
        self._probe_reader = probe_reader
        self._report = DoctorReport(())
        self._rows: dict[str, tuple[Adw.ActionRow, Gtk.Image, Gtk.Label]] = {}
        # Installation and conflict state needs the filesystem and systemd, so
        # it is read once and on request instead of on every status poll.
        self._probe: SystemProbe | None = None
        self._update_store = update_store or UpdateStore(default_update_path())
        self._fetch_version = fetch_version
        self._update_configuration = UpdateConfig()
        self._update_in_flight = False
        self._releases_url = RELEASES_PAGE_URL

        overview = Adw.PreferencesGroup()
        overview.set_title("Diagnóstico solo lectura")
        overview.set_description("No solicita permisos ni modifica ventiladores, potencia o RGB")
        self._summary = Gtk.Label(label="Esperando lecturas")
        self._summary.add_css_class("status-pill")
        self._summary.set_halign(Gtk.Align.START)
        overview.add(self._summary)
        self.add(overview)

        self._results = Adw.PreferencesGroup()
        self._results.set_title("Informe")
        recheck = Gtk.Button(label=translate("Volver a comprobar"))
        recheck.connect("clicked", self._on_recheck_clicked)
        recheck.set_valign(Gtk.Align.CENTER)
        self._results.set_header_suffix(recheck)
        self.add(self._results)

        updates = Adw.PreferencesGroup()
        updates.set_title("Avisos de versión")
        updates.set_description("Desactivado por defecto · única conexión de red de la aplicación")
        self._update_switch = Adw.SwitchRow()
        self._update_switch.set_title("Avisar de nuevas versiones")
        self._update_switch.set_subtitle(
            "Consulta la página de publicaciones una vez al día. No descarga ni instala nada"
        )
        updates.add(self._update_switch)
        self._update_row = Adw.ActionRow()
        self._update_row.set_title("Estado")
        self._update_value = Gtk.Label(label="—", xalign=1)
        self._update_value.add_css_class("measurement")
        self._update_row.add_suffix(self._update_value)
        self._releases_button = Gtk.Button(label=translate("Ver publicaciones"))
        self._releases_button.set_valign(Gtk.Align.CENTER)
        self._releases_button.connect("clicked", self._on_releases_clicked)
        self._releases_button.set_visible(False)
        self._update_row.add_suffix(self._releases_button)
        updates.add(self._update_row)
        self.add(updates)
        self._load_update_configuration()
        self._update_switch.connect("notify::active", self._on_update_switch_changed)

        actions = Adw.PreferencesGroup()
        actions.set_title("Compartir")
        copy = Gtk.Button(label="Copiar informe")
        copy.add_css_class("suggested-action")
        copy.connect("clicked", self._on_copy_clicked)
        copy_json = Gtk.Button(label="Copiar JSON")
        copy_json.connect("clicked", self._on_copy_json_clicked)
        save = Gtk.Button(label="Guardar informe")
        save.connect("clicked", self._on_save_clicked)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_halign(Gtk.Align.END)
        box.append(copy)
        box.append(copy_json)
        box.append(save)
        actions.add(box)
        self.add(actions)

    def update_status(self, status: dict[str, object]) -> None:
        if self._probe is None:
            self._probe = self._read_probe()
        self._report = build_doctor_report(status, probe=self._probe)
        labels = {
            DoctorSeverity.OK: translate("Listo"),
            DoctorSeverity.WARNING: translate("Revisar"),
            DoctorSeverity.ERROR: translate("Atención"),
        }
        severity = self._report.severity
        self._summary.set_label(labels[severity])
        _set_tone(self._summary, SEVERITY_TONES[severity])
        for finding in self._report.findings:
            self._apply_finding(finding)

    def _read_probe(self) -> SystemProbe:
        try:
            return self._probe_reader()
        except OSError as error:
            # A diagnosis that crashes the page helps nobody; report and degrade.
            self._show_error(translate("No se pudo inspeccionar el sistema: {error}", error=error))
            return SystemProbe()

    def _apply_finding(self, finding: DoctorFinding) -> None:
        entry = self._rows.get(finding.key)
        if entry is None:
            entry = self._add_row(finding)
        row, icon, value = entry
        value.set_label(finding.value)
        icon.set_from_icon_name(SEVERITY_ICONS[finding.severity])
        _set_tone(icon, SEVERITY_TONES[finding.severity])
        # An acceptable reading needs no instructions underneath it.
        row.set_subtitle(finding.remedy if finding.severity is not DoctorSeverity.OK else "")

    def _add_row(self, finding: DoctorFinding) -> tuple[Adw.ActionRow, Gtk.Image, Gtk.Label]:
        row = Adw.ActionRow()
        row.set_title(finding.title)
        row.set_subtitle_lines(3)
        icon = Gtk.Image.new_from_icon_name(SEVERITY_ICONS[finding.severity])
        icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        row.add_prefix(icon)
        value = Gtk.Label(label="—", xalign=1)
        value.set_wrap(True)
        value.set_max_width_chars(48)
        # Claim the free width of the row so short values stay on one line.
        value.set_hexpand(True)
        value.add_css_class("measurement")
        row.add_suffix(value)
        self._results.add(row)
        entry = (row, icon, value)
        self._rows[finding.key] = entry
        return entry

    def _on_recheck_clicked(self, _button: Gtk.Button) -> None:
        self._probe = self._read_probe()
        self._start_update_check()
        self._show_message(translate("Comprobaciones actualizadas."))

    def _load_update_configuration(self) -> None:
        try:
            self._update_configuration = self._update_store.load()
        except (OSError, ValueError) as error:
            self._show_error(translate("No se cargó el aviso de versión: {error}", error=error))
            self._update_configuration = UpdateConfig()
        self._update_switch.set_active(self._update_configuration.enabled)
        self._apply_update_result(UpdateResult(UpdateState.DISABLED))
        self._start_update_check()

    def _on_update_switch_changed(self, row: Adw.SwitchRow, _parameter: object) -> None:
        configuration = replace(self._update_configuration, enabled=row.get_active())
        try:
            self._update_store.save(configuration)
        except (OSError, ValueError) as error:
            self._show_error(translate("No se guardó el aviso de versión: {error}", error=error))
            return
        self._update_configuration = configuration
        if configuration.enabled:
            self._start_update_check()
        else:
            # Turning it off must also stop reporting what the last check saw.
            self._apply_update_result(UpdateResult(UpdateState.DISABLED))

    def _start_update_check(self) -> None:
        if self._update_in_flight or not self._update_configuration.enabled:
            return
        self._update_in_flight = True
        self._update_value.set_label(translate("consultando"))
        configuration = self._update_configuration
        fetch = self._fetch_version

        def execute() -> None:
            try:
                result, updated = check_for_update(configuration, fetch=fetch)
            except Exception:
                # A version notice may never be a reason to lose the window.
                result, updated = UpdateResult(UpdateState.UNKNOWN), configuration
            GLib.idle_add(self._finish_update_check, result, updated)

        threading.Thread(target=execute, daemon=True, name="release-notice").start()

    def _finish_update_check(self, result: UpdateResult, updated: UpdateConfig) -> bool:
        self._update_in_flight = False
        if updated != self._update_configuration:
            self._update_configuration = updated
            try:
                self._update_store.save(updated)
            except (OSError, ValueError) as error:
                self._show_error(
                    translate("No se guardó el aviso de versión: {error}", error=error)
                )
        self._apply_update_result(result)
        return GLib.SOURCE_REMOVE

    def _apply_update_result(self, result: UpdateResult) -> None:
        self._releases_url = result.url
        if result.state is UpdateState.AVAILABLE:
            self._update_value.set_label(
                translate("{version} disponible", version=result.latest_version)
            )
        elif result.state is UpdateState.CURRENT:
            self._update_value.set_label(translate("al día"))
        elif result.state is UpdateState.UNKNOWN:
            self._update_value.set_label(translate("no se pudo consultar"))
        else:
            self._update_value.set_label(translate("desactivado"))
        self._releases_button.set_visible(result.state is UpdateState.AVAILABLE)

    def _on_releases_clicked(self, _button: Gtk.Button) -> None:
        # Opening the page is the whole action: nothing is downloaded or run.
        launcher = Gtk.UriLauncher.new(self._releases_url)
        launcher.launch(self.get_root(), None, None)

    def _on_copy_clicked(self, _button: Gtk.Button) -> None:
        self.get_clipboard().set(self._report.to_text())
        self._show_message(translate("Informe Doctor copiado."))

    def _on_copy_json_clicked(self, _button: Gtk.Button) -> None:
        self.get_clipboard().set(self._report.to_json())
        self._show_message(translate("Informe Doctor copiado en JSON."))

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


def _set_tone(widget: Gtk.Widget, tone: str) -> None:
    for css_class in ("status-stable", "status-warm", "status-critical"):
        widget.remove_css_class(css_class)
    widget.add_css_class(tone)
