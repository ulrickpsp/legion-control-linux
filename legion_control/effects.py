"""Deterministic animated frames for the verified 24-zone static transport.

Every effect is a pure function of its settings and the elapsed time, so a frame
can be asserted in a test, reproduced after a daemon restart, and reasoned about
without hardware. Nothing here talks to the controller: an effect is rendered
into an ordinary :class:`~legion_control.rgb.RgbConfiguration` and written with
the same physically validated report sequence as a static preset. No firmware
animation command is claimed or sent.

Perceived brightness is not linear in the value written to an LED, so the
intensity ramps below are gamma-shaped. A linear fade reads as a fast drop
followed by a long dim tail, which looks broken rather than smooth.
"""

from __future__ import annotations

import colorsys
import json
import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Final

from legion_control.rgb import (
    RGB_ZONE_COUNT,
    RgbColor,
    RgbConfiguration,
    write_text_atomically,
)


EFFECT_CONFIG_VERSION: Final = 1
MAX_EFFECT_CONFIG_BYTES: Final = 1024

# Speed 1 crawls, speed 100 is fast without strobing. The bounds are deliberate:
# below roughly one second per cycle the 24 zones read as flicker, not motion.
SLOWEST_CYCLE_SECONDS: Final = 14.0
FASTEST_CYCLE_SECONDS: Final = 1.1

TAU: Final = math.tau

EXPECTED_EFFECT_KEYS: Final = frozenset(
    {"version", "kind", "speed_percent", "brightness_percent", "color", "enabled"}
)
EXPECTED_COLOR_KEYS: Final = frozenset({"red", "green", "blue"})


class EffectKind(Enum):
    """The animations this project renders itself, frame by frame."""

    BREATHING = "breathing"
    RAINBOW = "rainbow"
    WAVE = "wave"
    COMET = "comet"
    FIRE = "fire"
    AURORA = "aurora"


# Effects that paint their own palette ignore the chosen colour. The UI uses
# this to stop offering a colour that would have no visible effect.
COLOR_AWARE_KINDS: Final = frozenset({EffectKind.BREATHING, EffectKind.WAVE, EffectKind.COMET})


@dataclass(frozen=True, slots=True)
class EffectSettings:
    kind: EffectKind
    speed_percent: int
    brightness_percent: int
    color: RgbColor
    enabled: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EffectKind):
            raise ValueError("El efecto debe ser uno de los definidos.")
        if type(self.enabled) is not bool:
            raise ValueError("El estado del efecto debe ser booleano.")
        if type(self.speed_percent) is not int:
            raise ValueError("La velocidad del efecto debe ser un entero.")
        if not 1 <= self.speed_percent <= 100:
            raise ValueError("La velocidad del efecto debe estar entre 1 y 100.")
        if type(self.brightness_percent) is not int:
            raise ValueError("El brillo del efecto debe ser un entero.")
        if not 0 <= self.brightness_percent <= 100:
            raise ValueError("El brillo del efecto debe estar entre 0 y 100.")
        if not isinstance(self.color, RgbColor):
            raise ValueError("El efecto necesita un color válido.")

    @property
    def cycle_seconds(self) -> float:
        """Seconds for one full loop of the animation."""

        fraction = (self.speed_percent - 1) / 99
        return SLOWEST_CYCLE_SECONDS + (FASTEST_CYCLE_SECONDS - SLOWEST_CYCLE_SECONDS) * fraction

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "speed_percent": self.speed_percent,
            "brightness_percent": self.brightness_percent,
            "color": self.color.to_dict(),
            "enabled": self.enabled,
        }


def default_effect_settings() -> EffectSettings:
    return EffectSettings(
        kind=EffectKind.RAINBOW,
        speed_percent=45,
        brightness_percent=70,
        color=RgbColor(229, 32, 47),
        enabled=False,
    )


def effect_zones(settings: EffectSettings, elapsed_seconds: float) -> tuple[RgbColor, ...]:
    """Render one frame. Pure: the same inputs always give the same 24 colours."""

    if elapsed_seconds < 0:
        raise ValueError("El tiempo transcurrido no puede ser negativo.")
    phase = (elapsed_seconds / settings.cycle_seconds) % 1.0
    renderer = _RENDERERS[settings.kind]
    return tuple(renderer(settings.color, phase, zone) for zone in range(RGB_ZONE_COUNT))


