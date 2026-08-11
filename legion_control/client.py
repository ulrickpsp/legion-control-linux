"""Unprivileged application client for status and privileged mutations."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Final, Protocol

from legion_control.config import policy_to_json
from legion_control.domain import FanPolicy
from legion_control.linux import SysfsHardware
from legion_control.power import CustomPowerLimits, power_limits_to_json
from legion_control.rgb import (
    RGB_ZONE_COUNT,
    LegionRgbHardware,
    RgbConfiguration,
    rgb_configuration_from_json,
    rgb_configuration_to_json,
)
from legion_control.system_contract import (
    FAN_CONFIG_PATH,
    FAN_SERVICE_NAME,
    PKEXEC_PATH,
    PRIVILEGED_HELPER_PATH,
    RGB_CONFIG_PATH,
    SYSTEMCTL_PATH,
)


PKEXEC: Final = PKEXEC_PATH
HELPER: Final = PRIVILEGED_HELPER_PATH
CONFIG_PATH: Final = FAN_CONFIG_PATH


class ControlError(RuntimeError):
    """An operation failed or administrator authorization was cancelled."""


class ControlPort(Protocol):
    def read_status(self) -> dict[str, object]: ...
    def set_profile(self, profile: str) -> dict[str, object]: ...
    def set_fan_policy(self, policy: FanPolicy) -> dict[str, object]: ...
    def set_custom_configuration(
        self,
        policy: FanPolicy,
        power_limits: CustomPowerLimits,
    ) -> dict[str, object]: ...
    def restore_auto(self) -> dict[str, object]: ...
    def set_feature(self, feature: str, enabled: bool) -> dict[str, object]: ...
    def set_rgb_configuration(
        self,
        configuration: RgbConfiguration,
    ) -> dict[str, object]: ...


@dataclass(slots=True)
class LocalControlClient:
    hardware: SysfsHardware
    rgb_hardware: LegionRgbHardware | None = None

    def read_status(self) -> dict[str, object]:
        status = self.hardware.status().to_dict()
        rgb_hardware = self.rgb_hardware or LegionRgbHardware()
        capabilities = status.get("capabilities")
        if isinstance(capabilities, dict):
            rgb_available = rgb_hardware.is_available()
            capabilities["rgb_control"] = rgb_available
            capabilities["rgb_zones"] = RGB_ZONE_COUNT if rgb_available else 0
        status["fan_policy"] = _read_public_policy()
        status["fan_service_active"] = _service_is_active()
        rgb_configuration = _read_public_rgb_configuration()
        status["rgb_configuration_known"] = rgb_configuration is not None
        status["rgb_configuration"] = (
            rgb_configuration.to_dict()
            if rgb_configuration is not None
            else None
        )
        return status

    def set_profile(self, profile: str) -> dict[str, object]:
        return self._mutate("set-profile", profile)

    def set_fan_policy(self, policy: FanPolicy) -> dict[str, object]:
        return self._mutate("set-fan-config", policy_to_json(policy))

    def set_custom_configuration(
        self,
        policy: FanPolicy,
        power_limits: CustomPowerLimits,
    ) -> dict[str, object]:
        return self._mutate(
            "set-custom-config",
            policy_to_json(policy),
            power_limits_to_json(power_limits),
        )

    def restore_auto(self) -> dict[str, object]:
        return self._mutate("restore-auto")

    def set_feature(self, feature: str, enabled: bool) -> dict[str, object]:
        return self._mutate("set-feature", feature, "1" if enabled else "0")

    def set_rgb_configuration(
        self,
        configuration: RgbConfiguration,
    ) -> dict[str, object]:
        return self._mutate(
            "set-rgb-config",
            rgb_configuration_to_json(configuration),
        )

    @staticmethod
    def _mutate(*arguments: str) -> dict[str, object]:
        try:
            result = subprocess.run(
                [str(PKEXEC), str(HELPER), *arguments],
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
                env={
                    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
                    "LANG": os.environ.get("LANG", "es_ES.UTF-8"),
                    "LC_ALL": os.environ.get("LC_ALL", ""),
                    "DISPLAY": os.environ.get("DISPLAY", ""),
                    "WAYLAND_DISPLAY": os.environ.get("WAYLAND_DISPLAY", ""),
                    "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", ""),
                    "DBUS_SESSION_BUS_ADDRESS": os.environ.get(
                        "DBUS_SESSION_BUS_ADDRESS", ""
                    ),
                },
            )
        except subprocess.TimeoutExpired as error:
            raise ControlError("La autorización agotó el tiempo de espera.") from error
        except OSError as error:
            raise ControlError(f"No se pudo iniciar el helper: {error.strerror}.") from error
        response = _decode_response(result.stdout)
        if result.returncode == 0 and response.get("ok") is not True:
            raise ControlError("El helper devolvió una respuesta incorrecta.")
        if result.returncode != 0:
            message = response.get("error")
            if result.returncode in {126, 127}:
                message = "Autorización cancelada o no disponible."
            raise ControlError(str(message or result.stderr.strip() or "Operación rechazada."))
        payload = response.get("result")
        if not isinstance(payload, dict):
            raise ControlError("El helper devolvió una respuesta incorrecta.")
        return payload


def _decode_response(payload: str) -> dict[str, object]:
    try:
        document = json.loads(payload)
    except json.JSONDecodeError:
        return {}
    return document if isinstance(document, dict) else {}


def _read_public_policy() -> dict[str, object]:
    try:
        document = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"mode": "auto", "fixed_rpm": 2500, "curve": []}
    return document if isinstance(document, dict) else {"mode": "auto"}


def _read_public_rgb_configuration() -> RgbConfiguration | None:
    try:
        return rgb_configuration_from_json(
            RGB_CONFIG_PATH.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None


def _service_is_active() -> bool:
    try:
        result = subprocess.run(
            [str(SYSTEMCTL_PATH), "is-active", "--quiet", FAN_SERVICE_NAME],
            check=False,
            timeout=5,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0
