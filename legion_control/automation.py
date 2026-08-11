"""User-owned, transition-based AC/battery scene automation."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Final

from legion_control.scenes import SceneSlot


AUTOMATION_CONFIG_VERSION: Final = 1
MAX_AUTOMATION_CONFIG_BYTES: Final = 2048
EXPECTED_AUTOMATION_KEYS: Final = frozenset(
    {"version", "ac_enabled", "ac_scene", "battery_enabled", "battery_scene"}
)


class PowerSource(StrEnum):
    AC = "ac"
    BATTERY = "battery"


@dataclass(frozen=True, slots=True)
class AutomationConfig:
    ac_enabled: bool = False
    ac_scene: SceneSlot = SceneSlot.WORK
    battery_enabled: bool = False
    battery_scene: SceneSlot = SceneSlot.SILENCE

    def __post_init__(self) -> None:
        if type(self.ac_enabled) is not bool or type(self.battery_enabled) is not bool:
            raise ValueError("Las automatizaciones deben ser booleanas.")
        if not isinstance(self.ac_scene, SceneSlot):
            raise ValueError("La escena de corriente no es válida.")
        if not isinstance(self.battery_scene, SceneSlot):
            raise ValueError("La escena de batería no es válida.")

    def to_dict(self) -> dict[str, object]:
        return {
            "version": AUTOMATION_CONFIG_VERSION,
            "ac_enabled": self.ac_enabled,
            "ac_scene": self.ac_scene.value,
            "battery_enabled": self.battery_enabled,
            "battery_scene": self.battery_scene.value,
        }


@dataclass(slots=True)
class AutomationStore:
    path: Path

    def load(self) -> AutomationConfig:
        if not self.path.exists():
            return AutomationConfig()
        if self.path.stat().st_size > MAX_AUTOMATION_CONFIG_BYTES:
            raise ValueError("La automatización guardada es demasiado grande.")
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"JSON de automatización inválido: {error.msg}.") from error
        return automation_config_from_document(document)

    def save(self, configuration: AutomationConfig) -> None:
        payload = (
            json.dumps(
                configuration.to_dict(),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        )
        if len(payload.encode("utf-8")) > MAX_AUTOMATION_CONFIG_BYTES:
            raise ValueError("La automatización guardada es demasiado grande.")
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=".automation-",
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        try:
            temporary_path.chmod(0o600)
            os.replace(temporary_path, self.path)
            _sync_directory(self.path.parent)
        finally:
            temporary_path.unlink(missing_ok=True)


class PowerSourceAutomation:
    """Returns one scene only after a confirmed power-source transition."""

    def __init__(self) -> None:
        self._last_source: PowerSource | None = None

    def observe(
        self,
        status: dict[str, object],
        configuration: AutomationConfig,
    ) -> SceneSlot | None:
        source = source_from_status(status)
        if source is None:
            return None
        previous = self._last_source
        self._last_source = source
        if previous is None or previous is source:
            return None
        if source is PowerSource.AC and configuration.ac_enabled:
            return configuration.ac_scene
        if source is PowerSource.BATTERY and configuration.battery_enabled:
            return configuration.battery_scene
        return None


def source_from_status(status: dict[str, object]) -> PowerSource | None:
    battery_status = status.get("battery_status")
    if battery_status == "Discharging":
        return PowerSource.BATTERY
    if battery_status in {"Charging", "Full", "Not charging"}:
        return PowerSource.AC
    return None


def automation_config_from_document(document: Any) -> AutomationConfig:
    if not isinstance(document, dict) or frozenset(document) != EXPECTED_AUTOMATION_KEYS:
        raise ValueError("La automatización contiene claves incorrectas.")
    if document["version"] != AUTOMATION_CONFIG_VERSION:
        raise ValueError(f"Solo se admite automatización versión {AUTOMATION_CONFIG_VERSION}.")
    try:
        return AutomationConfig(
            ac_enabled=document["ac_enabled"],
            ac_scene=SceneSlot(document["ac_scene"]),
            battery_enabled=document["battery_enabled"],
            battery_scene=SceneSlot(document["battery_scene"]),
        )
    except (TypeError, ValueError) as error:
        raise ValueError("La automatización contiene valores inválidos.") from error


def default_automation_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    parent = Path(config_home) if config_home else Path.home() / ".config"
    return parent / "legion-control/automation.json"


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
