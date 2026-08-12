"""Read-only diagnostic report for Legion Control support requests."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from legion_control import __version__
from legion_control.i18n import translate


DOCTOR_REPORT_VERSION: Final = 1


class DoctorSeverity(StrEnum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class DoctorFinding:
    key: str
    title: str
    value: str
    severity: DoctorSeverity


@dataclass(frozen=True, slots=True)
class DoctorReport:
    findings: tuple[DoctorFinding, ...]

    @property
    def severity(self) -> DoctorSeverity:
        if any(item.severity is DoctorSeverity.ERROR for item in self.findings):
            return DoctorSeverity.ERROR
        if any(item.severity is DoctorSeverity.WARNING for item in self.findings):
            return DoctorSeverity.WARNING
        return DoctorSeverity.OK

    def to_dict(self) -> dict[str, object]:
        return {
            "version": DOCTOR_REPORT_VERSION,
            "severity": self.severity.value,
            "findings": [
                {
                    "key": item.key,
                    "title": item.title,
                    "value": item.value,
                    "severity": item.severity.value,
                }
                for item in self.findings
            ],
        }

    def to_text(self) -> str:
        lines = ["Legion Control Doctor", "", translate("Informe solo lectura."), ""]
        lines.extend(
            f"[{item.severity.value.upper()}] {item.title}: {item.value}" for item in self.findings
        )
        return "\n".join(lines) + "\n"

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n"


def build_doctor_report(
    status: dict[str, object],
    *,
    kernel_release: str | None = None,
) -> DoctorReport:
    """Summarize already-readable state without probing or writing hardware."""

    capabilities = _dictionary(status.get("capabilities"))
    supported = bool(capabilities.get("supported"))
    product = _text(capabilities.get("product"), "desconocido")
    product_version = _text(capabilities.get("product_version"), product)
    fan_control = bool(capabilities.get("fan_control"))
    temperatures = _temperatures(status)
    hottest = max(temperatures) if temperatures else None
    fan_service_active = bool(status.get("fan_service_active"))
    rgb_available = bool(capabilities.get("rgb_control"))
    release = kernel_release or os.uname().release

    findings = (
        # A support report is worth little without saying what produced it.
        DoctorFinding(
            "version",
            translate("Versión"),
            f"Legion Control {__version__}",
            DoctorSeverity.OK,
        ),
        DoctorFinding(
            "identity",
            translate("Equipo"),
            f"{product_version} · {translate('producto')} {product}",
            DoctorSeverity.OK if supported else DoctorSeverity.ERROR,
        ),
        DoctorFinding(
            "kernel",
            "Kernel",
            release,
            DoctorSeverity.OK,
        ),
        DoctorFinding(
            "fan_control",
            translate("Control de ventilación"),
            _fan_control_value(capabilities),
            DoctorSeverity.OK if fan_control else DoctorSeverity.WARNING,
        ),
        DoctorFinding(
            "thermal",
            translate("Lecturas térmicas"),
            _thermal_value(status),
            _thermal_severity(hottest),
        ),
        DoctorFinding(
            "fan_service",
            translate("Servicio de curva"),
            translate("activo") if fan_service_active else translate("control firmware"),
            DoctorSeverity.OK,
        ),
        DoctorFinding(
            "rgb",
            translate("Teclado RGB"),
            translate("controlador ITE detectado") if rgb_available else translate("no disponible"),
            DoctorSeverity.OK if rgb_available else DoctorSeverity.WARNING,
        ),
    )
    return DoctorReport(findings)


def _fan_control_value(capabilities: dict[str, Any]) -> str:
    if not bool(capabilities.get("fan_control")):
        return translate("no publicado por el kernel")
    minimum = capabilities.get("fan_minimum_rpm")
    maximum = capabilities.get("fan_maximum_rpm")
    step = capabilities.get("fan_step_rpm")
    if all(type(value) is int for value in (minimum, maximum, step)):
        return translate(
            "{minimum}–{maximum} RPM · paso {step} RPM",
            minimum=minimum,
            maximum=maximum,
            step=step,
        )
    return translate("disponible")


def _thermal_value(status: dict[str, object]) -> str:
    cpu = _integer(status.get("cpu_temperature_c"))
    gpu = _integer(status.get("gpu_temperature_c"))
    fan1 = _integer(status.get("fan1_rpm"))
    fan2 = _integer(status.get("fan2_rpm"))
    parts = []
    if cpu is not None:
        parts.append(f"CPU {cpu} °C")
    if gpu is not None:
        parts.append(f"GPU {gpu} °C")
    if fan1 is not None:
        parts.append(translate("fan 1 {rpm} RPM", rpm=fan1))
    if fan2 is not None:
        parts.append(translate("fan 2 {rpm} RPM", rpm=fan2))
    return " · ".join(parts) if parts else translate("sin lecturas fiables")


def _thermal_severity(hottest: int | None) -> DoctorSeverity:
    if hottest is None:
        return DoctorSeverity.WARNING
    if hottest >= 92:
        return DoctorSeverity.ERROR
    if hottest >= 80:
        return DoctorSeverity.WARNING
    return DoctorSeverity.OK


def _temperatures(status: dict[str, object]) -> list[int]:
    return [
        value
        for value in (
            _integer(status.get("cpu_temperature_c")),
            _integer(status.get("gpu_temperature_c")),
        )
        if value is not None
    ]


def _integer(value: object) -> int | None:
    return value if type(value) is int else None


def _text(value: object, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _dictionary(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
