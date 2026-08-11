"""Native GTK4/libadwaita interface for Legion Control."""

from __future__ import annotations

import math
import os
import threading
from collections.abc import Callable
from typing import Any, Final

import cairo  # Registers cairo.Context for PyGObject drawing callbacks.
import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
gi.require_foreign("cairo")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from legion_control.client import ControlPort, LocalControlClient  # noqa: E402
from legion_control.domain import (  # noqa: E402
    DEFAULT_CURVE,
    CurvePoint,
    DomainError,
    FanBounds,
    FanCurve,
    FanMode,
    FanPolicy,
)
from legion_control.linux import SysfsHardware  # noqa: E402
from legion_control.mock import MockControlClient  # noqa: E402
from legion_control.power import (  # noqa: E402
    CustomPowerLimits,
    PowerLimitBounds,
    PowerLimitCapabilities,
)
from legion_control.scenes import SceneStore, default_scene_path  # noqa: E402
from legion_control.ui_history import TelemetryHistoryPanel  # noqa: E402
from legion_control.ui_lighting import LightingPage  # noqa: E402
from legion_control.ui_scenes import ScenePanel  # noqa: E402
from legion_control.ui_style import install_css  # noqa: E402


APPLICATION_ID: Final = "io.github.ulrickpsp.LegionControl"
REFRESH_INTERVAL_MS: Final = 2500
PROFILE_VALUES: Final = (
    "low-power",
    "balanced",
    "performance",
    "max-power",
    "custom",
)
PROFILE_LABELS: Final = (
    "Silencioso",
    "Equilibrado",
    "Rendimiento",
    "Rendimiento máximo",
    "Personalizado",
)
MODE_VALUES: Final = (FanMode.AUTO, FanMode.FIXED, FanMode.CURVE)
MODE_LABELS: Final = ("Automático", "RPM fija", "Curva")

Operation = Callable[[], dict[str, object]]
MutationRunner = Callable[
    [Operation, str, Callable[[], None] | None, Callable[[], None] | None], None
]


def _value_row(title: str, subtitle: str = "") -> tuple[Adw.ActionRow, Gtk.Label]:
    row = Adw.ActionRow()
    row.set_title(title)
    if subtitle:
        row.set_subtitle(subtitle)
    value = Gtk.Label(label="—")
    value.add_css_class("measurement")
    value.set_valign(Gtk.Align.CENTER)
    value.set_accessible_role(Gtk.AccessibleRole.STATUS)
    row.add_suffix(value)
    return row, value


def _spin_with_unit(spin: Gtk.SpinButton, unit_text: str) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    box.append(spin)
    unit = Gtk.Label(label=unit_text)
    unit.add_css_class("dim-label")
    box.append(unit)
    return box


def _prefix_icon(icon_name: str, accessible_label: str) -> Gtk.Image:
    icon = Gtk.Image.new_from_icon_name(icon_name)
    icon.set_pixel_size(20)
    icon.set_tooltip_text(accessible_label)
    icon.add_css_class("row-icon")
    return icon


def _metric(
    title: str,
    *,
    primary: bool = False,
) -> tuple[Gtk.Box, Gtk.Label]:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    box.add_css_class("metric")
    title_label = Gtk.Label(label=title, xalign=0)
    title_label.add_css_class("metric-title")
    value = Gtk.Label(label="—", xalign=0)
    value.add_css_class("metric-value-primary" if primary else "metric-value")
    value.set_accessible_role(Gtk.AccessibleRole.STATUS)
    box.append(title_label)
    box.append(value)
    return box, value


def _status_pill() -> tuple[Gtk.Box, Gtk.Label, Gtk.Image]:
    pill = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    pill.add_css_class("status-pill")
    icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
    icon.set_pixel_size(16)
    label = Gtk.Label(label="Estado estable")
    pill.append(icon)
    pill.append(label)
    return pill, label, icon


def _set_status_tone(widget: Gtk.Widget, tone: str) -> None:
    for css_class in ("status-stable", "status-warm", "status-critical"):
        widget.remove_css_class(css_class)
    widget.add_css_class(tone)


def _button_content(label: str, icon_name: str) -> Gtk.Box:
    content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
    content.set_halign(Gtk.Align.CENTER)
    icon = Gtk.Image.new_from_icon_name(icon_name)
    icon.set_pixel_size(16)
    content.append(icon)
    content.append(Gtk.Label(label=label))
    return content


