"""Validated CPU power limits exposed by Lenovo Other Mode WMI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final


POWER_CONFIG_VERSION: Final = 1
MAX_POWER_CONFIG_BYTES: Final = 1024
EXPECTED_POWER_KEYS: Final = frozenset({"version", "sustained_w", "slow_w"})


@dataclass(frozen=True, slots=True)
class PowerLimitBounds:
    minimum_w: int
    maximum_w: int
    step_w: int
    default_w: int

    def __post_init__(self) -> None:
        values = (self.minimum_w, self.maximum_w, self.step_w, self.default_w)
        if any(type(value) is not int for value in values):
            raise ValueError("Los límites de potencia deben ser enteros.")
        if self.minimum_w <= 0 or self.maximum_w < self.minimum_w:
            raise ValueError("El rango de potencia publicado no es válido.")
        if self.step_w <= 0:
            raise ValueError("El paso de potencia debe ser positivo.")
        if not self.contains(self.default_w):
            raise ValueError("La potencia predeterminada queda fuera del rango.")

    def contains(self, value_w: int) -> bool:
        return (
            type(value_w) is int
            and self.minimum_w <= value_w <= self.maximum_w
            and (value_w - self.minimum_w) % self.step_w == 0
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "minimum_w": self.minimum_w,
            "maximum_w": self.maximum_w,
            "step_w": self.step_w,
            "default_w": self.default_w,
        }


@dataclass(frozen=True, slots=True)
class PowerLimitCapabilities:
    sustained: PowerLimitBounds
    slow: PowerLimitBounds

    def to_dict(self) -> dict[str, object]:
        return {
            "sustained": self.sustained.to_dict(),
            "slow": self.slow.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class CustomPowerLimits:
    sustained_w: int
    slow_w: int

    def __post_init__(self) -> None:
        if type(self.sustained_w) is not int or type(self.slow_w) is not int:
            raise ValueError("Cada límite de potencia debe ser un entero.")
        if self.sustained_w <= 0 or self.slow_w <= 0:
            raise ValueError("Cada límite de potencia debe ser positivo.")
        if self.slow_w < self.sustained_w:
            raise ValueError("La potencia lenta no puede ser menor que la potencia sostenida.")

    def validate_for(self, capabilities: PowerLimitCapabilities) -> None:
        if not capabilities.sustained.contains(self.sustained_w):
            bounds = capabilities.sustained
            raise ValueError(
                "La potencia sostenida debe estar entre "
                f"{bounds.minimum_w} y {bounds.maximum_w} W "
                f"en pasos de {bounds.step_w} W."
            )
        if not capabilities.slow.contains(self.slow_w):
            bounds = capabilities.slow
            raise ValueError(
                "La potencia lenta debe estar entre "
                f"{bounds.minimum_w} y {bounds.maximum_w} W "
                f"en pasos de {bounds.step_w} W."
            )

    def to_dict(self) -> dict[str, int]:
        return {
            "sustained_w": self.sustained_w,
            "slow_w": self.slow_w,
        }


def power_limits_to_json(limits: CustomPowerLimits) -> str:
    document = {
        "version": POWER_CONFIG_VERSION,
        **limits.to_dict(),
    }
    return json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def power_limits_from_json(payload: str) -> CustomPowerLimits:
    if len(payload.encode("utf-8")) > MAX_POWER_CONFIG_BYTES:
        raise ValueError("La configuración de potencia es demasiado grande.")
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ValueError(f"JSON de potencia inválido: {error.msg}.") from error
    if not isinstance(document, dict):
        raise ValueError("La configuración de potencia debe ser un objeto.")
    if frozenset(document) != EXPECTED_POWER_KEYS:
        raise ValueError("La configuración de potencia contiene claves incorrectas.")
    if document["version"] != POWER_CONFIG_VERSION:
        raise ValueError(f"Solo se admite potencia versión {POWER_CONFIG_VERSION}.")
    return CustomPowerLimits(
        sustained_w=_require_integer(document["sustained_w"]),
        slow_w=_require_integer(document["slow_w"]),
    )


def power_limits_from_document(document: Any) -> CustomPowerLimits:
    if not isinstance(document, dict):
        raise ValueError("Los límites de potencia deben ser un objeto.")
    return power_limits_from_json(
        json.dumps(
            {"version": POWER_CONFIG_VERSION, **document},
            ensure_ascii=False,
        )
    )


def _require_integer(value: object) -> int:
    if type(value) is not int:
        raise ValueError("Cada límite de potencia debe ser un entero.")
    return value
