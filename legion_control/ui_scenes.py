"""Compact scene controls for Silencio, Trabajo and Juego."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gtk  # noqa: E402

from legion_control.client import ControlPort  # noqa: E402
from legion_control.config import policy_from_json  # noqa: E402
from legion_control.domain import FanMode  # noqa: E402
from legion_control.power import (  # noqa: E402
    CustomPowerLimits,
    power_limits_from_document,
)
from legion_control.rgb import (  # noqa: E402
    default_rgb_configuration,
    rgb_configuration_from_document,
)
from legion_control.scenes import (  # noqa: E402
    Scene,
    SceneSlot,
    SceneStore,
    default_scenes,
)


Operation = Callable[[], dict[str, object]]
MutationRunner = Callable[
    [Operation, str, Callable[[], None] | None, Callable[[], None] | None],
    None,
]

SCENE_LABELS = {
    SceneSlot.SILENCE: "Silencio",
    SceneSlot.WORK: "Trabajo",
    SceneSlot.GAME: "Juego",
}
SCENE_ICONS = {
    SceneSlot.SILENCE: "audio-volume-low-symbolic",
    SceneSlot.WORK: "document-edit-symbolic",
    SceneSlot.GAME: "applications-games-symbolic",
}


class ScenePanel(Adw.PreferencesGroup):
    def __init__(
        self,
        client: ControlPort,
        store: SceneStore,
        run_mutation: MutationRunner,
        request_refresh: Callable[[], None],
        show_error: Callable[[str], None],
        show_message: Callable[[str], None],
    ) -> None:
        super().__init__()
        self.set_title("Escenas rápidas")
        self.set_description("Perfil, ventilación, potencia y RGB con una acción")
        self._client = client
        self._store = store
        self._run_mutation = run_mutation
        self._request_refresh = request_refresh
        self._show_error = show_error
        self._show_message = show_message
        self._latest_status: dict[str, object] | None = None
        self._scenes: dict[SceneSlot, Scene] | None = None
        self._rgb_available = False
        self._rows: dict[SceneSlot, Adw.ActionRow] = {}
        self._apply_buttons: dict[SceneSlot, Gtk.Button] = {}
        self._save_buttons: dict[SceneSlot, Gtk.Button] = {}

        for slot in SceneSlot:
            row = Adw.ActionRow()
            row.set_title(SCENE_LABELS[slot])
            row.set_subtitle("Preparando escena…")
            row.add_prefix(
                Gtk.Image.new_from_icon_name(SCENE_ICONS[slot])
            )
            save = Gtk.Button.new_from_icon_name("document-save-symbolic")
            save.set_tooltip_text(
                f"Guardar estado actual en {SCENE_LABELS[slot]}"
            )
            save.set_valign(Gtk.Align.CENTER)
            save.connect("clicked", self._on_save_clicked, slot)
            apply = Gtk.Button(label="Aplicar")
            apply.add_css_class("suggested-action")
            apply.set_valign(Gtk.Align.CENTER)
            apply.connect("clicked", self._on_apply_clicked, slot)
            row.add_suffix(save)
            row.add_suffix(apply)
            self.add(row)
            self._rows[slot] = row
            self._save_buttons[slot] = save
            self._apply_buttons[slot] = apply

    def update_status(self, status: dict[str, object]) -> None:
        self._latest_status = status
        capabilities = _dictionary(status.get("capabilities"))
        self._rgb_available = bool(capabilities.get("rgb_control"))
        if self._scenes is None:
            power_limits = _power_limits_from_status(status, capabilities)
            try:
                defaults = default_scenes(power_limits)
                self._scenes = self._store.load_or_defaults(defaults)
            except (OSError, ValueError) as error:
                self._scenes = default_scenes(power_limits)
                self._show_error(f"No se cargaron las escenas: {error}")
        for slot, scene in self._scenes.items():
            self._rows[slot].set_subtitle(_scene_summary(scene))
            self._apply_buttons[slot].set_sensitive(True)
            self._save_buttons[slot].set_sensitive(True)

    def _on_apply_clicked(
        self,
        _button: Gtk.Button,
        slot: SceneSlot,
    ) -> None:
        if self._scenes is None:
            return
        scene = self._scenes[slot]
        self._set_buttons_sensitive(False)

        def apply_scene() -> dict[str, object]:
            if self._rgb_available:
                self._client.set_rgb_configuration(scene.rgb_configuration)
            if scene.fan_policy.mode is FanMode.AUTO:
                return self._client.set_profile(scene.profile)
            if scene.power_limits is None:
                raise ValueError("La escena Custom no contiene límites de potencia.")
            return self._client.set_custom_configuration(
                scene.fan_policy,
                scene.power_limits,
            )

        self._run_mutation(
            apply_scene,
            f"Escena {SCENE_LABELS[slot]} aplicada.",
            self._finish_apply,
            self._finish_apply,
        )

    def _on_save_clicked(
        self,
        _button: Gtk.Button,
        slot: SceneSlot,
    ) -> None:
        if self._latest_status is None or self._scenes is None:
            return
        try:
            scene = _scene_from_status(
                slot,
                self._latest_status,
                self._scenes[slot],
            )
            self._scenes[slot] = scene
            self._store.save(self._scenes)
        except (OSError, ValueError) as error:
            self._show_error(f"No se guardó la escena: {error}")
            return
        self._rows[slot].set_subtitle(_scene_summary(scene))
        self._show_message(
            f"Estado actual guardado en {SCENE_LABELS[slot]}."
        )

    def _finish_apply(self) -> None:
        self._set_buttons_sensitive(True)
        self._request_refresh()

    def _set_buttons_sensitive(self, sensitive: bool) -> None:
        for button in (*self._apply_buttons.values(), *self._save_buttons.values()):
            button.set_sensitive(sensitive)


def _scene_from_status(
    slot: SceneSlot,
    status: dict[str, object],
    previous_scene: Scene,
) -> Scene:
    profile = status.get("profile")
    if not isinstance(profile, str):
        raise ValueError("No se puede leer el perfil actual.")
    policy_document = status.get("fan_policy")
    if not isinstance(policy_document, dict):
        raise ValueError("No se puede leer la ventilación actual.")
    fan_policy = policy_from_json(
        json.dumps(
            {"version": 1, **policy_document},
            ensure_ascii=False,
        )
    )
    power_limits = None
    if fan_policy.mode is not FanMode.AUTO:
        if profile != "custom":
            raise ValueError("La ventilación manual no está confirmada como Custom.")
        power_document = status.get("power_limits")
        power_limits = power_limits_from_document(power_document)
    elif profile == "custom":
        raise ValueError(
            "Custom sin ventilación manual no forma una escena completa."
        )
    rgb_document = status.get("rgb_configuration")
    rgb_configuration = (
        rgb_configuration_from_document(rgb_document)
        if isinstance(rgb_document, dict)
        else previous_scene.rgb_configuration
    )
    return Scene(
        slot=slot,
        profile=profile,
        fan_policy=fan_policy,
        power_limits=power_limits,
        rgb_configuration=rgb_configuration,
    )


def _power_limits_from_status(
    status: dict[str, object],
    capabilities: dict[str, Any],
) -> CustomPowerLimits:
    current = status.get("power_limits")
    if isinstance(current, dict):
        try:
            return power_limits_from_document(current)
        except ValueError:
            pass
    bounds = _dictionary(capabilities.get("power_limits"))
    sustained = _dictionary(bounds.get("sustained")).get("default_w")
    slow = _dictionary(bounds.get("slow")).get("default_w")
    if type(sustained) is int and type(slow) is int:
        return CustomPowerLimits(sustained, slow)
    return CustomPowerLimits(70, 125)


def _scene_summary(scene: Scene) -> str:
    if scene.fan_policy.mode is FanMode.AUTO:
        fan = "firmware"
    elif scene.fan_policy.mode is FanMode.CURVE:
        fan = "curva"
    else:
        fan = f"{scene.fan_policy.fixed_rpm} RPM"
    power = (
        f" · {scene.power_limits.sustained_w}/{scene.power_limits.slow_w} W"
        if scene.power_limits is not None
        else ""
    )
    rgb = "RGB" if scene.rgb_configuration.enabled else "RGB apagado"
    return f"{scene.profile} · {fan}{power} · {rgb}"


def _dictionary(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
