"""Static 24-zone patterns that look richer than a flat gradient.

Each pattern is a continuous field sampled at one phase. Sampling is what makes
them static: the frame is chosen here, written once through the same physically
verified report sequence as any other preset, and then left alone.

Animating them by resending successive phases was implemented and removed. The
controller retains its colours across a full power cycle, and whether the write
reaches non-volatile storage could not be determined on the validated unit: the
power rail cannot be cut without disassembly, and latency does not tell the two
apart, since the off report carries no colour at all and still costs as much as
a coloured one. Repeating that write many times a second against an unknown
endurance was not a risk worth taking for motion. See docs/RGB-PROTOCOL.md.

Perceived brightness is not linear in the value written to an LED, so the ramps
below are gamma-shaped. A linear falloff reads as a hard edge followed by a long
dim tail.
"""

from __future__ import annotations

import colorsys
import math
from enum import Enum
from typing import Final

from legion_control.rgb import RGB_ZONE_COUNT, RgbColor, RgbConfiguration


TAU: Final = math.tau


class PatternKind(Enum):
    """The fields a static frame can be sampled from."""

    AURORA = "aurora"
    FIRE = "fire"
    COMET = "comet"
    WAVE = "wave"


# Patterns that paint their own palette ignore the colour they are given.
COLOR_AWARE_KINDS: Final = frozenset({PatternKind.COMET, PatternKind.WAVE})


def pattern_zones(kind: PatternKind, color: RgbColor, phase: float) -> tuple[RgbColor, ...]:
    """Sample one frame of a pattern. Pure: same inputs, same 24 colours."""

    if not isinstance(kind, PatternKind):
        raise ValueError("El patrón debe ser uno de los definidos.")
    if not isinstance(color, RgbColor):
        raise ValueError("El patrón necesita un color válido.")
    renderer = _RENDERERS[kind]
    wrapped = phase % 1.0
    return tuple(renderer(color, wrapped, zone) for zone in range(RGB_ZONE_COUNT))


def pattern_configuration(
    kind: PatternKind,
    color: RgbColor,
    brightness_percent: int,
    phase: float,
    *,
    enabled: bool = True,
) -> RgbConfiguration:
    """Render a pattern into a configuration the verified writer accepts."""

    return RgbConfiguration(
        enabled=enabled,
        brightness_percent=brightness_percent,
        zones=pattern_zones(kind, color, phase),
    )


def _aurora(_color: RgbColor, phase: float, zone: int) -> RgbColor:
    """Curtains drifting through green, cyan and violet."""

    span = zone / RGB_ZONE_COUNT
    hue = (
        0.45
        + 0.17 * math.sin(TAU * (phase * 0.62 + span * 1.1))
        + 0.08 * math.sin(TAU * (phase * 0.31 - span * 0.7 + 0.25))
    )
    value = 0.30 + 0.70 * (0.5 + 0.5 * math.sin(TAU * (phase + span * 1.4))) ** 1.8
    return _from_hsv(hue % 1.0, 0.88, value)


def _fire(_color: RgbColor, phase: float, zone: int) -> RgbColor:
    """Warm flicker from layered sines, so it looks irregular but is reproducible.

    The dominant term is spatially slow so neighbouring zones stay related, as a
    flame does; the faster terms only add texture on top of it.
    """

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


def _comet(color: RgbColor, phase: float, zone: int) -> RgbColor:
    """A bright head with a tail decaying away from it.

    The tail never reaches black. On a still frame a bare comet leaves most of
    the keyboard dark, which reads as a fault rather than as a design.
    """

    head = _triangle(phase) * (RGB_ZONE_COUNT - 1)
    intensity = 0.12 + 0.88 * 0.55 ** abs(zone - head)
    lit = _scale(color, intensity)
    return _blend(lit, RgbColor(255, 255, 255), 0.6 * max(0.0, intensity - 0.8) / 0.2)


def _wave(color: RgbColor, phase: float, zone: int) -> RgbColor:
    """A crest of light over a dim bed of the chosen colour."""

    crest_width = 0.24
    offset = ((zone / RGB_ZONE_COUNT) - phase) % 1.0
    distance = min(offset, 1.0 - offset)
    intensity = _smoothstep(max(0.0, 1.0 - distance / crest_width))
    # The bed stays clearly lit for the same reason the comet's tail does.
    lit = _scale(color, 0.24 + 0.76 * intensity)
    # The crest itself washes toward white so it reads as light, not colour.
    return _blend(lit, RgbColor(255, 255, 255), 0.45 * intensity**3)


_RENDERERS: Final = {
    PatternKind.AURORA: _aurora,
    PatternKind.FIRE: _fire,
    PatternKind.COMET: _comet,
    PatternKind.WAVE: _wave,
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
    """Ramp 0 to 1 and back, so the head never jumps at the wrap."""

    return 1.0 - abs(2.0 * (phase % 1.0) - 1.0)


def _smoothstep(value: float) -> float:
    value = _clamp(value)
    return value * value * (3.0 - 2.0 * value)


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
