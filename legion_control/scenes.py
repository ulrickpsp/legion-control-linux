"""Three strict, user-owned Legion scenes for repeated daily use."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Final, Protocol

from legion_control.config import policy_from_json, policy_to_json
from legion_control.domain import DEFAULT_CURVE, FanMode, FanPolicy
from legion_control.power import (
    CustomPowerLimits,
    power_limits_from_document,
)
from legion_control.rgb import (
    RgbColor,
    RgbConfiguration,
    rgb_configuration_from_document,
    solid_rgb_configuration,
)


SCENE_CONFIG_VERSION: Final = 1
MAX_SCENE_CONFIG_BYTES: Final = 32768
EXPECTED_ROOT_KEYS: Final = frozenset({"version", "scenes"})
EXPECTED_SCENE_KEYS: Final = frozenset(
    {"slot", "profile", "fan_policy", "power_limits", "rgb_configuration"}
)
ALLOWED_SCENE_PROFILES: Final = frozenset(
    {"low-power", "balanced", "performance", "max-power", "custom"}
)


class SceneSlot(StrEnum):
    SILENCE = "silence"
    WORK = "work"
    GAME = "game"


class SceneControlPort(Protocol):
    def set_profile(self, profile: str) -> dict[str, object]: ...
    def set_custom_configuration(
        self,
        policy: FanPolicy,
        power_limits: CustomPowerLimits,
    ) -> dict[str, object]: ...
    def set_rgb_configuration(
        self,
        configuration: RgbConfiguration,
    ) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class Scene:
    slot: SceneSlot
    profile: str
    fan_policy: FanPolicy
    power_limits: CustomPowerLimits | None
    rgb_configuration: RgbConfiguration

    def __post_init__(self) -> None:
        if not isinstance(self.slot, SceneSlot):
            raise ValueError("La escena necesita una ranura conocida.")
        if self.profile not in ALLOWED_SCENE_PROFILES:
            raise ValueError(f"Perfil de escena no admitido: {self.profile}.")
        if self.fan_policy.mode is FanMode.AUTO:
            if self.profile == "custom" or self.power_limits is not None:
                raise ValueError("Una escena automática no puede incluir potencia Custom.")
        elif self.profile != "custom" or self.power_limits is None:
            raise ValueError("Una escena con ventilación manual necesita perfil y potencia Custom.")


@dataclass(slots=True)
class SceneStore:
    path: Path

    def load(self) -> dict[SceneSlot, Scene]:
        if self.path.stat().st_size > MAX_SCENE_CONFIG_BYTES:
            raise ValueError("Las escenas guardadas son demasiado grandes.")
        document = _load_document(self.path.read_text(encoding="utf-8"))
        return _scenes_from_document(document)

    def load_or_defaults(
        self,
        defaults: dict[SceneSlot, Scene],
    ) -> dict[SceneSlot, Scene]:
        if not self.path.exists():
            return dict(defaults)
        return self.load()

    def save(self, scenes: dict[SceneSlot, Scene]) -> None:
        if set(scenes) != set(SceneSlot):
            raise ValueError("Deben guardarse Silencio, Trabajo y Juego.")
        document = {
            "version": SCENE_CONFIG_VERSION,
            "scenes": [_scene_to_document(scenes[slot]) for slot in SceneSlot],
        }
        payload = (
            json.dumps(
                document,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        )
        if len(payload.encode("utf-8")) > MAX_SCENE_CONFIG_BYTES:
            raise ValueError("Las escenas guardadas son demasiado grandes.")
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=".scenes-",
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


def default_scenes(
    custom_power_limits: CustomPowerLimits,
) -> dict[SceneSlot, Scene]:
    automatic = FanPolicy(FanMode.AUTO, 2500, DEFAULT_CURVE)
    return {
        SceneSlot.SILENCE: Scene(
            slot=SceneSlot.SILENCE,
            profile="low-power",
            fan_policy=automatic,
            power_limits=None,
            rgb_configuration=solid_rgb_configuration(
                RgbColor(229, 72, 77),
                0,
                enabled=False,
            ),
        ),
        SceneSlot.WORK: Scene(
            slot=SceneSlot.WORK,
            profile="balanced",
            fan_policy=automatic,
            power_limits=None,
            rgb_configuration=solid_rgb_configuration(
                RgbColor(235, 239, 245),
                25,
            ),
        ),
        SceneSlot.GAME: Scene(
            slot=SceneSlot.GAME,
            profile="custom",
            fan_policy=FanPolicy(FanMode.CURVE, 2500, DEFAULT_CURVE),
            power_limits=custom_power_limits,
            rgb_configuration=solid_rgb_configuration(
                RgbColor(229, 32, 47),
                70,
            ),
        ),
    }


def default_scene_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    parent = Path(config_home) if config_home else Path.home() / ".config"
    return parent / "legion-control/scenes.json"


def load_scenes_for_status(
    store: SceneStore,
    status: dict[str, object],
) -> dict[SceneSlot, Scene]:
    return store.load_or_defaults(default_scenes(default_power_limits_from_status(status)))


def default_power_limits_from_status(status: dict[str, object]) -> CustomPowerLimits:
    current = status.get("power_limits")
    if isinstance(current, dict):
        try:
            return power_limits_from_document(current)
        except ValueError:
            pass
    capabilities = _dictionary(status.get("capabilities"))
    bounds = _dictionary(capabilities.get("power_limits"))
    sustained = _dictionary(bounds.get("sustained")).get("default_w")
    slow = _dictionary(bounds.get("slow")).get("default_w")
    if type(sustained) is int and type(slow) is int:
        return CustomPowerLimits(sustained, slow)
    return CustomPowerLimits(70, 125)


def apply_scene(
    client: SceneControlPort,
    scene: Scene,
    *,
    rgb_available: bool,
) -> dict[str, object]:
    if rgb_available:
        client.set_rgb_configuration(scene.rgb_configuration)
    if scene.fan_policy.mode is FanMode.AUTO:
        return client.set_profile(scene.profile)
    if scene.power_limits is None:
        raise ValueError("La escena Custom no contiene límites de potencia.")
    return client.set_custom_configuration(scene.fan_policy, scene.power_limits)


def _scene_to_document(scene: Scene) -> dict[str, object]:
    fan_policy = json.loads(policy_to_json(scene.fan_policy))
    fan_policy.pop("version")
    return {
        "slot": scene.slot.value,
        "profile": scene.profile,
        "fan_policy": fan_policy,
        "power_limits": (scene.power_limits.to_dict() if scene.power_limits is not None else None),
        "rgb_configuration": scene.rgb_configuration.to_dict(),
    }


def _scenes_from_document(document: dict[str, Any]) -> dict[SceneSlot, Scene]:
    raw_scenes = document["scenes"]
    if not isinstance(raw_scenes, list) or len(raw_scenes) != len(SceneSlot):
        raise ValueError("Deben existir exactamente tres escenas.")
    scenes = {scene.slot: scene for item in raw_scenes for scene in (_scene_from_document(item),)}
    if set(scenes) != set(SceneSlot):
        raise ValueError("Las escenas contienen ranuras duplicadas o ausentes.")
    return scenes


def _scene_from_document(document: Any) -> Scene:
    if not isinstance(document, dict) or frozenset(document) != EXPECTED_SCENE_KEYS:
        raise ValueError("Una escena contiene claves incorrectas.")
    try:
        slot = SceneSlot(document["slot"])
    except (TypeError, ValueError) as error:
        raise ValueError("Ranura de escena no admitida.") from error
    profile = document["profile"]
    if not isinstance(profile, str):
        raise ValueError("El perfil de escena debe ser texto.")
    fan_document = document["fan_policy"]
    if not isinstance(fan_document, dict):
        raise ValueError("La política de ventilación debe ser un objeto.")
    fan_policy = policy_from_json(
        json.dumps(
            {"version": 1, **fan_document},
            ensure_ascii=False,
        )
    )
    power_document = document["power_limits"]
    power_limits = None if power_document is None else power_limits_from_document(power_document)
    rgb_configuration = rgb_configuration_from_document(document["rgb_configuration"])
    return Scene(
        slot=slot,
        profile=profile,
        fan_policy=fan_policy,
        power_limits=power_limits,
        rgb_configuration=rgb_configuration,
    )


def _load_document(payload: str) -> dict[str, Any]:
    if len(payload.encode("utf-8")) > MAX_SCENE_CONFIG_BYTES:
        raise ValueError("Las escenas guardadas son demasiado grandes.")
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ValueError(f"JSON de escenas inválido: {error.msg}.") from error
    if not isinstance(document, dict) or frozenset(document) != EXPECTED_ROOT_KEYS:
        raise ValueError("El archivo de escenas contiene claves incorrectas.")
    if document["version"] != SCENE_CONFIG_VERSION:
        raise ValueError(f"Solo se admiten escenas versión {SCENE_CONFIG_VERSION}.")
    return document


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _dictionary(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