def effect_frame(settings: EffectSettings, elapsed_seconds: float) -> RgbConfiguration:
    """Render one frame as a configuration the verified writer accepts."""

    return RgbConfiguration(
        enabled=settings.enabled,
        brightness_percent=settings.brightness_percent,
        zones=effect_zones(settings, elapsed_seconds),
    )


def _breathing(color: RgbColor, phase: float, _zone: int) -> RgbColor:
    """The whole keyboard pulses on one colour."""

    level = 0.5 - 0.5 * math.cos(TAU * phase)
    return _scale(color, 0.10 + 0.90 * level**2.2)


def _rainbow(_color: RgbColor, phase: float, zone: int) -> RgbColor:
    """A full spectrum scrolling across the 24 zones."""

    return _from_hsv((zone / RGB_ZONE_COUNT + phase) % 1.0, 0.95, 1.0)


def _wave(color: RgbColor, phase: float, zone: int) -> RgbColor:
    """A bright crest travelling over a dim bed of the chosen colour."""

    crest_width = 0.24
    offset = ((zone / RGB_ZONE_COUNT) - phase) % 1.0
    distance = min(offset, 1.0 - offset)
    intensity = _smoothstep(max(0.0, 1.0 - distance / crest_width))
    lit = _scale(color, 0.14 + 0.86 * intensity)
    # The very crest washes toward white so the wave reads as light, not colour.
    return _blend(lit, RgbColor(255, 255, 255), 0.45 * intensity**3)


def _comet(color: RgbColor, phase: float, zone: int) -> RgbColor:
    """A head bouncing across the keyboard, trailing a decaying tail."""

    head = _triangle(phase) * (RGB_ZONE_COUNT - 1)
    intensity = 0.55 ** abs(zone - head)
    lit = _scale(color, intensity)
    return _blend(lit, RgbColor(255, 255, 255), 0.6 * max(0.0, intensity - 0.8) / 0.2)


def _fire(_color: RgbColor, phase: float, zone: int) -> RgbColor:
    """Warm flicker from layered sines, so it is random-looking but reproducible."""

    # The dominant term is spatially slow so neighbouring zones stay related, as
    # a flame does; the faster terms only add flicker on top of it.
    intensity = _clamp(
        0.5
        + 0.28 * math.sin(TAU * (phase + zone * 0.13))
        + 0.15 * math.sin(TAU * (phase * 1.73 + zone * 0.31 + 0.37))
        + 0.07 * math.sin(TAU * (phase * 2.61 + zone * 0.67 + 0.71))
    )
    return RgbColor(
        round(255 * _clamp(intensity * 1.7)),
        round(255 * _clamp((intensity - 0.22) / 0.62) ** 1.7),
        round(255 * _clamp((intensity - 0.86) / 0.14) ** 2.2),
    )


def _aurora(_color: RgbColor, phase: float, zone: int) -> RgbColor:
    """Slow curtains drifting through green, cyan and violet."""

    span = zone / RGB_ZONE_COUNT
    hue = (
        0.45
        + 0.17 * math.sin(TAU * (phase * 0.62 + span * 1.1))
        + 0.08 * math.sin(TAU * (phase * 0.31 - span * 0.7 + 0.25))
    )
    value = 0.30 + 0.70 * (0.5 + 0.5 * math.sin(TAU * (phase + span * 1.4))) ** 1.8
    return _from_hsv(hue % 1.0, 0.88, value)


_RENDERERS: Final = {
    EffectKind.BREATHING: _breathing,
    EffectKind.RAINBOW: _rainbow,
    EffectKind.WAVE: _wave,
    EffectKind.COMET: _comet,
    EffectKind.FIRE: _fire,
    EffectKind.AURORA: _aurora,
}


