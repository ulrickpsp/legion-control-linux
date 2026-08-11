"""Rate-limited, read-only thermal alert decisions."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from legion_control.i18n import translate


ELEVATED_TEMPERATURE_C: Final = 80
CRITICAL_TEMPERATURE_C: Final = 92
ALERT_COOLDOWN_SECONDS: Final = 600


class ThermalLevel(StrEnum):
    NORMAL = "normal"
    ELEVATED = "elevated"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ThermalAlert:
    level: ThermalLevel
    temperature_c: int | None
    message: str


class ThermalAlertController:
    """Notify on entry/escalation, never perform a hardware mutation."""

    def __init__(self, cooldown_seconds: int = ALERT_COOLDOWN_SECONDS) -> None:
        if cooldown_seconds < 0:
            raise ValueError("La espera entre alertas no puede ser negativa.")
        self._cooldown_seconds = cooldown_seconds
        self._level = ThermalLevel.UNKNOWN
        self._last_notice_at: float | None = None

    def observe(
        self,
        status: dict[str, object],
        *,
        timestamp: float | None = None,
    ) -> ThermalAlert | None:
        hottest = _hottest_temperature(status)
        level = _thermal_level(hottest)
        previous = self._level
        self._level = level
        now = time.monotonic() if timestamp is None else timestamp
        if level in {ThermalLevel.NORMAL, ThermalLevel.UNKNOWN}:
            return None
        escalated = _severity(level) > _severity(previous)
        cooled_down = (
            self._last_notice_at is None or now - self._last_notice_at >= self._cooldown_seconds
        )
        if not escalated and not cooled_down:
            return None
        self._last_notice_at = now
        if level is ThermalLevel.CRITICAL:
            return ThermalAlert(
                level,
                hottest,
                translate(
                    "Temperatura crítica: {temperature} °C. Reduce carga y restaura firmware si dudas.",
                    temperature=hottest,
                ),
            )
        return ThermalAlert(
            level,
            hottest,
            translate("Temperatura elevada: {temperature} °C.", temperature=hottest),
        )


def _hottest_temperature(status: dict[str, object]) -> int | None:
    readings = [
        value
        for value in (
            status.get("cpu_temperature_c"),
            status.get("gpu_temperature_c"),
        )
        if type(value) is int
    ]
    return max(readings) if readings else None


def _thermal_level(temperature_c: int | None) -> ThermalLevel:
    if temperature_c is None:
        return ThermalLevel.UNKNOWN
    if temperature_c >= CRITICAL_TEMPERATURE_C:
        return ThermalLevel.CRITICAL
    if temperature_c >= ELEVATED_TEMPERATURE_C:
        return ThermalLevel.ELEVATED
    return ThermalLevel.NORMAL


def _severity(level: ThermalLevel) -> int:
    return {
        ThermalLevel.UNKNOWN: 0,
        ThermalLevel.NORMAL: 1,
        ThermalLevel.ELEVATED: 2,
        ThermalLevel.CRITICAL: 3,
    }[level]
