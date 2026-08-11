"""Strict persistence contract for the root-owned fan configuration."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Final

from legion_control.domain import DEFAULT_CURVE, CurvePoint, FanCurve, FanMode, FanPolicy


CONFIG_VERSION: Final = 1
MAX_CONFIG_BYTES: Final = 4096
EXPECTED_KEYS: Final = frozenset({"version", "mode", "fixed_rpm", "curve"})
EXPECTED_POINT_KEYS: Final = frozenset({"temperature_c", "rpm"})


class ConfigurationError(ValueError):
    """A persisted or requested configuration is malformed."""


@dataclass(slots=True)
class ConfigStore:
    path: Path

    def load(self) -> FanPolicy:
        if not self.path.exists():
            return default_policy()
        size = self.path.stat().st_size
        if size > MAX_CONFIG_BYTES:
            raise ConfigurationError("La configuración supera 4096 bytes.")
        return policy_from_json(self.path.read_text(encoding="utf-8"))

    def save(self, policy: FanPolicy) -> None:
        self.path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        payload = policy_to_json(policy) + "\n"
        if len(payload.encode("utf-8")) > MAX_CONFIG_BYTES:
            raise ConfigurationError("La configuración supera 4096 bytes.")
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=".fan-config-",
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        try:
            temporary_path.chmod(0o644)
            os.replace(temporary_path, self.path)
            directory_fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary_path.unlink(missing_ok=True)


def default_policy() -> FanPolicy:
    return FanPolicy(mode=FanMode.AUTO, fixed_rpm=2500, curve=DEFAULT_CURVE)


def policy_from_json(payload: str) -> FanPolicy:
    if len(payload.encode("utf-8")) > MAX_CONFIG_BYTES:
        raise ConfigurationError("La configuración supera 4096 bytes.")
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ConfigurationError(f"JSON inválido: {error.msg}.") from error
    if not isinstance(document, dict):
        raise ConfigurationError("La configuración debe ser un objeto JSON.")
    if frozenset(document) != EXPECTED_KEYS:
        raise ConfigurationError("La configuración contiene claves incorrectas.")
    if document["version"] != CONFIG_VERSION:
        raise ConfigurationError(f"Solo se admite la versión {CONFIG_VERSION}.")
    try:
        mode = FanMode(document["mode"])
    except (TypeError, ValueError) as error:
        raise ConfigurationError("El modo debe ser auto, fixed o curve.") from error
    fixed_rpm = _require_integer(document["fixed_rpm"], "fixed_rpm")
    curve_document = document["curve"]
    if not isinstance(curve_document, list):
        raise ConfigurationError("curve debe ser una lista.")
    points = tuple(_point_from_document(item) for item in curve_document)
    return FanPolicy(mode=mode, fixed_rpm=fixed_rpm, curve=FanCurve(points))


def policy_to_json(policy: FanPolicy) -> str:
    document = {
        "version": CONFIG_VERSION,
        "mode": policy.mode.value,
        "fixed_rpm": policy.fixed_rpm,
        "curve": [
            {"temperature_c": point.temperature_c, "rpm": point.rpm}
            for point in policy.curve.points
        ],
    }
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _point_from_document(document: Any) -> CurvePoint:
    if not isinstance(document, dict) or frozenset(document) != EXPECTED_POINT_KEYS:
        raise ConfigurationError("Cada punto necesita temperature_c y rpm.")
    return CurvePoint(
        temperature_c=_require_integer(document["temperature_c"], "temperature_c"),
        rpm=_require_integer(document["rpm"], "rpm"),
    )


def _require_integer(value: Any, name: str) -> int:
    if type(value) is not int:
        raise ConfigurationError(f"{name} debe ser un entero.")
    return value