def _scale(color: RgbColor, factor: float) -> RgbColor:
    factor = _clamp(factor)
    return RgbColor(
        round(color.red * factor),
        round(color.green * factor),
        round(color.blue * factor),
    )


def _blend(first: RgbColor, second: RgbColor, weight: float) -> RgbColor:
    weight = _clamp(weight)
    return RgbColor(
        round(first.red + (second.red - first.red) * weight),
        round(first.green + (second.green - first.green) * weight),
        round(first.blue + (second.blue - first.blue) * weight),
    )


def _from_hsv(hue: float, saturation: float, value: float) -> RgbColor:
    red, green, blue = colorsys.hsv_to_rgb(hue, saturation, _clamp(value))
    return RgbColor(round(red * 255), round(green * 255), round(blue * 255))


def _triangle(phase: float) -> float:
    """Ramp 0 to 1 and back, so a bouncing head never jumps at the wrap."""

    return 1.0 - abs(2.0 * (phase % 1.0) - 1.0)


def _smoothstep(value: float) -> float:
    value = _clamp(value)
    return value * value * (3.0 - 2.0 * value)


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


@dataclass(slots=True)
class EffectConfigStore:
    path: Path
    mode: int = 0o644

    def load(self) -> EffectSettings | None:
        if not self.path.exists():
            return None
        if self.path.stat().st_size > MAX_EFFECT_CONFIG_BYTES:
            raise ValueError("La configuración de efectos es demasiado grande.")
        return effect_settings_from_json(self.path.read_text(encoding="utf-8"))

    def save(self, settings: EffectSettings) -> None:
        write_text_atomically(
            self.path,
            effect_settings_to_json(settings) + "\n",
            mode=self.mode,
            prefix=".rgb-effect-",
        )

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


def effect_settings_to_json(settings: EffectSettings) -> str:
    payload = json.dumps(
        {"version": EFFECT_CONFIG_VERSION, **settings.to_dict()},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(payload.encode("utf-8")) > MAX_EFFECT_CONFIG_BYTES:
        raise ValueError("La configuración de efectos es demasiado grande.")
    return payload


def effect_settings_from_json(payload: str) -> EffectSettings:
    if len(payload.encode("utf-8")) > MAX_EFFECT_CONFIG_BYTES:
        raise ValueError("La configuración de efectos es demasiado grande.")
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ValueError(f"JSON de efectos inválido: {error.msg}.") from error
    if not isinstance(document, dict):
        raise ValueError("La configuración de efectos debe ser un objeto.")
    if frozenset(document) != EXPECTED_EFFECT_KEYS:
        raise ValueError("La configuración de efectos contiene claves incorrectas.")
    if document["version"] != EFFECT_CONFIG_VERSION:
        raise ValueError(f"Solo se admiten efectos versión {EFFECT_CONFIG_VERSION}.")
    if type(document["enabled"]) is not bool:
        raise ValueError("El estado del efecto debe ser booleano.")
    return EffectSettings(
        kind=_kind_from_document(document["kind"]),
        speed_percent=_require_integer(document["speed_percent"], "velocidad"),
        brightness_percent=_require_integer(document["brightness_percent"], "brillo"),
        color=_color_from_document(document["color"]),
        enabled=document["enabled"],
    )


def effect_settings_from_document(document: Any) -> EffectSettings:
    if not isinstance(document, dict):
        raise ValueError("La configuración de efectos debe ser un objeto.")
    return effect_settings_from_json(
        json.dumps({"version": EFFECT_CONFIG_VERSION, **document}, ensure_ascii=False)
    )


def _kind_from_document(value: object) -> EffectKind:
    for kind in EffectKind:
        if kind.value == value:
            return kind
    raise ValueError("Efecto no admitido.")


def _color_from_document(document: Any) -> RgbColor:
    if not isinstance(document, dict) or frozenset(document) != EXPECTED_COLOR_KEYS:
        raise ValueError("El color del efecto necesita red, green y blue.")
    return RgbColor(
        _require_integer(document["red"], "red"),
        _require_integer(document["green"], "green"),
        _require_integer(document["blue"], "blue"),
    )


def _require_integer(value: object, name: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{name} debe ser un entero.")
    return value
