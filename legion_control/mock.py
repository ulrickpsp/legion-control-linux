"""Safe in-memory backend for UI development and visual testing."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field, replace

from legion_control.config import default_policy
from legion_control.domain import FanMode, FanPolicy
from legion_control.effects import EffectSettings, default_effect_settings
from legion_control.power import (
    CustomPowerLimits,
    PowerLimitBounds,
    PowerLimitCapabilities,
)
from legion_control.rgb import (
    RgbColor,
    RgbConfiguration,
    solid_rgb_configuration,
)


@dataclass(slots=True)
class MockControlClient:
    profile: str = "performance"
    policy: FanPolicy = field(default_factory=default_policy)
    power_limits: CustomPowerLimits = field(default_factory=lambda: CustomPowerLimits(70, 125))
    rgb_configuration: RgbConfiguration = field(
        default_factory=lambda: solid_rgb_configuration(
            RgbColor(229, 32, 47),
            70,
        )
    )
    rgb_effect: EffectSettings = field(default_factory=default_effect_settings)
    features: dict[str, bool] = field(
        default_factory=lambda: {
            "conservation_mode": True,
            "fn_lock": False,
            "camera_power": True,
        }
    )

    def read_status(self) -> dict[str, object]:
        wave = math.sin(time.monotonic() / 8)
        cpu = round(58 + 5 * wave)
        gpu = round(45 + 3 * wave)
        target = 0
        if self.policy.mode is FanMode.FIXED:
            target = self.policy.fixed_rpm
        elif self.policy.mode is FanMode.CURVE:
            target = self.policy.curve.target_at(max(cpu, gpu), self._bounds())
        observed = target or round((2100 + max(0, wave) * 400) / 100) * 100
        return {
            "capabilities": {
                "product": "83LU",
                "product_version": "Legion Pro 5 16IAX10H",
                "supported": True,
                "fan_control": True,
                "fan_minimum_rpm": 1700,
                "fan_maximum_rpm": 5300,
                "fan_step_rpm": 100,
                "power_control": True,
                "power_limits": self._power_capabilities().to_dict(),
                "rgb_control": True,
                "rgb_zones": 24,
                "platform_profiles": [
                    "low-power",
                    "balanced",
                    "performance",
                    "max-power",
                    "custom",
                ],
                "features": list(self.features),
            },
            "profile": self.profile,
            "cpu_temperature_c": cpu,
            "gpu_temperature_c": gpu,
            "fan1_rpm": observed,
            "fan2_rpm": observed,
            "fan1_target_rpm": target,
            "fan2_target_rpm": target,
            "power_limits": self.power_limits.to_dict(),
            "battery_percent": 78,
            "battery_status": "Charging",
            "features": dict(self.features),
            "fan_service_active": self.policy.mode is not FanMode.AUTO,
            "fan_policy": {
                "mode": self.policy.mode.value,
                "fixed_rpm": self.policy.fixed_rpm,
                "curve": [
                    {"temperature_c": point.temperature_c, "rpm": point.rpm}
                    for point in self.policy.curve.points
                ],
            },
            "rgb_configuration_known": True,
            "rgb_configuration": self.rgb_configuration.to_dict(),
            "rgb_effect": self.rgb_effect.to_dict(),
            "rgb_effect_active": self.rgb_effect.enabled,
        }

    def set_profile(self, profile: str) -> dict[str, object]:
        self.profile = profile
        if profile != "custom":
            self.policy = default_policy()
        return {"profile": profile}

    def set_fan_policy(self, policy: FanPolicy) -> dict[str, object]:
        policy.validate_for(self._bounds())
        self.policy = policy
        self.profile = "custom"
        return {"mode": policy.mode.value, "service_active": True}

    def set_custom_configuration(
        self,
        policy: FanPolicy,
        power_limits: CustomPowerLimits,
    ) -> dict[str, object]:
        policy.validate_for(self._bounds())
        power_limits.validate_for(self._power_capabilities())
        self.policy = policy
        self.power_limits = power_limits
        self.profile = "custom"
        return {
            "mode": policy.mode.value,
            "profile": "custom",
            "power_limits": power_limits.to_dict(),
            "service_active": True,
        }

    def restore_auto(self) -> dict[str, object]:
        self.policy = default_policy()
        return {"mode": "auto", "service_active": False}

    def set_feature(self, feature: str, enabled: bool) -> dict[str, object]:
        if feature not in self.features:
            raise ValueError(f"Función no disponible: {feature}.")
        self.features[feature] = enabled
        return {"feature": feature, "enabled": enabled}

    def set_rgb_configuration(
        self,
        configuration: RgbConfiguration,
    ) -> dict[str, object]:
        self.rgb_configuration = configuration
        self.rgb_effect = replace(self.rgb_effect, enabled=False)
        return {
            "enabled": configuration.enabled,
            "brightness_percent": configuration.brightness_percent,
            "zones": len(configuration.zones),
        }

    def set_rgb_effect(self, settings: EffectSettings) -> dict[str, object]:
        self.rgb_effect = settings
        return {
            "effect": settings.kind.value,
            "speed_percent": settings.speed_percent,
            "brightness_percent": settings.brightness_percent,
            "service_active": settings.enabled,
        }

    @staticmethod
    def _bounds():
        from legion_control.domain import FanBounds

        return FanBounds(1700, 5300, 100)

    @staticmethod
    def _power_capabilities() -> PowerLimitCapabilities:
        return PowerLimitCapabilities(
            sustained=PowerLimitBounds(50, 135, 1, 70),
            slow=PowerLimitBounds(60, 210, 1, 125),
        )
