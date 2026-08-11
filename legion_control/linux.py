"""Linux anti-corruption layer for Lenovo WMI and related telemetry."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, Iterable

from legion_control.domain import (
    EMERGENCY_FULL_SPEED_C,
    FanBounds,
    FanTargets,
    ThermalSnapshot,
)
from legion_control.power import (
    CustomPowerLimits,
    PowerLimitBounds,
    PowerLimitCapabilities,
)


SUPPORTED_PRODUCTS: Final = frozenset({"83LU"})
FEATURE_FILES: Final = {
    "conservation_mode": "conservation_mode",
    "fn_lock": "fn_lock",
    "camera_power": "camera_power",
}
NVIDIA_SMI: Final = Path("/usr/bin/nvidia-smi")
POWER_ATTRIBUTE_NAMES: Final = {
    "sustained": "ppt_pl1_spl",
    "slow": "ppt_pl2_sppt",
}


class HardwareError(RuntimeError):
    """The kernel interface is absent, unsafe, or rejected an operation."""


class UnsupportedHardwareError(HardwareError):
    """The laptop is not on the explicit product allowlist."""


@dataclass(frozen=True, slots=True)
class HardwarePaths:
    product_name: Path
    product_version: Path
    fan_hwmon: Path | None
    platform_profile: Path | None
    device_features: Path | None
    power_attributes: Path | None


@dataclass(frozen=True, slots=True)
class CapabilityReport:
    product: str
    product_version: str
    supported: bool
    fan_control: bool
    fan_minimum_rpm: int | None
    fan_maximum_rpm: int | None
    fan_step_rpm: int | None
    power_control: bool
    power_limits: PowerLimitCapabilities | None
    platform_profiles: tuple[str, ...]
    features: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        document = asdict(self)
        document["platform_profiles"] = list(self.platform_profiles)
        document["features"] = list(self.features)
        return document


@dataclass(frozen=True, slots=True)
class StatusReport:
    capabilities: CapabilityReport
    profile: str | None
    cpu_temperature_c: int | None
    gpu_temperature_c: int | None
    fan1_rpm: int | None
    fan2_rpm: int | None
    fan1_target_rpm: int | None
    fan2_target_rpm: int | None
    power_limits: CustomPowerLimits | None
    battery_percent: int | None
    battery_status: str | None
    features: dict[str, bool | None]

    def to_dict(self) -> dict[str, object]:
        document = asdict(self)
        document["capabilities"] = self.capabilities.to_dict()
        return document


class SysfsHardware:
    """Discovers known kernel drivers and exposes domain-shaped operations."""

    def __init__(self, root: Path = Path("/")) -> None:
        self._root = root.resolve()
        self._sys_root = self._root / "sys"
        self._paths = HardwarePaths(
            product_name=self._root / "sys/devices/virtual/dmi/id/product_name",
            product_version=self._root / "sys/devices/virtual/dmi/id/product_version",
            fan_hwmon=self._discover_named_directory(
                self._root / "sys/class/hwmon", "lenovo_wmi_other"
            ),
            platform_profile=self._discover_named_directory(
                self._root / "sys/class/platform-profile", "lenovo-wmi-gamezone"
            ),
            device_features=self._discover_device_features(),
            power_attributes=self._discover_power_attributes(),
        )

    def capabilities(self) -> CapabilityReport:
        product = self._read_optional_text(self._paths.product_name) or "desconocido"
        product_version = self._read_optional_text(self._paths.product_version) or product
        bounds = self._fan_bounds_or_none()
        power_limits = self._power_capabilities_or_none()
        profiles = self._profile_choices()
        features = tuple(
            feature
            for feature, filename in FEATURE_FILES.items()
            if self._paths.device_features is not None
            and (self._paths.device_features / filename).exists()
        )
        fan_directory = self._paths.fan_hwmon
        has_targets = (
            fan_directory is not None
            and (fan_directory / "fan1_target").exists()
            and (fan_directory / "fan2_target").exists()
        )
        return CapabilityReport(
            product=product,
            product_version=product_version,
            supported=product in SUPPORTED_PRODUCTS,
            fan_control=has_targets and bounds is not None,
            fan_minimum_rpm=bounds.minimum_rpm if bounds else None,
            fan_maximum_rpm=bounds.maximum_rpm if bounds else None,
            fan_step_rpm=bounds.step_rpm if bounds else None,
            power_control=power_limits is not None,
            power_limits=power_limits,
            platform_profiles=profiles,
            features=features,
        )

    def status(self) -> StatusReport:
        capabilities = self.capabilities()
        fan_directory = self._paths.fan_hwmon
        battery_directory = self._root / "sys/class/power_supply/BAT0"
        return StatusReport(
            capabilities=capabilities,
            profile=self._read_optional_text(
                self._profile_file("profile", required=False)
            ),
            cpu_temperature_c=self._read_cpu_temperature(),
            gpu_temperature_c=self._read_gpu_temperature(),
            fan1_rpm=self._read_optional_integer(self._child(fan_directory, "fan1_input")),
            fan2_rpm=self._read_optional_integer(self._child(fan_directory, "fan2_input")),
            fan1_target_rpm=self._read_optional_integer(
                self._child(fan_directory, "fan1_target")
            ),
            fan2_target_rpm=self._read_optional_integer(
                self._child(fan_directory, "fan2_target")
            ),
            power_limits=self._read_power_limits(),
            battery_percent=self._read_optional_integer(battery_directory / "capacity"),
            battery_status=self._read_optional_text(battery_directory / "status"),
            features={
                feature: self._read_feature(feature)
                for feature in FEATURE_FILES
                if feature in capabilities.features
            },
        )

    def thermal_snapshot(self) -> ThermalSnapshot:
        cpu_temperature = self._read_cpu_temperature()
        gpu_temperature = (
            None
            if cpu_temperature is not None
            and cpu_temperature >= EMERGENCY_FULL_SPEED_C
            else self._read_gpu_temperature()
        )
        fan_directory = self._paths.fan_hwmon
        fan1_rpm = self._read_optional_integer(self._child(fan_directory, "fan1_input"))
        fan2_rpm = self._read_optional_integer(self._child(fan_directory, "fan2_input"))
        if fan1_rpm is None or fan2_rpm is None:
            raise HardwareError("No se pueden leer ambos ventiladores.")
        return ThermalSnapshot(
            cpu_temperature_c=cpu_temperature,
            gpu_temperature_c=gpu_temperature,
            fan1_rpm=fan1_rpm,
            fan2_rpm=fan2_rpm,
        )

    def fan_bounds(self) -> FanBounds:
        bounds = self._fan_bounds_or_none()
        if bounds is None:
            raise HardwareError("El controlador no publica límites de ventilador.")
        return bounds

    def set_profile(self, profile: str) -> None:
        self.require_supported()
        choices = self._profile_choices()
        if profile not in choices:
            raise HardwareError(f"Perfil no admitido: {profile}.")
        self._write_text(self._profile_file("profile"), profile)
        observed = self._read_optional_text(self._profile_file("profile"))
        if observed != profile:
            raise HardwareError(f"El firmware no confirmó el perfil {profile}.")

    def current_profile(self) -> str:
        profile = self._read_optional_text(self._profile_file("profile"))
        if profile is None:
            raise HardwareError("No se puede leer el perfil térmico actual.")
        return profile

    def set_fan_targets(self, targets: FanTargets) -> None:
        self.require_supported()
        bounds = self.fan_bounds()
        fan1 = bounds.quantize(targets.fan1_rpm)
        fan2 = bounds.quantize(targets.fan2_rpm)
        if fan1 != targets.fan1_rpm or fan2 != targets.fan2_rpm:
            raise HardwareError("El objetivo no respeta los límites o pasos del hardware.")
        fan_directory = self._require_fan_directory()
        errors: list[str] = []
        for filename, value in (("fan1_target", fan1), ("fan2_target", fan2)):
            try:
                self._write_text(fan_directory / filename, str(value))
            except HardwareError as error:
                errors.append(str(error))
        if errors:
            detail = self._fan_restore_detail()
            raise HardwareError(
                "No se pudieron fijar ambos ventiladores: "
                + " ".join(errors)
                + detail
            )
        observed = (
            self._read_optional_integer(fan_directory / "fan1_target"),
            self._read_optional_integer(fan_directory / "fan2_target"),
        )
        if observed != (fan1, fan2):
            detail = self._fan_restore_detail()
            raise HardwareError(
                "El firmware no confirmó ambos objetivos de ventilador."
                + detail
            )

    def power_capabilities(self) -> PowerLimitCapabilities:
        capabilities = self._power_capabilities_or_none()
        if capabilities is None:
            raise HardwareError("El kernel no publica límites de potencia Lenovo.")
        return capabilities

    def current_power_limits(self) -> CustomPowerLimits:
        limits = self._read_power_limits()
        if limits is None:
            raise HardwareError("No se pueden leer ambos límites de potencia.")
        return limits

    def set_power_limits(self, limits: CustomPowerLimits) -> None:
        self.require_supported()
        if self._read_optional_text(self._profile_file("profile")) != "custom":
            raise HardwareError(
                "Los límites de potencia solo pueden escribirse en perfil Custom."
            )
        capabilities = self.power_capabilities()
        limits.validate_for(capabilities)
        previous = self._read_power_limits()
        if previous is None:
            raise HardwareError("No se pueden leer ambos límites de potencia.")
        values = (
            ("sustained", limits.sustained_w),
            ("slow", limits.slow_w),
        )
        try:
            for name, value in values:
                self._write_power_value(name, value)
        except HardwareError as error:
            rollback_errors = self._restore_power_limits(previous)
            detail = (
                f" Restauración incompleta: {' '.join(rollback_errors)}"
                if rollback_errors
                else ""
            )
            raise HardwareError(
                f"No se aplicaron ambos límites de potencia.{detail}"
            ) from error

    def restore_firmware_control(self) -> None:
        fan_directory = self._paths.fan_hwmon
        if fan_directory is None:
            raise HardwareError("No existe el controlador de ventiladores Lenovo.")
        errors: list[str] = []
        for filename in ("fan1_target", "fan2_target"):
            try:
                self._write_text(fan_directory / filename, "0")
            except HardwareError as error:
                errors.append(str(error))
        if errors:
            raise HardwareError("No se pudo restaurar el control automático: " + " ".join(errors))

    def _fan_restore_detail(self) -> str:
        try:
            self.restore_firmware_control()
        except HardwareError as error:
            return f" Restauración incompleta: {error}"
        return ""

    def set_feature(self, feature: str, enabled: bool) -> None:
        self.require_supported()
        filename = FEATURE_FILES.get(feature)
        if filename is None:
            raise HardwareError(f"Función no admitida: {feature}.")
        directory = self._paths.device_features
        if directory is None or not (directory / filename).exists():
            raise HardwareError(f"El kernel no publica {feature}.")
        self._write_text(directory / filename, "1" if enabled else "0")
        if self._read_feature(feature) is not enabled:
            raise HardwareError(f"El firmware no confirmó {feature}.")

    def require_supported(self) -> None:
        capabilities = self.capabilities()
        if not capabilities.supported:
            raise UnsupportedHardwareError(
                f"Modelo {capabilities.product} no admitido. Solo se admite 83LU."
            )

    def _fan_bounds_or_none(self) -> FanBounds | None:
        directory = self._paths.fan_hwmon
        if directory is None:
            return None
        minimums = self._integers(directory, ("fan1_min", "fan2_min"))
        maximums = self._integers(directory, ("fan1_max", "fan2_max"))
        steps = self._integers(directory, ("fan1_div", "fan2_div"))
        if not minimums or not maximums:
            return None
        try:
            return FanBounds(
                minimum_rpm=max(minimums),
                maximum_rpm=min(maximums),
                step_rpm=max(steps, default=100),
            )
        except ValueError:
            return None

    def _power_capabilities_or_none(self) -> PowerLimitCapabilities | None:
        sustained = self._power_bounds("sustained")
        slow = self._power_bounds("slow")
        if sustained is None or slow is None:
            return None
        return PowerLimitCapabilities(sustained=sustained, slow=slow)

    def _power_bounds(self, name: str) -> PowerLimitBounds | None:
        directory = self._power_attribute(name)
        if directory is None:
            return None
        values = tuple(
            self._read_optional_integer(directory / filename)
            for filename in (
                "min_value",
                "max_value",
                "scalar_increment",
                "default_value",
            )
        )
        if any(value is None for value in values):
            return None
        try:
            return PowerLimitBounds(*(int(value) for value in values))
        except ValueError:
            return None

    def _read_power_limits(self) -> CustomPowerLimits | None:
        sustained = self._read_power_value("sustained")
        slow = self._read_power_value("slow")
        if sustained is None or slow is None:
            return None
        try:
            return CustomPowerLimits(sustained_w=sustained, slow_w=slow)
        except ValueError:
            return None

    def _read_power_value(self, name: str) -> int | None:
        directory = self._power_attribute(name)
        return self._read_optional_integer(
            directory / "current_value" if directory else None
        )

    def _write_power_value(self, name: str, value: int) -> None:
        directory = self._power_attribute(name)
        if directory is None:
            raise HardwareError(f"No existe el límite de potencia {name}.")
        path = directory / "current_value"
        self._write_text(path, str(value))
        if self._read_optional_integer(path) != value:
            raise HardwareError(f"El firmware no confirmó {path.parent.name}.")

    def _restore_power_limits(self, limits: CustomPowerLimits) -> list[str]:
        errors: list[str] = []
        for name, value in (
            ("sustained", limits.sustained_w),
            ("slow", limits.slow_w),
        ):
            try:
                self._write_power_value(name, value)
            except HardwareError as error:
                errors.append(str(error))
        return errors

    def _power_attribute(self, name: str) -> Path | None:
        filename = POWER_ATTRIBUTE_NAMES.get(name)
        parent = self._paths.power_attributes
        if filename is None or parent is None:
            return None
        directory = parent / filename
        return directory if directory.is_dir() else None

    def _profile_choices(self) -> tuple[str, ...]:
        choices = self._read_optional_text(self._profile_file("choices", required=False))
        return tuple(choices.split()) if choices else ()

    def _profile_file(self, filename: str, required: bool = True) -> Path | None:
        directory = self._paths.platform_profile
        path = directory / filename if directory else None
        if required and (path is None or not path.exists()):
            raise HardwareError("No existe el perfil lenovo-wmi-gamezone.")
        return path

    def _read_cpu_temperature(self) -> int | None:
        candidates: list[int] = []
        for directory in self._hwmon_directories():
            name = self._read_optional_text(directory / "name")
            if name not in {"coretemp", "k10temp", "zenpower"}:
                continue
            for input_file in directory.glob("temp*_input"):
                label = self._read_optional_text(input_file.with_name(
                    input_file.name.replace("_input", "_label")
                ))
                if label in {"Package id 0", "Tctl", "Tdie"}:
                    value = self._read_optional_integer(input_file)
                    if value is not None:
                        candidates.append(value // 1000)
        return max(candidates, default=None)

    def _read_gpu_temperature(self) -> int | None:
        sysfs_candidates: list[int] = []
        for directory in self._hwmon_directories():
            name = self._read_optional_text(directory / "name") or ""
            if name not in {"amdgpu", "nvidia"}:
                continue
            for input_file in directory.glob("temp*_input"):
                value = self._read_optional_integer(input_file)
                if value is not None:
                    sysfs_candidates.append(value // 1000)
        if sysfs_candidates:
            return max(sysfs_candidates)
        if self._root != Path("/") or not NVIDIA_SMI.exists():
            return None
        try:
            result = subprocess.run(
                [
                    str(NVIDIA_SMI),
                    "--query-gpu=temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=4,
                env={
                    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
                    "LANG": "C",
                    "LC_ALL": "C",
                },
            )
        except (OSError, subprocess.SubprocessError):
            return None
        values = [
            int(line)
            for line in result.stdout.splitlines()
            if line.strip().isdigit()
        ]
        return max(values, default=None)

    def _read_feature(self, feature: str) -> bool | None:
        directory = self._paths.device_features
        filename = FEATURE_FILES.get(feature)
        if directory is None or filename is None:
            return None
        value = self._read_optional_integer(directory / filename)
        return bool(value) if value in {0, 1} else None

    def _discover_named_directory(self, parent: Path, expected_name: str) -> Path | None:
        if not parent.exists():
            return None
        for directory in sorted(parent.iterdir()):
            resolved = self._safe_resolve(directory)
            if resolved is None or not resolved.is_dir():
                continue
            if self._read_optional_text(resolved / "name") == expected_name:
                return resolved
        return None

    def _discover_device_features(self) -> Path | None:
        candidate = self._root / "sys/bus/platform/devices/VPC2004:00"
        resolved = self._safe_resolve(candidate)
        return resolved if resolved is not None and resolved.is_dir() else None

    def _discover_power_attributes(self) -> Path | None:
        parent = self._root / "sys/class/firmware-attributes"
        if not parent.exists():
            return None
        for directory in sorted(parent.iterdir()):
            if not directory.name.startswith("lenovo-wmi-other"):
                continue
            resolved = self._safe_resolve(directory / "attributes")
            if resolved is not None and resolved.is_dir():
                return resolved
        return None

    def _safe_resolve(self, path: Path) -> Path | None:
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            return None
        try:
            resolved.relative_to(self._sys_root.resolve())
        except ValueError:
            return None
        return resolved

    def _hwmon_directories(self) -> Iterable[Path]:
        parent = self._root / "sys/class/hwmon"
        if not parent.exists():
            return ()
        return tuple(
            resolved
            for path in sorted(parent.iterdir())
            if (resolved := self._safe_resolve(path)) is not None
        )

    def _require_fan_directory(self) -> Path:
        if self._paths.fan_hwmon is None:
            raise HardwareError("No existe el controlador lenovo_wmi_other.")
        return self._paths.fan_hwmon

    @staticmethod
    def _child(parent: Path | None, filename: str) -> Path | None:
        return parent / filename if parent is not None else None

    def _integers(self, directory: Path, filenames: tuple[str, ...]) -> list[int]:
        return [
            value
            for filename in filenames
            if (value := self._read_optional_integer(directory / filename)) is not None
        ]

    @staticmethod
    def _read_optional_text(path: Path | None) -> str | None:
        if path is None:
            return None
        try:
            return path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            return None

    def _read_optional_integer(self, path: Path | None) -> int | None:
        text = self._read_optional_text(path)
        try:
            return int(text) if text is not None else None
        except ValueError:
            return None

    @staticmethod
    def _write_text(path: Path, value: str) -> None:
        try:
            with path.open("w", encoding="ascii") as stream:
                stream.write(value)
        except OSError as error:
            raise HardwareError(f"No se pudo escribir {path.name}: {error.strerror}.") from error


def status_as_json(hardware: SysfsHardware) -> str:
    return json.dumps(hardware.status().to_dict(), ensure_ascii=False, sort_keys=True)
