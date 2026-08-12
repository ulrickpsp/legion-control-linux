"""Read-only diagnostic report for Legion Control support requests."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from legion_control import __version__
from legion_control.i18n import translate
from legion_control.system_contract import (
    FAN_SERVICE_NAME,
    POLKIT_ACTION_PATH,
    PRIVILEGED_HELPER_PATH,
    SYSTEMCTL_PATH,
)
from legion_control.updates import UpdateStore, default_update_path, parse_version


DOCTOR_REPORT_VERSION: Final = 2
VALIDATED_BIOS_VERSION: Final = "Q6CN79WW"
# Without these the kernel publishes no platform profile, no fan hwmon and no
# firmware attributes, so every control in the application goes quiet.
REQUIRED_KERNEL_MODULES: Final = ("lenovo_wmi_gamezone", "lenovo_wmi_other")
# Anything else that writes platform_profile will silently undo a scene.
PROFILE_COMPETITORS: Final = ("power-profiles-daemon.service", "tuned.service")
# Other keyboard tools drive the same ITE controller from their own state.
RGB_COMPETITORS: Final = ("openrgb.service", "legiond.service")
# The out-of-tree LenovoLegionLinux driver claims the same WMI methods.
COMPETING_MODULES: Final = ("legion_laptop",)
SYSTEMCTL_TIMEOUT_SECONDS: Final = 5
UNKNOWN_STATE: Final = "unknown"

SystemctlRunner = Callable[[str, tuple[str, ...]], tuple[str, ...]]


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
    remedy: str = ""


@dataclass(frozen=True, slots=True)
class SystemProbe:
    """Environment facts a status poll cannot see, gathered without writing."""

    helper_installed: bool = False
    polkit_action_installed: bool = False
    loaded_modules: tuple[str, ...] = ()
    competing_modules: tuple[str, ...] = ()
    fan_service_state: str = UNKNOWN_STATE
    fan_service_enabled: str = UNKNOWN_STATE
    active_profile_competitors: tuple[str, ...] = ()
    active_rgb_competitors: tuple[str, ...] = ()
    bios_version: str | None = None
    # Last release seen by the opt-in notice; empty when it is off or unasked.
    available_version: str = ""


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
                    "remedy": item.remedy,
                }
                for item in self.findings
            ],
        }

    def to_text(self) -> str:
        lines = ["Legion Control Doctor", "", translate("Informe solo lectura."), ""]
        for item in self.findings:
            lines.append(f"[{item.severity.value.upper()}] {item.title}: {item.value}")
            # A finding the reader cannot act on is only half a diagnosis.
            if item.remedy and item.severity is not DoctorSeverity.OK:
                lines.append(f"    → {item.remedy}")
        return "\n".join(lines) + "\n"

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n"


def probe_system(
    *,
    root: Path = Path("/"),
    run_systemctl: SystemctlRunner | None = None,
    update_store: UpdateStore | None = None,
) -> SystemProbe:
    """Read installation and conflict state from the running system only.

    The release notice is read from its saved file, never from the network: the
    check runs where the user enabled it, and this only reports its last answer.
    """

    runner = run_systemctl or _systemctl_states
    units = (FAN_SERVICE_NAME, *PROFILE_COMPETITORS, *RGB_COMPETITORS)
    states = dict(zip(units, runner("is-active", units)))
    enabled = runner("is-enabled", (FAN_SERVICE_NAME,))
    return SystemProbe(
        helper_installed=_relative_to(root, PRIVILEGED_HELPER_PATH).exists(),
        polkit_action_installed=_relative_to(root, POLKIT_ACTION_PATH).exists(),
        loaded_modules=_present_modules(root, REQUIRED_KERNEL_MODULES),
        competing_modules=_present_modules(root, COMPETING_MODULES),
        fan_service_state=states.get(FAN_SERVICE_NAME, UNKNOWN_STATE),
        fan_service_enabled=enabled[0] if enabled else UNKNOWN_STATE,
        active_profile_competitors=_active(states, PROFILE_COMPETITORS),
        active_rgb_competitors=_active(states, RGB_COMPETITORS),
        bios_version=_read_optional_text(root / "sys/devices/virtual/dmi/id/bios_version"),
        available_version=_saved_release_notice(update_store),
    )


def _saved_release_notice(store: UpdateStore | None) -> str:
    configuration = store or UpdateStore(default_update_path())
    try:
        saved = configuration.load()
    except (OSError, ValueError):
        return ""
    return saved.last_seen_version if saved.enabled else ""


def build_doctor_report(
    status: dict[str, object],
    *,
    kernel_release: str | None = None,
    probe: SystemProbe | None = None,
) -> DoctorReport:
    """Summarize already-readable state without probing or writing hardware.

    ``probe`` carries the facts that need the filesystem and systemd rather than
    a status poll.  It stays optional so callers that only have a status
    dictionary, and the poll itself, never pay for those reads.
    """

    capabilities = _dictionary(status.get("capabilities"))
    supported = bool(capabilities.get("supported"))
    product = _text(capabilities.get("product"), "desconocido")
    product_version = _text(capabilities.get("product_version"), product)
    fan_control = bool(capabilities.get("fan_control"))
    temperatures = _temperatures(status)
    hottest = max(temperatures) if temperatures else None
    rgb_available = bool(capabilities.get("rgb_control"))
    release = kernel_release or os.uname().release

    findings: list[DoctorFinding] = [
        # A support report is worth little without saying what produced it.
        _version_finding(probe),
        DoctorFinding(
            "identity",
            translate("Equipo"),
            f"{product_version} · {translate('producto')} {product}",
            DoctorSeverity.OK if supported else DoctorSeverity.ERROR,
            ""
            if supported
            else translate("Este equipo no está en la lista de modelos verificados."),
        ),
        DoctorFinding(
            "kernel",
            "Kernel",
            release,
            DoctorSeverity.OK,
        ),
    ]
    if probe is not None:
        findings.extend(_installation_findings(probe, supported))
    findings.append(
        DoctorFinding(
            "fan_control",
            translate("Control de ventilación"),
            _fan_control_value(capabilities),
            DoctorSeverity.OK if fan_control else DoctorSeverity.WARNING,
            ""
            if fan_control
            else translate("El kernel no publica fan1_target; solo queda el control del firmware."),
        )
    )
    findings.append(
        DoctorFinding(
            "thermal",
            translate("Lecturas térmicas"),
            _thermal_value(status),
            _thermal_severity(hottest),
            _thermal_remedy(hottest),
        )
    )
    findings.append(_fan_service_finding(status, probe))
    findings.append(
        DoctorFinding(
            "rgb",
            translate("Teclado RGB"),
            translate("controlador ITE detectado") if rgb_available else translate("no disponible"),
            DoctorSeverity.OK if rgb_available else DoctorSeverity.WARNING,
            ""
            if rgb_available
            else translate("No aparece el nodo hidraw de 048d:c195. Reconecta o revisa el modelo."),
        )
    )
    if probe is not None:
        findings.extend(_conflict_findings(probe))
    return DoctorReport(tuple(findings))


def _version_finding(probe: SystemProbe | None) -> DoctorFinding:
    installed = f"Legion Control {__version__}"
    available = probe.available_version if probe is not None else ""
    published = parse_version(available) if available else None
    current = parse_version(__version__)
    if published is None or current is None or published <= current:
        return DoctorFinding("version", translate("Versión"), installed, DoctorSeverity.OK)
    return DoctorFinding(
        "version",
        translate("Versión"),
        translate("{installed} · {latest} disponible", installed=installed, latest=available),
        DoctorSeverity.WARNING,
        translate("Solo la última publicación recibe soporte de seguridad."),
    )


def _installation_findings(probe: SystemProbe, supported: bool) -> list[DoctorFinding]:
    return [
        _bios_finding(probe, supported),
        _modules_finding(probe),
        _privilege_finding(probe),
    ]


def _bios_finding(probe: SystemProbe, supported: bool) -> DoctorFinding:
    version = probe.bios_version
    if version is None:
        return DoctorFinding(
            "bios",
            "BIOS",
            translate("no legible"),
            DoctorSeverity.WARNING,
            translate("Sin la versión de BIOS no se puede comparar con la validada."),
        )
    if not supported or version == VALIDATED_BIOS_VERSION:
        # Off the allowlist the comparison says nothing; identity already errored.
        return DoctorFinding("bios", "BIOS", version, DoctorSeverity.OK)
    return DoctorFinding(
        "bios",
        "BIOS",
        translate(
            "{version} · validada {expected}", version=version, expected=VALIDATED_BIOS_VERSION
        ),
        DoctorSeverity.WARNING,
        translate("Otra BIOS puede mover los límites publicados. Revisa antes de escribir."),
    )


def _modules_finding(probe: SystemProbe) -> DoctorFinding:
    missing = tuple(name for name in REQUIRED_KERNEL_MODULES if name not in probe.loaded_modules)
    if not missing:
        return DoctorFinding(
            "modules",
            translate("Módulos del kernel"),
            " · ".join(probe.loaded_modules),
            DoctorSeverity.OK,
        )
    return DoctorFinding(
        "modules",
        translate("Módulos del kernel"),
        translate("faltan {names}", names=" · ".join(missing)),
        DoctorSeverity.WARNING,
        translate("Sin los módulos WMI de Lenovo no hay perfil, ventilación ni potencia."),
    )


def _privilege_finding(probe: SystemProbe) -> DoctorFinding:
    if probe.helper_installed and probe.polkit_action_installed:
        return DoctorFinding(
            "privileges",
            translate("Autorización"),
            translate("helper y acción PolicyKit instalados"),
            DoctorSeverity.OK,
        )
    missing = []
    if not probe.helper_installed:
        missing.append(str(PRIVILEGED_HELPER_PATH))
    if not probe.polkit_action_installed:
        missing.append(str(POLKIT_ACTION_PATH))
    return DoctorFinding(
        "privileges",
        translate("Autorización"),
        translate("falta {names}", names=" · ".join(missing)),
        DoctorSeverity.ERROR,
        translate("Instala el paquete: sin esos archivos ningún cambio llega al hardware."),
    )


def _fan_service_finding(
    status: dict[str, object],
    probe: SystemProbe | None,
) -> DoctorFinding:
    title = translate("Servicio de curva")
    if probe is None:
        active = bool(status.get("fan_service_active"))
        return DoctorFinding(
            "fan_service",
            title,
            translate("activo") if active else translate("control firmware"),
            DoctorSeverity.OK,
        )
    state = probe.fan_service_state
    if state == "failed":
        return DoctorFinding(
            "fan_service",
            title,
            translate("fallido"),
            DoctorSeverity.ERROR,
            translate("Revisa journalctl -u {unit}", unit=FAN_SERVICE_NAME),
        )
    if state == "active":
        return DoctorFinding("fan_service", title, translate("activo"), DoctorSeverity.OK)
    if state == UNKNOWN_STATE:
        return DoctorFinding(
            "fan_service",
            title,
            translate("estado no legible"),
            DoctorSeverity.WARNING,
            translate("systemctl no respondió; el servicio puede estar en cualquier estado."),
        )
    return DoctorFinding("fan_service", title, translate("control firmware"), DoctorSeverity.OK)


def _conflict_findings(probe: SystemProbe) -> list[DoctorFinding]:
    profile_rivals = (*probe.active_profile_competitors, *probe.competing_modules)
    findings = []
    if profile_rivals:
        findings.append(
            DoctorFinding(
                "profile_conflict",
                translate("Conflicto de perfil"),
                " · ".join(profile_rivals),
                DoctorSeverity.WARNING,
                translate("Otro componente escribe platform_profile y puede deshacer una escena."),
            )
        )
    else:
        findings.append(
            DoctorFinding(
                "profile_conflict",
                translate("Conflicto de perfil"),
                translate("ninguno"),
                DoctorSeverity.OK,
            )
        )
    if probe.active_rgb_competitors:
        findings.append(
            DoctorFinding(
                "rgb_conflict",
                translate("Conflicto RGB"),
                " · ".join(probe.active_rgb_competitors),
                DoctorSeverity.WARNING,
                translate("Otra herramienta maneja el mismo controlador ITE. Ciérrala antes."),
            )
        )
    else:
        findings.append(
            DoctorFinding(
                "rgb_conflict",
                translate("Conflicto RGB"),
                translate("ninguno"),
                DoctorSeverity.OK,
            )
        )
    return findings


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


def _thermal_remedy(hottest: int | None) -> str:
    if hottest is None:
        return translate("Sin sensores no hay curva segura: el firmware conserva el control.")
    if hottest >= 92:
        return translate("Temperatura crítica: deja que el firmware suba los ventiladores.")
    if hottest >= 80:
        return translate("Carga sostenida alta. Un perfil más frío baja la temperatura.")
    return ""


def _temperatures(status: dict[str, object]) -> list[int]:
    return [
        value
        for value in (
            _integer(status.get("cpu_temperature_c")),
            _integer(status.get("gpu_temperature_c")),
        )
        if value is not None
    ]


def _active(states: dict[str, str], units: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(unit for unit in units if states.get(unit) == "active")


def _present_modules(root: Path, names: tuple[str, ...]) -> tuple[str, ...]:
    # /sys/module also lists built-in modules, which /proc/modules omits.
    parent = root / "sys/module"
    return tuple(name for name in names if (parent / name).exists())


def _relative_to(root: Path, path: Path) -> Path:
    return root / path.relative_to("/")


def _systemctl_states(command: str, units: tuple[str, ...]) -> tuple[str, ...]:
    if not units or not SYSTEMCTL_PATH.exists():
        return tuple(UNKNOWN_STATE for _ in units)
    try:
        completed = subprocess.run(
            [str(SYSTEMCTL_PATH), command, *units],
            capture_output=True,
            text=True,
            check=False,
            timeout=SYSTEMCTL_TIMEOUT_SECONDS,
            env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
        )
    except (OSError, subprocess.SubprocessError):
        return tuple(UNKNOWN_STATE for _ in units)
    # systemctl answers one word per unit and exits non-zero unless all match.
    states = completed.stdout.split()
    if len(states) != len(units):
        return tuple(UNKNOWN_STATE for _ in units)
    return tuple(states)


def _read_optional_text(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return text or None


def _integer(value: object) -> int | None:
    return value if type(value) is int else None


def _text(value: object, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _dictionary(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
