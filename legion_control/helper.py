"""Narrow privileged command surface invoked through PolicyKit."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from time import monotonic, sleep
from typing import Final, Iterator, Protocol

from legion_control.config import ConfigStore, default_policy, policy_from_json
from legion_control.domain import FanBounds, FanMode, FanPolicy
from legion_control.effects import (
    EffectConfigStore,
    EffectSettings,
    effect_settings_from_json,
)
from legion_control.linux import (
    CapabilityReport,
    HardwareError,
    StatusReport,
    SysfsHardware,
)
from legion_control.power import (
    CustomPowerLimits,
    PowerLimitCapabilities,
    power_limits_from_json,
)
from legion_control.rgb import (
    LegionRgbHardware,
    RgbConfiguration,
    RgbConfigStore,
    RgbHardwareError,
    rgb_configuration_from_json,
)
from legion_control.system_contract import (
    CONTROL_LOCK_PATH,
    FAN_CONFIG_PATH,
    FAN_SERVICE_NAME,
    RGB_CONFIG_PATH,
    RGB_EFFECT_CONFIG_PATH,
    RGB_SERVICE_NAME,
    SYSTEMCTL_PATH,
)


CONFIG_PATH: Final = FAN_CONFIG_PATH
SYSTEMCTL: Final = SYSTEMCTL_PATH
SERVICE_NAME: Final = FAN_SERVICE_NAME
RGB_SERVICE: Final = RGB_SERVICE_NAME
CONTROL_LOCK_TIMEOUT_SECONDS: Final = 15.0
ALLOWED_PROFILES: Final = frozenset({"low-power", "balanced", "performance", "max-power", "custom"})


class HelperError(RuntimeError):
    """A privileged request cannot be completed safely."""


class HardwarePort(Protocol):
    def capabilities(self) -> CapabilityReport: ...
    def set_profile(self, profile: str) -> None: ...
    def current_profile(self) -> str: ...
    def power_capabilities(self) -> PowerLimitCapabilities: ...
    def current_power_limits(self) -> CustomPowerLimits: ...
    def set_power_limits(self, limits: CustomPowerLimits) -> None: ...
    def set_feature(self, feature: str, enabled: bool) -> None: ...
    def restore_firmware_control(self) -> None: ...
    def fan_bounds(self) -> FanBounds: ...
    def status(self) -> StatusReport: ...


class RgbPort(Protocol):
    def is_available(self) -> bool: ...
    def apply(self, configuration: RgbConfiguration) -> None: ...


class ServicePort(Protocol):
    def activate(self) -> None: ...
    def deactivate(self) -> None: ...
    def is_active(self) -> bool: ...


@dataclass(slots=True)
class SystemdUnitService:
    unit: str = SERVICE_NAME
    executable: Path = SYSTEMCTL

    def activate(self) -> None:
        self._run("enable", "--now", self.unit)

    def deactivate(self) -> None:
        self._run("disable", "--now", self.unit)

    def is_active(self) -> bool:
        try:
            result = subprocess.run(
                [str(self.executable), "is-active", "--quiet", self.unit],
                check=False,
                timeout=5,
                env=_safe_environment(),
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0

    def _run(self, *arguments: str) -> None:
        try:
            subprocess.run(
                [str(self.executable), *arguments],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
                env=_safe_environment(),
            )
        except (OSError, subprocess.SubprocessError) as error:
            detail = getattr(error, "stderr", "") or str(error)
            raise HelperError(f"systemd rechazó la operación: {detail.strip()}") from error


@dataclass(slots=True)
class PrivilegedController:
    hardware: HardwarePort
    store: ConfigStore
    service: ServicePort
    rgb_hardware: RgbPort | None = None
    rgb_store: RgbConfigStore | None = None
    rgb_service: ServicePort | None = None
    rgb_effect_store: EffectConfigStore | None = None

    def status(self) -> dict[str, object]:
        report = self.hardware.status().to_dict()
        report["fan_service_active"] = self.service.is_active()
        report["fan_policy"] = _policy_document(self.store.load())
        effect = self._saved_effect()
        report["rgb_effect"] = effect.to_dict() if effect is not None else None
        report["rgb_effect_active"] = (
            self.rgb_service.is_active() if self.rgb_service is not None else False
        )
        return report

    def set_profile(self, profile: str) -> dict[str, object]:
        if profile not in ALLOWED_PROFILES:
            raise HelperError(f"Perfil no admitido: {profile}.")
        if profile != "custom":
            self._stop_manual_control()
        self.hardware.set_profile(profile)
        return {"profile": profile}

    def set_fan_policy(self, policy: FanPolicy) -> dict[str, object]:
        if policy.mode is FanMode.AUTO:
            return self.restore_auto()
        bounds = self.hardware.fan_bounds()
        policy.validate_for(bounds)
        self.store.save(policy)
        try:
            self.hardware.set_profile("custom")
            self.service.activate()
        except Exception:
            self._recover_from_failed_activation()
            raise
        return {"mode": policy.mode.value, "service_active": True}

    def set_custom_configuration(
        self,
        policy: FanPolicy,
        power_limits: CustomPowerLimits,
    ) -> dict[str, object]:
        if policy.mode is FanMode.AUTO:
            raise HelperError("Una configuración Custom necesita RPM fija o curva.")
        bounds = self.hardware.fan_bounds()
        policy.validate_for(bounds)
        power_limits.validate_for(self.hardware.power_capabilities())
        previous_profile = self.hardware.current_profile()
        previous_power_limits = self.hardware.current_power_limits()
        self.store.save(policy)
        power_limits_changed = False
        try:
            self.hardware.set_profile("custom")
            self.hardware.set_power_limits(power_limits)
            power_limits_changed = True
            self.service.activate()
        except Exception:
            recovery_errors = self._recover_custom_configuration(
                previous_profile,
                previous_power_limits if power_limits_changed else None,
            )
            if recovery_errors:
                raise HelperError(
                    "Falló Custom y la recuperación no fue completa: " + " ".join(recovery_errors)
                )
            raise
        return {
            "mode": policy.mode.value,
            "profile": "custom",
            "power_limits": power_limits.to_dict(),
            "service_active": True,
        }

    def restore_auto(self) -> dict[str, object]:
        self._stop_manual_control()
        return {"mode": FanMode.AUTO.value, "service_active": False}

    def set_feature(self, feature: str, enabled: bool) -> dict[str, object]:
        self.hardware.set_feature(feature, enabled)
        return {"feature": feature, "enabled": enabled}

    def set_rgb_configuration(
        self,
        configuration: RgbConfiguration,
    ) -> dict[str, object]:
        if self.rgb_hardware is None or self.rgb_store is None:
            raise HelperError("El soporte RGB no está instalado.")
        if not self.rgb_hardware.is_available():
            raise HelperError("No aparece el teclado RGB 048d:c195 en la interfaz esperada.")
        # A running effect repaints the keyboard many times a second, so it has
        # to stop before a static frame is written or it would erase it.
        self._stop_rgb_effect()
        try:
            self.rgb_hardware.apply(configuration)
        except (RgbHardwareError, OSError, ValueError) as error:
            try:
                self.rgb_store.clear()
            except OSError as cleanup_error:
                raise HelperError(
                    "Falló el RGB y no se pudo invalidar su estado guardado: "
                    f"{cleanup_error}. Error original: {error}"
                ) from cleanup_error
            raise
        self.rgb_store.save(configuration)
        return {
            "enabled": configuration.enabled,
            "brightness_percent": configuration.brightness_percent,
            "zones": len(configuration.zones),
        }

    def set_rgb_effect(self, settings: EffectSettings) -> dict[str, object]:
        """Hand an animation to the effect service, or stop it.

        The service reads the saved settings, so a running animation switches
        effect without restarting and without a visible gap.
        """

        if self.rgb_hardware is None or self.rgb_effect_store is None:
            raise HelperError("El soporte RGB no está instalado.")
        if self.rgb_service is None:
            raise HelperError("El servicio de efectos no está instalado.")
        if not self.rgb_hardware.is_available():
            raise HelperError("No aparece el teclado RGB 048d:c195 en la interfaz esperada.")
        self.rgb_effect_store.save(settings)
        if not settings.enabled or settings.brightness_percent == 0:
            self.rgb_service.deactivate()
            return {"effect": settings.kind.value, "service_active": False}
        try:
            self.rgb_service.activate()
        except Exception:
            self._disable_saved_effect()
            raise
        return {
            "effect": settings.kind.value,
            "speed_percent": settings.speed_percent,
            "brightness_percent": settings.brightness_percent,
            "service_active": True,
        }

    def _stop_rgb_effect(self) -> None:
        """Stop the animation, keeping the chosen effect for the next time."""

        settings = self._saved_effect()
        if self.rgb_service is None or settings is None or not settings.enabled:
            return
        self._disable_saved_effect()
        self.rgb_service.deactivate()

    def _disable_saved_effect(self) -> None:
        settings = self._saved_effect()
        if settings is None or self.rgb_effect_store is None:
            return
        self.rgb_effect_store.save(replace(settings, enabled=False))

    def _saved_effect(self) -> EffectSettings | None:
        if self.rgb_effect_store is None:
            return None
        try:
            settings = self.rgb_effect_store.load()
        except (OSError, ValueError):
            return None
        return settings

    def _recover_from_failed_activation(self) -> None:
        try:
            self._stop_manual_control()
        except HelperError as error:
            raise HelperError(
                f"Falló la activación y la recuperación no fue completa: {error}"
            ) from error

    def _recover_custom_configuration(
        self,
        previous_profile: str,
        previous_power_limits: CustomPowerLimits | None,
    ) -> list[str]:
        errors: list[str] = []
        try:
            self._stop_manual_control()
        except Exception as error:
            errors.append(f"ventilación: {error}")
        if previous_power_limits is not None:
            try:
                self.hardware.set_power_limits(previous_power_limits)
            except Exception as error:
                errors.append(f"potencia: {error}")
        if previous_profile != "custom":
            try:
                self.hardware.set_profile(previous_profile)
            except Exception as error:
                errors.append(f"perfil: {error}")
        return errors

    def _stop_manual_control(self) -> None:
        errors: list[str] = []
        operations = (
            ("guardar modo automático", lambda: self.store.save(default_policy())),
            ("detener el servicio", self.service.deactivate),
            ("restaurar el firmware", self.hardware.restore_firmware_control),
        )
        for description, operation in operations:
            try:
                operation()
            except Exception as error:
                errors.append(f"{description}: {error}")
        if errors:
            raise HelperError("Recuperación incompleta. " + " ".join(errors))


def main(arguments: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    if os.geteuid() != 0:
        return _emit_error("Este helper debe ejecutarse como root mediante PolicyKit.")
    try:
        controller = PrivilegedController(
            hardware=SysfsHardware(),
            store=ConfigStore(CONFIG_PATH),
            service=SystemdUnitService(SERVICE_NAME),
            rgb_hardware=LegionRgbHardware(),
            rgb_store=RgbConfigStore(RGB_CONFIG_PATH),
            rgb_service=SystemdUnitService(RGB_SERVICE),
            rgb_effect_store=EffectConfigStore(RGB_EFFECT_CONFIG_PATH),
        )
        with _exclusive_control():
            result = _dispatch(controller, arguments)
    except (
        HelperError,
        HardwareError,
        RgbHardwareError,
        ValueError,
        OSError,
    ) as error:
        return _emit_error(str(error))
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
    return 0


def _dispatch(controller: PrivilegedController, arguments: list[str]) -> dict[str, object]:
    if arguments == ["status"]:
        return controller.status()
    if len(arguments) == 2 and arguments[0] == "set-profile":
        return controller.set_profile(arguments[1])
    if len(arguments) == 2 and arguments[0] == "set-fan-config":
        return controller.set_fan_policy(policy_from_json(arguments[1]))
    if len(arguments) == 3 and arguments[0] == "set-custom-config":
        return controller.set_custom_configuration(
            policy_from_json(arguments[1]),
            power_limits_from_json(arguments[2]),
        )
    if len(arguments) == 2 and arguments[0] == "set-rgb-config":
        return controller.set_rgb_configuration(rgb_configuration_from_json(arguments[1]))
    if len(arguments) == 2 and arguments[0] == "set-rgb-effect":
        return controller.set_rgb_effect(effect_settings_from_json(arguments[1]))
    if arguments == ["restore-auto"]:
        return controller.restore_auto()
    if len(arguments) == 3 and arguments[0] == "set-feature" and arguments[2] in {"0", "1"}:
        return controller.set_feature(arguments[1], arguments[2] == "1")
    raise HelperError("Orden no admitida.")


@contextmanager
def _exclusive_control(
    lock_path: Path = CONTROL_LOCK_PATH,
    *,
    timeout_seconds: float = CONTROL_LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    try:
        descriptor = os.open(
            lock_path,
            os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o600,
        )
    except OSError as error:
        raise HelperError(f"No se pudo abrir el bloqueo de control: {error}.") from error

    acquired = False
    try:
        deadline = monotonic() + max(0.0, timeout_seconds)
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError as error:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise HelperError(
                        "Hay una operación anterior en curso; inténtalo de nuevo."
                    ) from error
                sleep(min(0.05, remaining))
        yield
    finally:
        if acquired:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _policy_document(policy: FanPolicy) -> dict[str, object]:
    return {
        "mode": policy.mode.value,
        "fixed_rpm": policy.fixed_rpm,
        "curve": [
            {"temperature_c": point.temperature_c, "rpm": point.rpm}
            for point in policy.curve.points
        ],
    }


def _safe_environment() -> dict[str, str]:
    return {
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }


def _emit_error(message: str) -> int:
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
