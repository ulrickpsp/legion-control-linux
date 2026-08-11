"""Native graph with local 10-minute, 24-hour and seven-day telemetry views."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gtk  # noqa: E402

from legion_control.history import (  # noqa: E402
    DAY_SECONDS,
    DEFAULT_HISTORY_SECONDS,
    TelemetryArchive,
    TelemetryEvent,
    TelemetryHistory,
    TelemetrySample,
    default_telemetry_path,
)
from legion_control.i18n import translate  # noqa: E402
from legion_control.ui_files import choose_save_path  # noqa: E402


# Series colours per colour scheme; each one clears the 3:1 contrast floor for
# graphical objects against its own graph background.
SERIES_COLORS_DARK = {
    "cpu": (0.961, 0.620, 0.161),
    "gpu": (0.900, 0.200, 0.250),
    "fan1": (0.204, 0.718, 0.831),
    "fan2": (0.478, 0.522, 0.949),
}
SERIES_COLORS_LIGHT = {
    "cpu": (0.706, 0.325, 0.035),
    "gpu": (0.757, 0.184, 0.231),
    "fan1": (0.055, 0.455, 0.565),
    "fan2": (0.310, 0.275, 0.898),
}

HISTORY_WINDOWS = (
    ("10 min", DEFAULT_HISTORY_SECONDS),
    ("24 h", DAY_SECONDS),
    ("7 días", 7 * DAY_SECONDS),
)


class TelemetryHistoryPanel(Gtk.Box):
    def __init__(
        self,
        archive: TelemetryArchive | None = None,
        show_error: Callable[[str], None] | None = None,
        show_message: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add_css_class("history-panel")
        self._archive = archive or TelemetryArchive(default_telemetry_path())
        self._show_error = show_error or (lambda _message: None)
        self._show_message = show_message or (lambda _message: None)
        samples, events = self._archive.load(max_age_seconds=DEFAULT_HISTORY_SECONDS)
        self._history = TelemetryHistory(samples=samples, events=events)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        copy.set_hexpand(True)
        self._title = Gtk.Label(label="Últimos 10 minutos", xalign=0)
        self._title.add_css_class("history-title")
        self._subtitle = Gtk.Label(label="Recopilando lecturas…", xalign=0)
        self._subtitle.add_css_class("hero-subtitle")
        copy.append(self._title)
        copy.append(self._subtitle)
        header.append(copy)

        legend = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self._legend_labels: list[Gtk.Label] = []
        for label, css_class in (
            ("CPU", "legend-cpu"),
            ("GPU", "legend-gpu"),
            ("Fan 1", "legend-fan1"),
            ("Fan 2", "legend-fan2"),
        ):
            item = Gtk.Label(label=label)
            item.add_css_class("history-legend")
            item.add_css_class(css_class)
            legend.append(item)
            self._legend_labels.append(item)
        header.append(legend)
        self.append(header)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        controls.set_halign(Gtk.Align.END)
        self._window_selector = Gtk.DropDown.new_from_strings(
            tuple(translate(label) for label, _ in HISTORY_WINDOWS)
        )
        self._window_selector.set_selected(0)
        self._window_selector.connect("notify::selected", self._on_window_changed)
        export = Gtk.Button(label="Exportar CSV")
        export.connect("clicked", self._on_export_clicked)
        controls.append(self._window_selector)
        controls.append(export)
        self.append(controls)

        self._graph = Gtk.DrawingArea()
        self._graph.set_content_height(170)
        self._graph.set_hexpand(True)
        self._graph.set_accessible_role(Gtk.AccessibleRole.IMG)
        self._graph.set_tooltip_text(
            "Historial de temperaturas CPU/GPU y RPM de ambos ventiladores"
        )
        self._graph.set_draw_func(self._draw)
        self.append(self._graph)

        self._sync_legend_colors()

    def _sync_legend_colors(self) -> None:
        """Re-point the legend at the palette of the active colour scheme.

        Called on every refresh instead of from a GtkStyleManager signal: the
        style manager is a process-wide singleton and outlives this panel.
        """
        light = not Adw.StyleManager.get_default().get_dark()
        for label in self._legend_labels:
            if light:
                label.add_css_class("on-light")
            else:
                label.remove_css_class("on-light")

    @property
    def history(self) -> TelemetryHistory:
        return self._history

    def update_status(self, status: dict[str, object]) -> None:
        self._sync_legend_colors()
        self._history.append_status(status)
        try:
            self._archive.append_status(status)
        except OSError as error:
            self._show_error(translate("No se guardó el historial: {error}", error=error))
        count = len(self._history.samples)
        label, _ = HISTORY_WINDOWS[self._window_selector.get_selected()]
        self._subtitle.set_label(
            translate(
                "{count} lecturas · guardado local durante 7 días · vista {label}",
                count=count,
                label=translate(label),
            )
            if count
            else translate("Recopilando lecturas…")
        )
        self._graph.queue_draw()

    def record_event(self, label: str) -> None:
        timestamp = time.time()
        try:
            event = TelemetryEvent(timestamp, label)
            self._history.append_event(event)
            self._archive.append_event(label, timestamp=timestamp)
        except (OSError, ValueError) as error:
            self._show_error(translate("No se guardó el evento: {error}", error=error))
        self._graph.queue_draw()

    def _on_window_changed(self, _selector: Gtk.DropDown, _parameter: object) -> None:
        label, seconds = HISTORY_WINDOWS[self._window_selector.get_selected()]
        samples, events = self._archive.load(max_age_seconds=seconds)
        self._history.replace(
            max_age_seconds=seconds,
            samples=samples,
            events=events,
        )
        self._title.set_label(translate("Historial · {label}", label=translate(label)))
        self._subtitle.set_label(
            translate(
                "{count} lecturas · guardado local durante 7 días",
                count=len(samples),
            )
        )
        self._graph.queue_draw()

    def _on_export_clicked(self, _button: Gtk.Button) -> None:
        choose_save_path(
            self,
            title=translate("Exportar historial térmico"),
            suggested_name="legion-control-telemetria.csv",
            on_path=self._export_to,
            on_error=self._show_error,
        )

    def _export_to(self, path: Path) -> None:
        try:
            self._archive.export_csv(path)
        except OSError as error:
            self._show_error(translate("No se exportó el CSV: {error}", error=error))
            return
        self._show_message(translate("Historial CSV exportado."))

    def _draw(
        self,
        _area: Gtk.DrawingArea,
        context: Any,
        width: int,
        height: int,
    ) -> None:
        dark = Adw.StyleManager.get_default().get_dark()
        foreground = (0.94, 0.95, 0.97) if dark else (0.12, 0.13, 0.15)
        grid = (0.72, 0.74, 0.78) if dark else (0.20, 0.22, 0.26)
        series = SERIES_COLORS_DARK if dark else SERIES_COLORS_LIGHT
        samples = self._history.samples
        left, right, top, bottom = 42, 50, 14, 24
        graph_width = max(1, width - left - right)
        graph_height = max(1, height - top - bottom)

        context.set_line_width(1)
        context.set_source_rgba(*grid, 0.14)
        for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
            y = top + graph_height * fraction
            context.move_to(left, y)
            context.line_to(left + graph_width, y)
        for fraction in (0.0, 0.5, 1.0):
            x = left + graph_width * fraction
            context.move_to(x, top)
            context.line_to(x, top + graph_height)
        context.stroke()

        _draw_label(context, "100°", 5, top + 4, foreground)
        _draw_label(context, "30°", 10, top + graph_height, foreground)
        _draw_label(context, "6000", left + graph_width + 7, top + 4, foreground)
        _draw_label(
            context,
            "0 RPM",
            left + graph_width + 7,
            top + graph_height,
            foreground,
        )

        if len(samples) < 2:
            _draw_centered_message(
                context,
                translate("El gráfico aparecerá tras dos lecturas"),
                width,
                height,
                foreground,
            )
            return

        first_timestamp = samples[0].timestamp
        last_timestamp = samples[-1].timestamp
        duration = max(1.0, last_timestamp - first_timestamp)

        def x_position(sample: TelemetrySample) -> float:
            return left + ((sample.timestamp - first_timestamp) / duration) * graph_width

        _draw_series(
            context,
            samples,
            x_position,
            lambda sample: sample.cpu_temperature_c,
            lambda value: top + graph_height - ((value - 30) / 70) * graph_height,
            series["cpu"],
        )
        _draw_series(
            context,
            samples,
            x_position,
            lambda sample: sample.gpu_temperature_c,
            lambda value: top + graph_height - ((value - 30) / 70) * graph_height,
            series["gpu"],
        )
        _draw_series(
            context,
            samples,
            x_position,
            lambda sample: sample.fan1_rpm,
            lambda value: top + graph_height - (value / 6000) * graph_height,
            series["fan1"],
        )
        _draw_series(
            context,
            samples,
            x_position,
            lambda sample: sample.fan2_rpm,
            lambda value: top + graph_height - (value / 6000) * graph_height,
            series["fan2"],
        )
        _draw_events(
            context,
            self._history.events,
            first_timestamp,
            last_timestamp,
            left,
            top,
            graph_width,
            graph_height,
            foreground,
        )


def _draw_series(
    context: Any,
    samples: tuple[TelemetrySample, ...],
    x_position: Any,
    value_for: Any,
    y_position: Any,
    color: tuple[float, float, float],
) -> None:
    drawing = False
    context.set_source_rgba(*color, 0.92)
    context.set_line_width(2)
    for sample in samples:
        value = value_for(sample)
        if value is None:
            drawing = False
            continue
        x = x_position(sample)
        y = y_position(value)
        if drawing:
            context.line_to(x, y)
        else:
            context.move_to(x, y)
            drawing = True
    context.stroke()


def _draw_events(
    context: Any,
    events: tuple[TelemetryEvent, ...],
    first_timestamp: float,
    last_timestamp: float,
    left: int,
    top: int,
    graph_width: int,
    graph_height: int,
    foreground: tuple[float, float, float],
) -> None:
    duration = max(1.0, last_timestamp - first_timestamp)
    context.set_source_rgba(*foreground, 0.35)
    context.set_line_width(1)
    for event in events:
        if not first_timestamp <= event.timestamp <= last_timestamp:
            continue
        x = left + ((event.timestamp - first_timestamp) / duration) * graph_width
        context.move_to(x, top)
        context.line_to(x, top + graph_height)
    context.stroke()


def _draw_label(
    context: Any,
    text: str,
    x: float,
    y: float,
    color: tuple[float, float, float],
) -> None:
    context.set_source_rgba(*color, 0.58)
    context.set_font_size(10)
    context.move_to(x, y)
    context.show_text(text)


def _draw_centered_message(
    context: Any,
    text: str,
    width: int,
    height: int,
    color: tuple[float, float, float],
) -> None:
    context.set_font_size(12)
    extents = context.text_extents(text)
    context.set_source_rgba(*color, 0.5)
    context.move_to((width - extents.width) / 2, height / 2)
    context.show_text(text)