class HomePage(Adw.PreferencesPage):
    def __init__(
        self,
        client: ControlPort,
        run_mutation: MutationRunner,
        request_refresh: Callable[[], None],
        scene_store: SceneStore | None = None,
        show_error: Callable[[str], None] | None = None,
        show_message: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        self.add_css_class("control-page")
        self.set_title("Inicio")
        self.set_icon_name("view-grid-symbolic")
        self._client = client
        self._run_mutation = run_mutation
        self._request_refresh = request_refresh
        self._refreshing = False
        self._available_profiles: set[str] = set()
        self._pending_profile: str | None = None

        thermal_group = Adw.PreferencesGroup()
        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        hero.add_css_class("thermal-hero")

        hero_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        heading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        heading = Gtk.Label(label="Estado térmico", xalign=0)
        heading.add_css_class("hero-heading")
        self._hero_context = Gtk.Label(label="Lecturas actuales del equipo", xalign=0)
        self._hero_context.add_css_class("hero-subtitle")
        heading_box.append(heading)
        heading_box.append(self._hero_context)
        hero_header.append(heading_box)
        heading_box.set_hexpand(True)
        self._health_pill, self._health_label, self._health_icon = _status_pill()
        self._health_pill.set_valign(Gtk.Align.CENTER)
        hero_header.append(self._health_pill)
        hero.append(hero_header)

        metrics = Gtk.Grid(column_spacing=24, row_spacing=18)
        metrics.set_column_homogeneous(True)
        cpu_metric, self._cpu_value = _metric("CPU", primary=True)
        gpu_metric, self._gpu_value = _metric("GPU", primary=True)
        fan1_metric, self._fan1_value = _metric("VENTILADOR 1")
        fan2_metric, self._fan2_value = _metric("VENTILADOR 2")
        metrics.attach(cpu_metric, 0, 0, 1, 1)
        metrics.attach(gpu_metric, 1, 0, 1, 1)
        metrics.attach(fan1_metric, 2, 0, 1, 1)
        metrics.attach(fan2_metric, 3, 0, 1, 1)
        hero.append(metrics)
        thermal_group.add(hero)
        self.add(thermal_group)

        history_group = Adw.PreferencesGroup()
        self._history_panel = TelemetryHistoryPanel()
        history_group.add(self._history_panel)
        self.add(history_group)

        profile_group = Adw.PreferencesGroup()
        profile_group.set_title("Rendimiento")
        profile_group.set_description("Ruido, consumo y potencia")
        self._profile_row = Adw.ComboRow()
        self._profile_row.set_title("Perfil térmico")
        self._profile_row.set_subtitle("Esperando lectura del kernel")
        self._profile_row.set_model(Gtk.StringList.new(PROFILE_LABELS))
        self._profile_row.add_prefix(
            _prefix_icon("power-profile-balanced-symbolic", "Perfil térmico")
        )
        self._profile_row.connect("notify::selected", self._on_profile_selected)
        profile_group.add(self._profile_row)
        self.add(profile_group)

        self._scene_panel: ScenePanel | None = None
        if scene_store is not None:
            self._scene_panel = ScenePanel(
                client,
                scene_store,
                run_mutation,
                request_refresh,
                show_error or (lambda _message: None),
                show_message or (lambda _message: None),
            )
            self.add(self._scene_panel)

        system_group = Adw.PreferencesGroup()
        system_group.set_title("Resumen")
        self._battery_row, self._battery_value = _value_row("Batería")
        self._service_row, self._service_value = _value_row(
            "Control de curva", "Servicio térmico local"
        )
        self._battery_row.add_prefix(
            _prefix_icon("battery-level-80-charging-symbolic", "Batería")
        )
        self._service_row.add_prefix(
            _prefix_icon("weather-tornado-symbolic", "Control de ventilación")
        )
        system_group.add(self._battery_row)
        system_group.add(self._service_row)
        self.add(system_group)

    def update_status(self, status: dict[str, object]) -> None:
        self._history_panel.update_status(status)
        if self._scene_panel is not None:
            self._scene_panel.update_status(status)
        self._refreshing = True
        capabilities = _dictionary(status.get("capabilities"))
        self._available_profiles = set(_string_list(capabilities.get("platform_profiles")))
        self._cpu_value.set_label(_temperature(status.get("cpu_temperature_c")))
        self._gpu_value.set_label(_temperature(status.get("gpu_temperature_c")))
        self._fan1_value.set_label(_rpm(status.get("fan1_rpm")))
        self._fan2_value.set_label(_rpm(status.get("fan2_rpm")))
        temperatures = [
            value
            for value in (
                status.get("cpu_temperature_c"),
                status.get("gpu_temperature_c"),
            )
            if type(value) is int
        ]
        hottest = max(temperatures, default=None)
        if hottest is None:
            self._health_label.set_label("Lecturas incompletas")
            self._health_icon.set_from_icon_name("dialog-warning-symbolic")
            _set_status_tone(self._health_pill, "status-warm")
        elif hottest >= 92:
            self._health_label.set_label("Temperatura crítica")
            self._health_icon.set_from_icon_name("dialog-warning-symbolic")
            _set_status_tone(self._health_pill, "status-critical")
        elif hottest >= 80:
            self._health_label.set_label("Temperatura elevada")
            self._health_icon.set_from_icon_name("dialog-warning-symbolic")
            _set_status_tone(self._health_pill, "status-warm")
        else:
            self._health_label.set_label("Estado estable")
            self._health_icon.set_from_icon_name("emblem-ok-symbolic")
            _set_status_tone(self._health_pill, "status-stable")
        battery = status.get("battery_percent")
        battery_status = _battery_status(status.get("battery_status"))
        self._battery_value.set_label(
            f"{battery}% · {battery_status}" if isinstance(battery, int) else "No disponible"
        )
        service_active = bool(status.get("fan_service_active"))
        self._service_value.set_label("Activo" if service_active else "Firmware")
        profile = status.get("profile")
        profile_label = (
            PROFILE_LABELS[PROFILE_VALUES.index(profile)]
            if profile in PROFILE_VALUES
            else "Perfil desconocido"
        )
        owner = "Curva activa" if service_active else "Control firmware"
        self._hero_context.set_label(f"{profile_label} · {owner}")
        if profile in PROFILE_VALUES:
            if self._pending_profile is None or profile == self._pending_profile:
                self._profile_row.set_selected(PROFILE_VALUES.index(profile))
            if profile == self._pending_profile:
                self._pending_profile = None
            if self._pending_profile is None:
                self._profile_row.set_subtitle(
                    f"Confirmado por el kernel: {profile_label}"
                )
        if self._pending_profile is not None:
            pending_label = PROFILE_LABELS[
                PROFILE_VALUES.index(self._pending_profile)
            ]
            self._profile_row.set_subtitle(f"Confirmando {pending_label}…")
        self._profile_row.set_sensitive(
            bool(self._available_profiles) and self._pending_profile is None
        )
        self._refreshing = False

    def _on_profile_selected(self, row: Adw.ComboRow, _parameter: object) -> None:
        if self._refreshing:
            return
        index = row.get_selected()
        if index >= len(PROFILE_VALUES):
            return
        profile = PROFILE_VALUES[index]
        if profile not in self._available_profiles:
            return
        self._pending_profile = profile
        self._profile_row.set_sensitive(False)
        self._profile_row.set_subtitle(
            f"Confirmando {PROFILE_LABELS[index]}…"
        )

        def finish() -> None:
            self._request_refresh()

        def restore() -> None:
            self._pending_profile = None
            self._profile_row.set_sensitive(bool(self._available_profiles))
            self._request_refresh()

        self._run_mutation(
            lambda: self._client.set_profile(profile),
            f"Perfil cambiado a {PROFILE_LABELS[index]}.",
            finish,
            restore,
        )


class FanPage(Adw.PreferencesPage):
    def __init__(
        self,
        client: ControlPort,
        run_mutation: MutationRunner,
        request_refresh: Callable[[], None],
    ) -> None:
        super().__init__()
        self.add_css_class("control-page")
        self.set_title("Ventilación")
        self.set_icon_name("weather-tornado-symbolic")
        self._client = client
        self._run_mutation = run_mutation
        self._request_refresh = request_refresh
        self._bounds = FanBounds(1700, 5300, 100)
        self._latest_temperature = 60
        self._refreshing = False
        self._editor_dirty = False
        self._fan_control_available = False
        self._power_control_available = False
        self._power_capabilities: PowerLimitCapabilities | None = None

        live_group = Adw.PreferencesGroup()
        live_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        live_header.add_css_class("live-strip")
        temperature_metric, self._temperature_value = _metric("MÁS CALIENTE")
        fan1_metric, self._fan1_value = _metric("VENTILADOR 1")
        fan2_metric, self._fan2_value = _metric("VENTILADOR 2")
        target_metric, self._target_value = _metric("OBJETIVO")
        for metric in (
            temperature_metric,
            fan1_metric,
            fan2_metric,
            target_metric,
        ):
            metric.set_hexpand(True)
            live_header.append(metric)
        self._mode_pill, self._mode_status, mode_icon = _status_pill()
        mode_icon.set_from_icon_name("weather-tornado-symbolic")
        self._mode_status.set_label("Firmware")
        self._mode_pill.add_css_class("mode-pill")
        live_header.append(self._mode_pill)
        live_group.add(live_header)
        self.add(live_group)

        safety_group = Adw.PreferencesGroup()
        restore_row = Adw.ActionRow()
        restore_row.set_title("Salida segura: control firmware")
        restore_row.set_subtitle(
            "Detiene el servicio y devuelve ambos objetivos a automático"
        )
        restore_row.add_prefix(
            _prefix_icon("security-high-symbolic", "Recuperación segura")
        )
        self._restore_button = Gtk.Button()
        self._restore_button.set_child(
            _button_content("Restaurar firmware", "view-refresh-symbolic")
        )
        self._restore_button.add_css_class("safe-action")
        self._restore_button.set_valign(Gtk.Align.CENTER)
        self._restore_button.connect("clicked", self._on_restore_clicked)
        restore_row.add_suffix(self._restore_button)
        restore_row.set_activatable_widget(self._restore_button)
        safety_group.add(restore_row)
        self.add(safety_group)

        self._power_group = Adw.PreferencesGroup()
        self._power_group.set_title("Potencia Custom")
        self._power_group.set_description(
            "CPU y ventilación se aplican juntas en Personalizado"
        )
        self._power_group.set_visible(False)

        sustained_row = Adw.ActionRow()
        sustained_row.set_title("Potencia sostenida")
        sustained_row.set_subtitle("Límite estable de CPU (PPT PL1 / SPL)")
        sustained_row.add_prefix(
            _prefix_icon("speedometer-symbolic", "Potencia sostenida")
        )
        self._sustained_adjustment = Gtk.Adjustment(
            value=70,
            lower=50,
            upper=135,
            step_increment=1,
            page_increment=5,
        )
        self._sustained_spin = Gtk.SpinButton(
            adjustment=self._sustained_adjustment
        )
        self._sustained_spin.set_digits(0)
        self._sustained_spin.set_numeric(True)
        sustained_row.add_suffix(_spin_with_unit(self._sustained_spin, "W"))
        self._power_group.add(sustained_row)

        slow_row = Adw.ActionRow()
        slow_row.set_title("Potencia lenta")
        slow_row.set_subtitle("Techo temporal de CPU (PPT PL2 / SPPT)")
        slow_row.add_prefix(
            _prefix_icon("power-profile-performance-symbolic", "Potencia lenta")
        )
        self._slow_adjustment = Gtk.Adjustment(
            value=125,
            lower=60,
            upper=210,
            step_increment=1,
            page_increment=5,
        )
        self._slow_spin = Gtk.SpinButton(adjustment=self._slow_adjustment)
        self._slow_spin.set_digits(0)
        self._slow_spin.set_numeric(True)
        slow_row.add_suffix(_spin_with_unit(self._slow_spin, "W"))
        self._power_group.add(slow_row)
        self._sustained_adjustment.connect(
            "value-changed", self._on_power_value_changed
        )
        self._slow_adjustment.connect(
            "value-changed", self._on_power_value_changed
        )
        self.add(self._power_group)

        self._editor_group = Adw.PreferencesGroup()
        self._editor_group.set_title("Modo de ventilación")
        self._editor_group.set_description(
            "Curva con filtrado e histéresis · continúa aunque cierres la ventana"
        )

        self._mode_selector = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=0,
        )
        self._mode_selector.add_css_class("linked")
        self._mode_selector.add_css_class("mode-selector")
        self._mode_selector.set_halign(Gtk.Align.FILL)
        self._mode_buttons: dict[FanMode, Gtk.ToggleButton] = {}
        mode_icons = (
            "emblem-system-symbolic",
            "speedometer-symbolic",
            "weather-tornado-symbolic",
        )
        for mode, label, icon_name in zip(
            MODE_VALUES, MODE_LABELS, mode_icons, strict=True
        ):
            button = Gtk.ToggleButton()
            button.set_hexpand(True)
            button.set_child(_button_content(label, icon_name))
            button.connect("toggled", self._on_mode_button_toggled, mode)
            self._mode_selector.append(button)
            self._mode_buttons[mode] = button
        self._editor_group.add(self._mode_selector)

        apply_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        apply_box.set_halign(Gtk.Align.END)
        apply_box.set_margin_top(12)
        self._apply_button = Gtk.Button(label="Aplicar curva")
        self._apply_button.add_css_class("suggested-action")
        self._apply_button.add_css_class("legion-primary")
        self._apply_button.connect("clicked", self._on_apply_clicked)
        self._apply_button.set_sensitive(False)
        apply_box.append(self._apply_button)
        self._editor_group.add(apply_box)

        self._editor_stack = Gtk.Stack()
        self._editor_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._editor_stack.set_transition_duration(180)
        self._editor_stack.set_vhomogeneous(False)
        self._editor_stack.add_css_class("editor-panel")
        self._editor_stack.set_margin_top(16)
        self._editor_stack.add_named(self._build_auto_editor(), "auto")
        self._editor_stack.add_named(self._build_fixed_editor(), "fixed")
        self._editor_stack.add_named(self._build_curve_editor(), "curve")
        self._editor_group.add(self._editor_stack)
        self.add(self._editor_group)

    def _build_auto_editor(self) -> Gtk.Widget:
        label = Gtk.Label(
            label=(
                "El firmware decide la velocidad. Es el estado más seguro "
                "si no necesitas una curva propia."
            ),
            wrap=True,
            xalign=0,
        )
        label.add_css_class("dim-label")
        label.set_margin_start(16)
        label.set_margin_end(16)
        label.set_margin_top(16)
        label.set_margin_bottom(16)
        return label

    def _build_fixed_editor(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        self._fixed_adjustment = Gtk.Adjustment(
            value=2500,
            lower=self._bounds.minimum_rpm,
            upper=self._bounds.maximum_rpm,
            step_increment=self._bounds.step_rpm,
            page_increment=500,
        )
        self._fixed_scale = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL,
            adjustment=self._fixed_adjustment,
        )
        self._fixed_scale.set_draw_value(False)
        self._fixed_scale.set_hexpand(True)
        self._fixed_spin = Gtk.SpinButton(adjustment=self._fixed_adjustment)
        self._fixed_spin.set_digits(0)
        self._fixed_spin.set_numeric(True)
        self._fixed_spin.set_accessible_role(Gtk.AccessibleRole.SPIN_BUTTON)
        self._fixed_adjustment.connect("value-changed", self._on_fixed_value_changed)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.append(self._fixed_scale)
        row.append(self._fixed_spin)
        unit = Gtk.Label(label="RPM")
        unit.add_css_class("dim-label")
        row.append(unit)
        box.append(row)
        return box

    def _build_curve_editor(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        self._graph = Gtk.DrawingArea()
        self._graph.set_content_height(220)
        self._graph.set_hexpand(True)
        self._graph.set_draw_func(self._draw_curve)
        self._graph.set_accessible_role(Gtk.AccessibleRole.IMG)
        self._graph.set_tooltip_text(
            "Curva de temperatura y RPM con el punto de trabajo actual"
        )
        self._graph.add_css_class("curve-canvas")
        box.append(self._graph)

        grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        grid.set_column_homogeneous(False)
        temperature_heading = Gtk.Label(label="Temperatura")
        temperature_heading.add_css_class("heading")
        temperature_heading.set_halign(Gtk.Align.START)
        rpm_heading = Gtk.Label(label="Objetivo")
        rpm_heading.add_css_class("heading")
        rpm_heading.set_halign(Gtk.Align.START)
        grid.attach(Gtk.Label(label=""), 0, 0, 1, 1)
        grid.attach(temperature_heading, 1, 0, 1, 1)
        grid.attach(rpm_heading, 2, 0, 1, 1)
        self._point_spins: list[tuple[Gtk.SpinButton, Gtk.SpinButton]] = []
        for index, point in enumerate(DEFAULT_CURVE.points, start=1):
            point_label = Gtk.Label(label=f"Punto {index}")
            point_label.set_halign(Gtk.Align.START)
            temperature_spin = Gtk.SpinButton.new_with_range(20, 100, 1)
            temperature_spin.set_value(point.temperature_c)
            temperature_spin.set_numeric(True)
            rpm_spin = Gtk.SpinButton.new_with_range(
                self._bounds.minimum_rpm,
                self._bounds.maximum_rpm,
                self._bounds.step_rpm,
            )
            rpm_spin.set_value(point.rpm)
            rpm_spin.set_numeric(True)
            temperature_spin.connect("value-changed", self._on_curve_value_changed)
            rpm_spin.connect("value-changed", self._on_curve_value_changed)
            grid.attach(point_label, 0, index, 1, 1)
            grid.attach(_spin_with_unit(temperature_spin, "°C"), 1, index, 1, 1)
            grid.attach(_spin_with_unit(rpm_spin, "RPM"), 2, index, 1, 1)
            self._point_spins.append((temperature_spin, rpm_spin))
        box.append(grid)
        return box

    def update_status(self, status: dict[str, object]) -> None:
        capabilities = _dictionary(status.get("capabilities"))
        power_capabilities = _power_capabilities_from_document(
            capabilities.get("power_limits")
        )
        self._power_control_available = bool(
            capabilities.get("power_control")
        ) and power_capabilities is not None
        self._power_capabilities = power_capabilities
        self._power_group.set_visible(self._power_control_available)
        if power_capabilities is not None:
            self._refreshing = True
            self._update_power_adjustment(
                self._sustained_adjustment,
                power_capabilities.sustained,
            )
            self._update_power_adjustment(
                self._slow_adjustment,
                power_capabilities.slow,
            )
            if not self._editor_dirty:
                current_power = status.get("power_limits")
                if isinstance(current_power, dict):
                    try:
                        limits = CustomPowerLimits(
                            sustained_w=int(current_power["sustained_w"]),
                            slow_w=int(current_power["slow_w"]),
                        )
                        limits.validate_for(power_capabilities)
                    except (KeyError, TypeError, ValueError):
                        pass
                    else:
                        self._sustained_adjustment.set_value(
                            limits.sustained_w
                        )
                        self._slow_adjustment.set_value(limits.slow_w)
            self._refreshing = False
        minimum = capabilities.get("fan_minimum_rpm")
        maximum = capabilities.get("fan_maximum_rpm")
        step = capabilities.get("fan_step_rpm")
        if all(type(value) is int for value in (minimum, maximum, step)):
            try:
                self._bounds = FanBounds(int(minimum), int(maximum), int(step))
                self._update_adjustment_bounds()
            except DomainError:
                pass
        temperatures = [
            value
            for value in (
                status.get("cpu_temperature_c"),
                status.get("gpu_temperature_c"),
            )
            if type(value) is int
        ]
        if temperatures:
            self._latest_temperature = max(temperatures)
        self._temperature_value.set_label(f"{self._latest_temperature} °C")
        self._fan1_value.set_label(_rpm(status.get("fan1_rpm")))
        self._fan2_value.set_label(_rpm(status.get("fan2_rpm")))
        target_values = [
            value
            for value in (
                status.get("fan1_target_rpm"),
                status.get("fan2_target_rpm"),
            )
            if type(value) is int and value > 0
        ]
        self._target_value.set_label(
            f"{max(target_values)} RPM" if target_values else "Firmware"
        )
        self._fan_control_available = bool(capabilities.get("fan_control"))
        self._restore_button.set_sensitive(self._fan_control_available)
        policy = _dictionary(status.get("fan_policy"))
        if not self._editor_dirty:
            self._load_policy(policy)
        mode = str(policy.get("mode", "auto"))
        service_active = bool(status.get("fan_service_active"))
        if service_active and mode == FanMode.CURVE.value:
            self._mode_status.set_label("Curva activa")
            _set_status_tone(self._mode_pill, "status-stable")
        elif service_active and mode == FanMode.FIXED.value:
            self._mode_status.set_label("RPM fija")
            _set_status_tone(self._mode_pill, "status-warm")
        else:
            self._mode_status.set_label("Firmware")
            _set_status_tone(self._mode_pill, "status-stable")
        self._sync_apply_button()
        self._graph.queue_draw()

    def _load_policy(self, document: dict[str, object]) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        mode_value = document.get("mode", "auto")
        try:
            mode = FanMode(str(mode_value))
        except ValueError:
            mode = FanMode.AUTO
        self._mode_buttons[mode].set_active(True)
        self._editor_stack.set_visible_child_name(mode.value)
        self._sync_power_group(mode)
        fixed = document.get("fixed_rpm")
        if type(fixed) is int:
            self._fixed_adjustment.set_value(int(fixed))
        curve = document.get("curve")
        if isinstance(curve, list) and len(curve) == len(self._point_spins):
            for item, (temperature_spin, rpm_spin) in zip(
                curve, self._point_spins, strict=True
            ):
                if isinstance(item, dict):
                    temperature = item.get("temperature_c")
                    rpm = item.get("rpm")
                    if type(temperature) is int:
                        temperature_spin.set_value(temperature)
                    if type(rpm) is int:
                        rpm_spin.set_value(rpm)
        self._refreshing = False
        self._set_editor_dirty(False)
        self._graph.queue_draw()

    def _update_adjustment_bounds(self) -> None:
        self._fixed_adjustment.set_lower(self._bounds.minimum_rpm)
        self._fixed_adjustment.set_upper(self._bounds.maximum_rpm)
        self._fixed_adjustment.set_step_increment(self._bounds.step_rpm)
        for _, rpm_spin in self._point_spins:
            adjustment = rpm_spin.get_adjustment()
            adjustment.set_lower(self._bounds.minimum_rpm)
            adjustment.set_upper(self._bounds.maximum_rpm)
            adjustment.set_step_increment(self._bounds.step_rpm)

    @staticmethod
    def _update_power_adjustment(
        adjustment: Gtk.Adjustment,
        bounds: PowerLimitBounds,
    ) -> None:
        adjustment.set_lower(bounds.minimum_w)
        adjustment.set_upper(bounds.maximum_w)
        adjustment.set_step_increment(bounds.step_w)
        adjustment.set_page_increment(max(bounds.step_w, 5))

    def _on_mode_button_toggled(
        self, button: Gtk.ToggleButton, mode: FanMode
    ) -> None:
        if not button.get_active():
            if not any(
                candidate.get_active()
                for candidate in self._mode_buttons.values()
            ):
                button.set_active(True)
            return
        for candidate in self._mode_buttons.values():
            if candidate is not button and candidate.get_active():
                candidate.set_active(False)
        self._editor_stack.set_visible_child_name(mode.value)
        labels = {
            FanMode.AUTO: "Usar control automático",
            FanMode.FIXED: "Aplicar RPM + potencia",
            FanMode.CURVE: "Aplicar curva + potencia",
        }
        self._apply_button.set_label(labels[mode])
        self._sync_power_group(mode)
        if not self._refreshing:
            self._set_editor_dirty(True)

    def _on_restore_clicked(self, _button: Gtk.Button) -> None:
        self._restore_button.set_sensitive(False)
        self._run_mutation(
            self._client.restore_auto,
            "Control devuelto al firmware.",
            self._finish_restore,
            self._restore_failed,
        )

    def _on_apply_clicked(self, _button: Gtk.Button) -> None:
        if not self._editor_dirty:
            return
        try:
            policy = self._policy_from_editor()
            policy.validate_for(self._bounds)
            power_limits = self._power_limits_from_editor()
            if (
                policy.mode is not FanMode.AUTO
                and self._power_capabilities is not None
            ):
                power_limits.validate_for(self._power_capabilities)
        except (DomainError, ValueError) as error:
            root = self.get_root()
            if isinstance(root, MainWindow):
                root.show_error(str(error))
            return
        if policy.mode is FanMode.AUTO:
            operation = self._client.restore_auto
        elif self._power_capabilities is not None:
            operation = lambda: self._client.set_custom_configuration(
                policy,
                power_limits,
            )
        else:
            operation = lambda: self._client.set_fan_policy(policy)
        message = (
            "Control devuelto al firmware."
            if policy.mode is FanMode.AUTO
            else "Configuración de ventilación aplicada."
        )
        self._apply_button.set_sensitive(False)
        self._run_mutation(
            operation,
            message,
            self._finish_apply,
            self._apply_failed,
        )

    def _policy_from_editor(self) -> FanPolicy:
        mode = next(
            (
                candidate
                for candidate, button in self._mode_buttons.items()
                if button.get_active()
            ),
            FanMode.AUTO,
        )
        points = tuple(
            CurvePoint(
                temperature_c=temperature_spin.get_value_as_int(),
                rpm=rpm_spin.get_value_as_int(),
            )
            for temperature_spin, rpm_spin in self._point_spins
        )
        return FanPolicy(
            mode=mode,
            fixed_rpm=self._fixed_spin.get_value_as_int(),
            curve=FanCurve(points),
        )

    def _power_limits_from_editor(self) -> CustomPowerLimits:
        return CustomPowerLimits(
            sustained_w=self._sustained_spin.get_value_as_int(),
            slow_w=self._slow_spin.get_value_as_int(),
        )

    def _on_curve_value_changed(self, _spin: Gtk.SpinButton) -> None:
        if not self._refreshing:
            self._set_editor_dirty(True)
            self._graph.queue_draw()

    def _on_fixed_value_changed(self, _adjustment: Gtk.Adjustment) -> None:
        if not self._refreshing:
            self._set_editor_dirty(True)

    def _on_power_value_changed(self, _adjustment: Gtk.Adjustment) -> None:
        if not self._refreshing:
            self._set_editor_dirty(True)

    def _sync_power_group(self, mode: FanMode) -> None:
        self._power_group.set_sensitive(
            self._power_control_available and mode is not FanMode.AUTO
        )

    def _set_editor_dirty(self, dirty: bool) -> None:
        self._editor_dirty = dirty
        if dirty:
            self._editor_group.set_description(
                "Cambios sin aplicar · pulsa Aplicar para activarlos"
            )
        else:
            self._editor_group.set_description(
                "Curva con filtrado e histéresis · continúa aunque cierres la ventana"
            )
        self._sync_apply_button()

    def _sync_apply_button(self) -> None:
        self._apply_button.set_sensitive(
            self._fan_control_available and self._editor_dirty
        )

    def _finish_apply(self) -> None:
        self._set_editor_dirty(False)
        self._request_refresh()

    def _apply_failed(self) -> None:
        self._sync_apply_button()

    def _finish_restore(self) -> None:
        self._set_editor_dirty(False)
        self._request_refresh()

    def _restore_failed(self) -> None:
        self._restore_button.set_sensitive(self._fan_control_available)

    def _draw_curve(
        self, _area: Gtk.DrawingArea, context: Any, width: int, height: int
    ) -> None:
        dark = Adw.StyleManager.get_default().get_dark()
        foreground = (0.94, 0.95, 0.97) if dark else (0.12, 0.13, 0.15)
        muted = (0.59, 0.61, 0.66) if dark else (0.43, 0.45, 0.49)
        grid = (0.72, 0.74, 0.78) if dark else (0.20, 0.22, 0.26)
        accent = (0.90, 0.20, 0.25)
        live = (0.96, 0.62, 0.16)
        margin_left, margin_right = 54, 18
        margin_top, margin_bottom = 26, 34
        graph_width = max(1, width - margin_left - margin_right)
        graph_height = max(1, height - margin_top - margin_bottom)

        context.set_line_width(1)
        context.set_source_rgba(*grid, 0.14)
        for temperature in (20, 40, 60, 80, 100):
            x = margin_left + ((temperature - 20) / 80) * graph_width
            context.move_to(x, margin_top)
            context.line_to(x, margin_top + graph_height)
        for fraction in (0.0, 0.5, 1.0):
            y = margin_top + graph_height - fraction * graph_height
            context.move_to(margin_left, y)
            context.line_to(margin_left + graph_width, y)
        context.stroke()

        context.set_line_width(1)
        context.set_source_rgba(*muted, 0.65)
        context.move_to(margin_left, margin_top)
        context.line_to(margin_left, margin_top + graph_height)
        context.line_to(margin_left + graph_width, margin_top + graph_height)
        context.stroke()

        try:
            curve = self._policy_from_editor().curve
            curve.validate_for(self._bounds)
        except DomainError:
            return

        def position(temperature_c: int, rpm: int) -> tuple[float, float]:
            x = margin_left + ((temperature_c - 20) / 80) * graph_width
            fraction = (
                (rpm - self._bounds.minimum_rpm)
                / (self._bounds.maximum_rpm - self._bounds.minimum_rpm)
            )
            y = margin_top + graph_height - fraction * graph_height
            return x, y

        positions = [
            position(point.temperature_c, point.rpm) for point in curve.points
        ]
        first_x, first_y = positions[0]
        last_x, last_y = positions[-1]
        context.move_to(first_x, margin_top + graph_height)
        context.line_to(first_x, first_y)
        for x, y in positions[1:]:
            context.line_to(x, y)
        context.line_to(last_x, margin_top + graph_height)
        context.close_path()
        fill = cairo.LinearGradient(0, margin_top, 0, margin_top + graph_height)
        fill.add_color_stop_rgba(0, *accent, 0.24)
        fill.add_color_stop_rgba(1, *accent, 0.025)
        context.set_source(fill)
        context.fill()

        context.set_source_rgb(*accent)
        context.set_line_width(3.5)
        context.set_line_join(cairo.LINE_JOIN_ROUND)
        for index, (x, y) in enumerate(positions):
            if index == 0:
                context.move_to(x, y)
            else:
                context.line_to(x, y)
        context.stroke()

        for x, y in positions:
            context.set_source_rgb(*foreground)
            context.arc(x, y, 6.5, 0, math.tau)
            context.fill()
            context.set_source_rgb(*accent)
            context.arc(x, y, 4, 0, math.tau)
            context.fill()

        try:
            live_target = curve.target_at(self._latest_temperature, self._bounds)
        except DomainError:
            live_target = None
        if live_target is not None:
            current_x, current_y = position(self._latest_temperature, live_target)
            context.set_source_rgba(*live, 0.72)
            context.set_line_width(1.5)
            context.set_dash([5, 5])
            context.move_to(current_x, margin_top)
            context.line_to(current_x, margin_top + graph_height)
            context.stroke()
            context.set_dash([])
            context.set_source_rgb(*foreground)
            context.arc(current_x, current_y, 8, 0, math.tau)
            context.fill()
            context.set_source_rgb(*live)
            context.arc(current_x, current_y, 5, 0, math.tau)
            context.fill()
            context.set_source_rgb(*live)
            context.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            context.set_font_size(11)
            context.move_to(min(current_x + 8, width - 62), margin_top - 8)
            context.show_text(f"{self._latest_temperature} °C")

        context.set_source_rgb(*foreground)
        context.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        context.set_font_size(11)
        context.move_to(margin_left - 5, height - 8)
        context.show_text("20 °C")
        context.move_to(width - 52, height - 8)
        context.show_text("100 °C")
        context.move_to(2, margin_top + 5)
        context.show_text(str(self._bounds.maximum_rpm))
        context.move_to(2, margin_top + graph_height)
        context.show_text(str(self._bounds.minimum_rpm))


class DevicePage(Adw.PreferencesPage):
    FEATURE_COPY: Final = {
        "conservation_mode": (
            "Conservación de batería",
            "Reduce el desgaste cuando el portátil permanece conectado",
        ),
        "fn_lock": (
            "Bloqueo Fn",
            "Cambia el comportamiento principal de la fila de funciones",
        ),
        "camera_power": (
            "Alimentación de cámara",
            "Conecta o corta la cámara integrada",
        ),
    }
    FEATURE_ICONS: Final = {
        "conservation_mode": "battery-level-80-charging-symbolic",
        "fn_lock": "input-keyboard-symbolic",
        "camera_power": "camera-web-symbolic",
    }

    def __init__(
        self,
        client: ControlPort,
        run_mutation: MutationRunner,
        request_refresh: Callable[[], None],
    ) -> None:
        super().__init__()
        self.add_css_class("control-page")
        self.set_title("Dispositivo")
        self.set_icon_name("preferences-system-symbolic")
        self._client = client
        self._run_mutation = run_mutation
        self._request_refresh = request_refresh
        self._refreshing = False

        identity_group = Adw.PreferencesGroup()
        identity = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        identity.add_css_class("device-hero")
        device_icon = Gtk.Image.new_from_icon_name("computer-symbolic")
        device_icon.set_pixel_size(28)
        device_icon.add_css_class("device-mark")
        identity.append(device_icon)
        identity_copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        identity_copy.set_hexpand(True)
        self._device_name = Gtk.Label(label="Lenovo Legion", xalign=0)
        self._device_name.add_css_class("device-name")
        self._device_model = Gtk.Label(label="Detectando modelo…", xalign=0)
        self._device_model.add_css_class("hero-subtitle")
        identity_copy.append(self._device_name)
        identity_copy.append(self._device_model)
        identity.append(identity_copy)
        self._device_pill, self._device_status, device_status_icon = _status_pill()
        device_status_icon.set_from_icon_name("emblem-ok-symbolic")
        self._device_status.set_label("Compatible")
        identity.append(self._device_pill)
        identity_group.add(identity)
        self.add(identity_group)

        group = Adw.PreferencesGroup()
        group.set_title("Funciones del equipo")
        group.set_description("Cambios guardados por el firmware")
        self._rows: dict[str, Adw.SwitchRow] = {}
        for feature, (title, subtitle) in self.FEATURE_COPY.items():
            row = Adw.SwitchRow()
            row.set_title(title)
            row.set_subtitle(subtitle)
            row.add_prefix(_prefix_icon(self.FEATURE_ICONS[feature], title))
            row.connect("notify::active", self._on_feature_changed, feature)
            group.add(row)
            self._rows[feature] = row
        self.add(group)

    def update_status(self, status: dict[str, object]) -> None:
        capabilities = _dictionary(status.get("capabilities"))
        available = set(_string_list(capabilities.get("features")))
        values = _dictionary(status.get("features"))
        product_version = str(capabilities.get("product_version") or "Lenovo Legion")
        product = str(capabilities.get("product") or "modelo desconocido")
        self._device_name.set_label(product_version)
        self._device_model.set_label(f"Producto {product}")
        if bool(capabilities.get("supported")):
            self._device_status.set_label("Compatible")
            _set_status_tone(self._device_pill, "status-stable")
        else:
            self._device_status.set_label("Solo lectura")
            _set_status_tone(self._device_pill, "status-warm")
        self._refreshing = True
        for feature, row in self._rows.items():
            row.set_sensitive(feature in available)
            value = values.get(feature)
            if isinstance(value, bool):
                row.set_active(value)
        self._refreshing = False

    def _on_feature_changed(
        self, row: Adw.SwitchRow, _parameter: object, feature: str
    ) -> None:
        if self._refreshing:
            return
        desired = row.get_active()
        row.set_sensitive(False)

        def restore_row() -> None:
            self._refreshing = True
            row.set_active(not desired)
            row.set_sensitive(True)
            self._refreshing = False

        def finish() -> None:
            row.set_sensitive(True)
            self._request_refresh()

        self._run_mutation(
            lambda: self._client.set_feature(feature, desired),
            "Función actualizada.",
            finish,
            restore_row,
        )


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application, client: ControlPort) -> None:
        super().__init__(application=application)
        self.set_title("Legion Control")
        self.set_default_size(980, 720)
        self.set_size_request(820, 600)
        self._client = client
        self._refresh_in_progress = False
        self._refresh_pending = False
        self._refresh_generation = 0
        self._mutations_in_progress = 0

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.add_css_class("app-shell")
        header = Adw.HeaderBar()
        header.add_css_class("app-header")

        brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=9)
        brand_icon = Gtk.Image.new_from_icon_name("weather-tornado-symbolic")
        brand_icon.set_pixel_size(18)
        brand_icon.add_css_class("brand-mark")
        brand_label = Gtk.Label(label="Legion Control")
        brand_label.add_css_class("brand-title")
        brand.append(brand_icon)
        brand.append(brand_label)
        header.pack_start(brand)

        self._view_stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcher()
        switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        switcher.set_stack(self._view_stack)
        header.set_title_widget(switcher)

        self._busy_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=7,
        )
        self._busy_box.add_css_class("busy-state")
        self._spinner = Gtk.Spinner()
        self._spinner.set_tooltip_text("Aplicando cambio")
        busy_label = Gtk.Label(label="Aplicando")
        busy_label.add_css_class("busy-label")
        self._busy_box.append(self._spinner)
        self._busy_box.append(busy_label)
        self._busy_box.set_visible(False)
        header.pack_end(self._busy_box)
        root.append(header)

        self._banner = Adw.Banner()
        root.append(self._banner)

        self._toast_overlay = Adw.ToastOverlay()
        self._toast_overlay.set_child(self._view_stack)
        root.append(self._toast_overlay)
        self._toast_overlay.set_vexpand(True)
        self.set_content(root)

        self._home_page = HomePage(
            client,
            self.run_mutation,
            self.request_refresh,
            SceneStore(default_scene_path()),
            self.show_error,
            self.show_message,
        )
        self._fan_page = FanPage(client, self.run_mutation, self.request_refresh)
        self._lighting_page = LightingPage(
            client,
            self.run_mutation,
            self.request_refresh,
            self.show_error,
        )
        self._device_page = DevicePage(client, self.run_mutation, self.request_refresh)
        self._view_stack.add_titled_with_icon(
            self._home_page, "home", "Inicio", "view-grid-symbolic"
        )
        self._view_stack.add_titled_with_icon(
            self._fan_page, "fans", "Ventilación", "weather-tornado-symbolic"
        )
        self._view_stack.add_titled_with_icon(
            self._lighting_page,
            "lighting",
            "Iluminación",
            "preferences-color-symbolic",
        )
        self._view_stack.add_titled_with_icon(
            self._device_page, "device", "Dispositivo", "preferences-system-symbolic"
        )
        if os.environ.get("LEGION_CONTROL_MOCK") == "1":
            requested_view = os.environ.get("LEGION_CONTROL_VIEW", "home")
            if requested_view in {"home", "fans", "lighting", "device"}:
                self._view_stack.set_visible_child_name(requested_view)

        self.request_refresh()
        GLib.timeout_add(REFRESH_INTERVAL_MS, self._refresh_timer)

    def request_refresh(self) -> None:
        if self._mutations_in_progress > 0 or self._refresh_in_progress:
            self._refresh_pending = True
            return
        self._refresh_pending = False
        self._refresh_in_progress = True
        self._refresh_generation += 1
        generation = self._refresh_generation

        def read() -> None:
            try:
                status = self._client.read_status()
            except Exception as error:
                GLib.idle_add(
                    self._finish_refresh_error,
                    generation,
                    str(error),
                )
            else:
                GLib.idle_add(self._finish_refresh, generation, status)

        threading.Thread(target=read, daemon=True, name="status-refresh").start()

    def run_mutation(
        self,
        operation: Operation,
        success_message: str,
        on_success: Callable[[], None] | None,
        on_failure: Callable[[], None] | None,
    ) -> None:
        if self._mutations_in_progress > 0:
            self.show_message("Espera a que termine el cambio en curso.")
            if on_failure:
                on_failure()
            return
        self._mutations_in_progress += 1
        self._refresh_generation += 1
        self._refresh_pending = True
        self._spinner.set_spinning(True)
        self._busy_box.set_visible(True)

        def execute() -> None:
            try:
                operation()
            except Exception as error:
                GLib.idle_add(self._finish_mutation_error, str(error), on_failure)
            else:
                GLib.idle_add(
                    self._finish_mutation_success, success_message, on_success
                )

        threading.Thread(target=execute, daemon=True, name="control-mutation").start()

    def show_error(self, message: str) -> None:
        toast = Adw.Toast.new(message)
        toast.set_timeout(5)
        self._toast_overlay.add_toast(toast)

    def show_message(self, message: str) -> None:
        self._toast_overlay.add_toast(Adw.Toast.new(message))

    def _refresh_timer(self) -> bool:
        self.request_refresh()
        return GLib.SOURCE_CONTINUE

    def _finish_refresh(
        self,
        generation: int,
        status: dict[str, object],
    ) -> bool:
        self._refresh_in_progress = False
        if (
            generation != self._refresh_generation
            or self._mutations_in_progress > 0
        ):
            self._refresh_pending = True
            self._queue_pending_refresh()
            return GLib.SOURCE_REMOVE
        capabilities = _dictionary(status.get("capabilities"))
        supported = bool(capabilities.get("supported"))
        fan_control = bool(capabilities.get("fan_control"))
        if not supported:
            product = capabilities.get("product", "desconocido")
            self._banner.set_title(
                f"Modelo {product} no admitido: controles bloqueados"
            )
            self._banner.set_revealed(True)
        elif not fan_control:
            self._banner.set_title(
                "El kernel no publica control manual de ventiladores"
            )
            self._banner.set_revealed(True)
        else:
            self._banner.set_revealed(False)
        self._home_page.update_status(status)
        self._fan_page.update_status(status)
        self._lighting_page.update_status(status)
        self._device_page.update_status(status)
        self._queue_pending_refresh()
        return GLib.SOURCE_REMOVE

    def _finish_refresh_error(self, generation: int, message: str) -> bool:
        self._refresh_in_progress = False
        if (
            generation != self._refresh_generation
            or self._mutations_in_progress > 0
        ):
            self._refresh_pending = True
            self._queue_pending_refresh()
            return GLib.SOURCE_REMOVE
        self._banner.set_title(f"No se puede leer el equipo: {message}")
        self._banner.set_revealed(True)
        self._queue_pending_refresh()
        return GLib.SOURCE_REMOVE

    def _finish_mutation_success(
        self, message: str, callback: Callable[[], None] | None
    ) -> bool:
        self._finish_busy_state()
        self._toast_overlay.add_toast(Adw.Toast.new(message))
        if callback:
            callback()
        self._queue_pending_refresh()
        return GLib.SOURCE_REMOVE

    def _finish_mutation_error(
        self, message: str, callback: Callable[[], None] | None
    ) -> bool:
        self._finish_busy_state()
        self.show_error(message)
        if callback:
            callback()
        self._queue_pending_refresh()
        return GLib.SOURCE_REMOVE

    def _finish_busy_state(self) -> None:
        self._mutations_in_progress = max(0, self._mutations_in_progress - 1)
        busy = self._mutations_in_progress > 0
        self._spinner.set_spinning(busy)
        self._busy_box.set_visible(busy)

    def _queue_pending_refresh(self) -> None:
        if (
            not self._refresh_pending
            or self._refresh_in_progress
            or self._mutations_in_progress > 0
        ):
            return
        self._refresh_pending = False
        GLib.idle_add(self._request_refresh_idle)

    def _request_refresh_idle(self) -> bool:
        self.request_refresh()
        return GLib.SOURCE_REMOVE


class LegionControlApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APPLICATION_ID)

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        if os.environ.get("LEGION_CONTROL_MOCK") == "1":
            requested_theme = os.environ.get("LEGION_CONTROL_THEME")
            style_manager = Adw.StyleManager.get_default()
            if requested_theme == "light":
                style_manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
            elif requested_theme == "dark":
                style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        install_css()

    def do_activate(self) -> None:
        window = self.get_active_window()
        if window is None:
            client: ControlPort
            if os.environ.get("LEGION_CONTROL_MOCK") == "1":
                client = MockControlClient()
                if os.environ.get("LEGION_CONTROL_MOCK_CURVE") == "1":
                    client.set_fan_policy(
                        FanPolicy(FanMode.CURVE, 2500, DEFAULT_CURVE)
                    )
            else:
                client = LocalControlClient(SysfsHardware())
            window = MainWindow(self, client)
        window.present()


def _dictionary(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _power_capabilities_from_document(
    value: object,
) -> PowerLimitCapabilities | None:
    document = _dictionary(value)
    try:
        return PowerLimitCapabilities(
            sustained=_power_bounds_from_document(document["sustained"]),
            slow=_power_bounds_from_document(document["slow"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _power_bounds_from_document(value: object) -> PowerLimitBounds:
    document = _dictionary(value)
    return PowerLimitBounds(
        minimum_w=document["minimum_w"],
        maximum_w=document["maximum_w"],
        step_w=document["step_w"],
        default_w=document["default_w"],
    )


def _string_list(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _temperature(value: object) -> str:
    return f"{value} °C" if type(value) is int else "No disponible"


def _rpm(value: object) -> str:
    return f"{value} RPM" if type(value) is int else "No disponible"


def _battery_status(value: object) -> str:
    labels = {
        "Charging": "cargando",
        "Discharging": "en uso",
        "Full": "completa",
        "Not charging": "sin cargar",
    }
    return labels.get(str(value), str(value or "estado desconocido"))


def main() -> int:
    return LegionControlApplication().run(None)


if __name__ == "__main__":
    raise SystemExit(main())
