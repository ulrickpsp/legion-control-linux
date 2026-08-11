"""GTK page for the exact 24-zone RGB keyboard."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from legion_control.client import ControlPort  # noqa: E402
from legion_control.i18n import translate  # noqa: E402
from legion_control.rgb import (  # noqa: E402
    RGB_ZONE_COUNT,
    RgbColor,
    RgbConfiguration,
    alternating_rgb_configuration,
    default_rgb_configuration,
    gradient_rgb_configuration,
    rgb_configuration_from_document,
    solid_rgb_configuration,
    wave_rgb_configuration,
)


# Long enough to swallow a slider drag, short enough to feel immediate.
WRITE_DELAY_MS = 400

Operation = Callable[[], dict[str, object]]
MutationRunner = Callable[
    [Operation, str, Callable[[], None] | None, Callable[[], None] | None],
    None,
]


class ZoneSwatch(Gtk.ToggleButton):
    def __init__(
        self,
        zone_index: int,
        on_selected: Callable[[int], None],
    ) -> None:
        super().__init__()
        self._zone_index = zone_index
        self._color = RgbColor(0, 0, 0)
        self.set_tooltip_text(translate("Editar zona {index}", index=zone_index + 1))
        self.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [translate("Zona RGB {index}", index=zone_index + 1)],
        )
        self.add_css_class("zone-swatch")
        drawing = Gtk.DrawingArea()
        drawing.set_content_width(54)
        drawing.set_content_height(36)
        drawing.set_draw_func(self._draw)
        self.set_child(drawing)
        self.connect("toggled", self._on_toggled, on_selected)

    def set_color(self, color: RgbColor) -> None:
        self._color = color
        child = self.get_child()
        if isinstance(child, Gtk.DrawingArea):
            child.queue_draw()

    def _on_toggled(
        self,
        _button: Gtk.ToggleButton,
        on_selected: Callable[[int], None],
    ) -> None:
        if self.get_active():
            on_selected(self._zone_index)

    def _draw(
        self,
        _area: Gtk.DrawingArea,
        context: Any,
        width: int,
        height: int,
    ) -> None:
        red = self._color.red / 255
        green = self._color.green / 255
        blue = self._color.blue / 255
        context.set_source_rgb(red, green, blue)
        _rounded_rectangle(context, 3, 3, width - 6, height - 6, 8)
        context.fill()
        luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
        if luminance > 0.55:
            context.set_source_rgb(0.08, 0.08, 0.09)
        else:
            context.set_source_rgb(0.97, 0.97, 0.98)
        label = str(self._zone_index + 1)
        context.set_font_size(11)
        extents = context.text_extents(label)
        context.move_to(
            (width - extents.width) / 2,
            (height + extents.height) / 2,
        )
        context.show_text(label)


class LightingPage(Adw.PreferencesPage):
    def __init__(
        self,
        client: ControlPort,
        run_mutation: MutationRunner,
        request_refresh: Callable[[], None],
        show_error: Callable[[str], None],
    ) -> None:
        super().__init__()
        self.add_css_class("control-page")
        self.set_title("Iluminación")
        self.set_icon_name("preferences-color-symbolic")
        self._client = client
        self._run_mutation = run_mutation
        self._request_refresh = request_refresh
        self._show_error = show_error
        self._available = False
        self._refreshing = False
        self._pending_write = False
        self._write_in_flight = False
        self._write_failed = False
        self._write_timeout_id = 0
        self._selected_zone = 0
        self._zones = list(default_rgb_configuration().zones)

        status_group = Adw.PreferencesGroup()
        hero = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        hero.add_css_class("lighting-hero")
        icon = Gtk.Image.new_from_icon_name("preferences-color-symbolic")
        icon.set_pixel_size(28)
        icon.add_css_class("device-mark")
        hero.append(icon)
        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        copy.set_hexpand(True)
        title = Gtk.Label(label="Teclado RGB · 24 zonas", xalign=0)
        title.add_css_class("device-name")
        self._status_copy = Gtk.Label(
            label="Detectando controlador HID…",
            xalign=0,
        )
        self._status_copy.add_css_class("hero-subtitle")
        copy.append(title)
        copy.append(self._status_copy)
        hero.append(copy)
        self._status_pill = Gtk.Label(label="Detectando")
        self._status_pill.add_css_class("status-pill")
        hero.append(self._status_pill)
        status_group.add(hero)
        self.add(status_group)

        controls = Adw.PreferencesGroup()
        controls.set_title("Control")
        controls.set_description("Se aplica solo, poco después de cada cambio")
        self._controls_group = controls

        self._enabled_row = Adw.SwitchRow()
        self._enabled_row.set_title("Iluminación")
        self._enabled_row.set_subtitle("Apaga sin perder colores guardados")
        self._enabled_row.connect("notify::active", self._on_enabled_changed)
        controls.add(self._enabled_row)

        brightness_row = Adw.ActionRow()
        brightness_row.set_title("Brillo")
        self._brightness = Gtk.Adjustment(
            value=60,
            lower=0,
            upper=100,
            step_increment=1,
            page_increment=10,
        )
        self._brightness.connect("value-changed", self._on_brightness_changed)
        scale = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL,
            adjustment=self._brightness,
        )
        scale.set_draw_value(False)
        scale.set_size_request(220, -1)
        scale.update_property(
            [Gtk.AccessibleProperty.LABEL],
            ["Brillo del teclado en por ciento"],
        )
        self._brightness_value = Gtk.Label(label="60 %")
        self._brightness_value.add_css_class("measurement")
        brightness_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=10,
        )
        brightness_box.append(scale)
        brightness_box.append(self._brightness_value)
        brightness_row.add_suffix(brightness_box)
        controls.add(brightness_row)

        color_row = Adw.ActionRow()
        color_row.set_title("Color de zona")
        color_row.set_subtitle("Selecciona una zona o aplica el color a todas")
        color_dialog = Gtk.ColorDialog()
        color_dialog.set_with_alpha(False)
        self._color_button = Gtk.ColorDialogButton(dialog=color_dialog)
        self._color_button.update_property(
            [Gtk.AccessibleProperty.LABEL],
            ["Color de la zona seleccionada"],
        )
        all_button = Gtk.Button(label="Aplicar a todas")
        all_button.connect("clicked", self._on_apply_color_to_all)
        color_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        color_box.append(self._color_button)
        color_box.append(all_button)
        color_row.add_suffix(color_box)
        controls.add(color_row)
        self.add(controls)

        zones_group = Adw.PreferencesGroup()
        zones_group.set_title("Zonas")
        zones_group.set_description("Selecciona una de las 24 zonas y cambia su color")
        self._zones_group = zones_group
        zone_grid = Gtk.Grid(column_spacing=6, row_spacing=6)
        zone_grid.set_column_homogeneous(True)
        zone_grid.add_css_class("zone-grid")
        self._zone_buttons: list[ZoneSwatch] = []
        for zone_index in range(RGB_ZONE_COUNT):
            button = ZoneSwatch(zone_index, self._select_zone)
            zone_grid.attach(button, zone_index % 8, zone_index // 8, 1, 1)
            self._zone_buttons.append(button)
        self._zone_buttons[0].set_active(True)
        zones_group.add(zone_grid)
        self.add(zones_group)

        presets = Adw.PreferencesGroup()
        presets.set_title("Presets y efectos estáticos")
        presets.set_description(
            "Un solo frame verificado; no activa animaciones de firmware no comprobadas"
        )
        self._presets_group = presets
        # A flow box so the row wraps instead of squeezing buttons below their
        # minimum width once the list outgrows one line.
        preset_box = Gtk.FlowBox()
        preset_box.add_css_class("preset-box")
        preset_box.set_selection_mode(Gtk.SelectionMode.NONE)
        preset_box.set_homogeneous(True)
        preset_box.set_min_children_per_line(2)
        # Four columns keep every label, including the longest, above its
        # minimum width at the narrowest supported desktop.
        preset_box.set_max_children_per_line(4)
        preset_box.set_row_spacing(8)
        preset_box.set_column_spacing(8)
        for label, preset in (
            ("Legion", self._preset_legion),
            ("Blanco", self._preset_white),
            ("Espectro", self._preset_spectrum),
            ("Atardecer", self._preset_sunset),
            ("Ola", self._preset_wave),
            ("Hielo", self._preset_ice),
            ("Bosque", self._preset_forest),
            ("Neón", self._preset_neon),
            ("Brasa", self._preset_ember),
            ("Nocturno", self._preset_night),
            ("Ajedrez", self._preset_checker),
            ("Apagar", self._preset_off),
        ):
            button = Gtk.Button(label=label)
            button.set_hexpand(True)
            button.connect("clicked", lambda _button, action=preset: action())
            preset_box.append(button)
        presets.add(preset_box)
        self.add(presets)

        self._color_button.connect("notify::rgba", self._on_color_selected)
        self._load_configuration(default_rgb_configuration())

    def update_status(self, status: dict[str, object]) -> None:
        capabilities = _dictionary(status.get("capabilities"))
        self._available = bool(capabilities.get("rgb_control"))
        known = bool(status.get("rgb_configuration_known"))
        document = status.get("rgb_configuration")
        settled = not self._pending_write and not self._write_in_flight and not self._write_failed
        if settled and known and isinstance(document, dict):
            try:
                self._load_configuration(rgb_configuration_from_document(document))
            except ValueError:
                known = False
        if not self._available:
            self._status_pill.set_label(translate("No disponible"))
            self._status_copy.set_label(
                translate("No aparece 048d:c195 en la interfaz HID esperada")
            )
        elif known:
            self._status_pill.set_label(translate("Aplicado"))
            self._status_copy.set_label(translate("Configuración confirmada por el helper local"))
        else:
            self._status_pill.set_label(translate("Detectado"))
            self._status_copy.set_label(
                translate("Controlador listo · aplica un preset para sincronizar")
            )
        self._set_controls_sensitive(self._available)

    def current_configuration(self) -> RgbConfiguration:
        return RgbConfiguration(
            enabled=self._enabled_row.get_active(),
            brightness_percent=round(self._brightness.get_value()),
            zones=tuple(self._zones),
        )

    def _load_configuration(self, configuration: RgbConfiguration) -> None:
        self._refreshing = True
        self._enabled_row.set_active(configuration.enabled)
        self._brightness.set_value(configuration.brightness_percent)
        self._zones = list(configuration.zones)
        for button, color in zip(
            self._zone_buttons,
            self._zones,
            strict=True,
        ):
            button.set_color(color)
        self._sync_color_button()
        self._refreshing = False

    def _select_zone(self, zone_index: int) -> None:
        self._selected_zone = zone_index
        for index, button in enumerate(self._zone_buttons):
            if index != zone_index and button.get_active():
                button.set_active(False)
        self._sync_color_button()

    def _sync_color_button(self) -> None:
        color = self._zones[self._selected_zone]
        rgba = Gdk.RGBA()
        rgba.red = color.red / 255
        rgba.green = color.green / 255
        rgba.blue = color.blue / 255
        rgba.alpha = 1
        self._color_button.set_rgba(rgba)

    def _on_color_selected(
        self,
        _button: Gtk.ColorDialogButton,
        _parameter: object,
    ) -> None:
        if self._refreshing:
            return
        rgba = self._color_button.get_rgba()
        color = RgbColor(
            round(rgba.red * 255),
            round(rgba.green * 255),
            round(rgba.blue * 255),
        )
        self._zones[self._selected_zone] = color
        self._zone_buttons[self._selected_zone].set_color(color)
        self._schedule_write()

    def _on_apply_color_to_all(self, _button: Gtk.Button) -> None:
        color = self._zones[self._selected_zone]
        self._set_all_zones(color)

    def _on_enabled_changed(
        self,
        _row: Adw.SwitchRow,
        _parameter: object,
    ) -> None:
        if not self._refreshing:
            self._schedule_write()

    def _on_brightness_changed(self, adjustment: Gtk.Adjustment) -> None:
        self._brightness_value.set_label(f"{adjustment.get_value():.0f} %")
        if not self._refreshing:
            self._schedule_write()

    def _preset_legion(self) -> None:
        self._set_preset(solid_rgb_configuration(RgbColor(229, 32, 47), 70))

    def _preset_white(self) -> None:
        self._set_preset(solid_rgb_configuration(RgbColor(235, 239, 245), 45))

    def _preset_spectrum(self) -> None:
        self._set_preset(wave_rgb_configuration(70))

    def _preset_sunset(self) -> None:
        self._set_preset(
            gradient_rgb_configuration(
                RgbColor(247, 137, 55),
                RgbColor(119, 46, 181),
                65,
            )
        )

    def _preset_wave(self) -> None:
        configuration = wave_rgb_configuration(70)
        rotated = RgbConfiguration(
            configuration.enabled,
            configuration.brightness_percent,
            configuration.zones[6:] + configuration.zones[:6],
        )
        self._set_preset(rotated)

    def _preset_ice(self) -> None:
        self._set_preset(
            gradient_rgb_configuration(RgbColor(79, 216, 245), RgbColor(234, 246, 255), 55)
        )

    def _preset_forest(self) -> None:
        self._set_preset(
            gradient_rgb_configuration(RgbColor(18, 112, 58), RgbColor(156, 224, 91), 60)
        )

    def _preset_neon(self) -> None:
        self._set_preset(
            gradient_rgb_configuration(RgbColor(255, 47, 176), RgbColor(0, 229, 255), 75)
        )

    def _preset_ember(self) -> None:
        self._set_preset(
            gradient_rgb_configuration(RgbColor(140, 16, 7), RgbColor(255, 176, 32), 65)
        )

    def _preset_night(self) -> None:
        """A dim warm frame for working in the dark without glare."""
        self._set_preset(solid_rgb_configuration(RgbColor(255, 155, 61), 15))

    def _preset_checker(self) -> None:
        self._set_preset(
            alternating_rgb_configuration(RgbColor(229, 32, 47), RgbColor(12, 12, 14), 70)
        )

    def _preset_off(self) -> None:
        configuration = self.current_configuration()
        self._set_preset(
            RgbConfiguration(False, configuration.brightness_percent, configuration.zones)
        )

    def _set_preset(self, configuration: RgbConfiguration) -> None:
        """Take the preset's colours, keep the brightness the user chose."""
        self._load_configuration(
            RgbConfiguration(
                configuration.enabled,
                round(self._brightness.get_value()),
                configuration.zones,
            )
        )
        self._schedule_write()

    def _set_all_zones(self, color: RgbColor) -> None:
        self._zones = [color] * RGB_ZONE_COUNT
        for button in self._zone_buttons:
            button.set_color(color)
        self._schedule_write()

    def _schedule_write(self) -> None:
        """Coalesce edits into one write shortly after the user stops.

        Every write crosses PolicyKit into the privileged helper and sends
        960-byte HID reports, so dragging the brightness slider must not turn
        into one write per pixel.
        """

        self._pending_write = True
        if self._write_timeout_id:
            GLib.source_remove(self._write_timeout_id)
        self._write_timeout_id = GLib.timeout_add(WRITE_DELAY_MS, self._flush_write)

    def _flush_write(self) -> bool:
        self._write_timeout_id = 0
        if self._write_in_flight or not self._available:
            return GLib.SOURCE_REMOVE
        try:
            configuration = self.current_configuration()
        except ValueError as error:
            self._show_error(str(error))
            return GLib.SOURCE_REMOVE
        self._pending_write = False
        self._write_in_flight = True
        self._run_mutation(
            lambda: self._client.set_rgb_configuration(configuration),
            translate("Iluminación aplicada en las 24 zonas."),
            self._write_succeeded,
            self._write_failed_once,
        )
        return GLib.SOURCE_REMOVE

    def _write_succeeded(self) -> None:
        self._write_in_flight = False
        self._write_failed = False
        # An edit made while the helper was busy still has to reach the keyboard.
        if self._pending_write:
            self._schedule_write()
        else:
            self._request_refresh()

    def _write_failed_once(self) -> None:
        """Keep the colours on screen so a refresh cannot discard them.

        Without this the next status poll would overwrite the user's edit with
        whatever the keyboard last accepted. It does not retry on its own: a
        failing helper would turn into an endless write loop.
        """

        self._write_in_flight = False
        self._write_failed = True

    def _set_controls_sensitive(self, sensitive: bool) -> None:
        self._controls_group.set_sensitive(sensitive)
        self._zones_group.set_sensitive(sensitive)
        self._presets_group.set_sensitive(sensitive)


def _rounded_rectangle(
    context: Any,
    x: float,
    y: float,
    width: float,
    height: float,
    radius: float,
) -> None:
    context.new_sub_path()
    context.arc(x + width - radius, y + radius, radius, -1.57, 0)
    context.arc(x + width - radius, y + height - radius, radius, 0, 1.57)
    context.arc(x + radius, y + height - radius, radius, 1.57, 3.14)
    context.arc(x + radius, y + radius, radius, 3.14, 4.71)
    context.close_path()


def _dictionary(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
