"""GTK controls for explicitly enabled power-source scene automation."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gtk  # noqa: E402

from legion_control.automation import (  # noqa: E402
    AutomationConfig,
    AutomationStore,
    PowerSource,
    source_from_status,
)
from legion_control.i18n import translate  # noqa: E402
from legion_control.scenes import SceneSlot  # noqa: E402


SCENE_LABELS = ("Silencio", "Trabajo", "Juego")
SCENE_SLOTS = tuple(SceneSlot)


class AutomationPage(Adw.PreferencesPage):
    """Stores intent only; MainWindow applies a scene after a source transition."""

    def __init__(
        self,
        store: AutomationStore,
        show_error: Callable[[str], None],
        show_message: Callable[[str], None],
    ) -> None:
        super().__init__()
        self.add_css_class("control-page")
        self.set_title("Automatización")
        self.set_icon_name("preferences-system-time-symbolic")
        self._store = store
        self._show_error = show_error
        self._show_message = show_message
        self._configuration = AutomationConfig()
        self._refreshing = False
        self._loaded = False

        status_group = Adw.PreferencesGroup()
        status_group.set_title("Estado de energía")
        self._source_row = Adw.ActionRow()
        self._source_row.set_title("Fuente actual")
        self._source_value = Gtk.Label(label="Esperando lectura")
        self._source_value.add_css_class("measurement")
        self._source_row.add_suffix(self._source_value)
        status_group.add(self._source_row)
        self.add(status_group)

        controls = Adw.PreferencesGroup()
        controls.set_title("Escenas al cambiar fuente")
        controls.set_description(
            "Desactivado por defecto · funciona mientras Legion Control está abierto"
        )

        self._ac_enabled = Adw.SwitchRow()
        self._ac_enabled.set_title("Al conectar corriente")
        self._ac_enabled.set_subtitle("Aplica una escena guardada tras el cambio")
        self._ac_enabled.connect("notify::active", self._on_controls_changed)
        controls.add(self._ac_enabled)
        self._ac_scene = self._scene_row("Escena con corriente")
        controls.add(self._ac_scene)

        self._battery_enabled = Adw.SwitchRow()
        self._battery_enabled.set_title("Al usar batería")
        self._battery_enabled.set_subtitle("Aplica una escena guardada tras el cambio")
        self._battery_enabled.connect("notify::active", self._on_controls_changed)
        controls.add(self._battery_enabled)
        self._battery_scene = self._scene_row("Escena con batería")
        controls.add(self._battery_scene)
        self.add(controls)

    @property
    def configuration(self) -> AutomationConfig:
        return self._configuration

    def update_status(self, status: dict[str, object]) -> None:
        if not self._loaded:
            self._load()
        source = source_from_status(status)
        labels = {
            PowerSource.AC: translate("Corriente"),
            PowerSource.BATTERY: translate("Batería"),
            None: translate("No disponible"),
        }
        self._source_value.set_label(labels[source])

    def _scene_row(self, title: str) -> Adw.ComboRow:
        row = Adw.ComboRow()
        row.set_title(title)
        row.set_model(Gtk.StringList.new(tuple(translate(label) for label in SCENE_LABELS)))
        row.connect("notify::selected", self._on_controls_changed)
        return row

    def _load(self) -> None:
        try:
            configuration = self._store.load()
        except (OSError, ValueError) as error:
            self._show_error(translate("No se cargó la automatización: {error}", error=error))
            configuration = AutomationConfig()
        self._refreshing = True
        self._configuration = configuration
        self._ac_enabled.set_active(configuration.ac_enabled)
        self._ac_scene.set_selected(SCENE_SLOTS.index(configuration.ac_scene))
        self._battery_enabled.set_active(configuration.battery_enabled)
        self._battery_scene.set_selected(SCENE_SLOTS.index(configuration.battery_scene))
        self._refreshing = False
        self._loaded = True

    def _on_controls_changed(self, _widget: Gtk.Widget, _parameter: object) -> None:
        if self._refreshing or not self._loaded:
            return
        configuration = AutomationConfig(
            ac_enabled=self._ac_enabled.get_active(),
            ac_scene=SCENE_SLOTS[self._ac_scene.get_selected()],
            battery_enabled=self._battery_enabled.get_active(),
            battery_scene=SCENE_SLOTS[self._battery_scene.get_selected()],
        )
        try:
            self._store.save(configuration)
        except (OSError, ValueError) as error:
            self._show_error(translate("No se guardó la automatización: {error}", error=error))
            self._load()
            return
        self._configuration = configuration
        self._show_message(translate("Automatización guardada."))
