"""Native graph for the last ten minutes of thermal telemetry."""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gtk  # noqa: E402

from legion_control.history import TelemetryHistory, TelemetrySample  # noqa: E402


class TelemetryHistoryPanel(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add_css_class("history-panel")
        self._history = TelemetryHistory()

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        copy.set_hexpand(True)
        title = Gtk.Label(label="Últimos 10 minutos", xalign=0)
        title.add_css_class("history-title")
        self._subtitle = Gtk.Label(label="Recopilando lecturas…", xalign=0)
        self._subtitle.add_css_class("hero-subtitle")
        copy.append(title)
        copy.append(self._subtitle)
        header.append(copy)

        legend = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
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
        header.append(legend)
        self.append(header)

        self._graph = Gtk.DrawingArea()
        self._graph.set_content_height(170)
        self._graph.set_hexpand(True)
        self._graph.set_accessible_role(Gtk.AccessibleRole.IMG)
        self._graph.set_tooltip_text(
            "Historial de temperaturas CPU/GPU y RPM de ambos ventiladores"
        )
        self._graph.set_draw_func(self._draw)
        self.append(self._graph)

    @property
    def history(self) -> TelemetryHistory:
        return self._history

    def update_status(self, status: dict[str, object]) -> None:
        self._history.append_status(status)
        count = len(self._history.samples)
        self._subtitle.set_label(
            f"{count} lecturas · se reinicia al cerrar"
            if count
            else "Recopilando lecturas…"
        )
        self._graph.queue_draw()

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
                "El gráfico aparecerá tras dos lecturas",
                width,
                height,
                foreground,
            )
            return

        first_timestamp = samples[0].timestamp
        last_timestamp = samples[-1].timestamp
        duration = max(1.0, last_timestamp - first_timestamp)

        def x_position(sample: TelemetrySample) -> float:
            return left + (
                (sample.timestamp - first_timestamp) / duration
            ) * graph_width

        _draw_series(
            context,
            samples,
            x_position,
            lambda sample: sample.cpu_temperature_c,
            lambda value: top + graph_height - ((value - 30) / 70) * graph_height,
            (0.96, 0.62, 0.16),
        )
        _draw_series(
            context,
            samples,
            x_position,
            lambda sample: sample.gpu_temperature_c,
            lambda value: top + graph_height - ((value - 30) / 70) * graph_height,
            (0.90, 0.20, 0.25),
        )
        _draw_series(
            context,
            samples,
            x_position,
            lambda sample: sample.fan1_rpm,
            lambda value: top + graph_height - (value / 6000) * graph_height,
            (0.20, 0.72, 0.84),
        )
        _draw_series(
            context,
            samples,
            x_position,
            lambda sample: sample.fan2_rpm,
            lambda value: top + graph_height - (value / 6000) * graph_height,
            (0.48, 0.52, 0.95),
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
