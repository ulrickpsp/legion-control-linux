from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from legion_control.config import ConfigStore, default_policy
from legion_control.domain import DEFAULT_CURVE, FanBounds, FanMode, FanPolicy
from legion_control.effects import (
    EffectConfigStore,
    EffectKind,
    EffectSettings,
    effect_settings_to_json,
)
from legion_control.helper import (
    HelperError,
    PrivilegedController,
    SystemdUnitService,
    _dispatch,
    _exclusive_control,
)
from legion_control.power import CustomPowerLimits, PowerLimitBounds, PowerLimitCapabilities
from legion_control.rgb import (
    RgbColor,
    RgbConfigStore,
    RgbConfiguration,
    RgbHardwareError,
    solid_rgb_configuration,
)


class FakeHardware:
    def __init__(self, *, fail_power: bool = False) -> None:
        self.profile = "performance"
        self.features: dict[str, bool] = {}
        self.restore_count = 0
        self.power_limits = CustomPowerLimits(60, 119)
        self.fail_power = fail_power

    def fan_bounds(self) -> FanBounds:
        return FanBounds(1700, 5300, 100)

    def set_profile(self, profile: str) -> None:
        self.profile = profile

    def current_profile(self) -> str:
        return self.profile

    def power_capabilities(self) -> PowerLimitCapabilities:
        return PowerLimitCapabilities(
            sustained=PowerLimitBounds(50, 135, 1, 70),
            slow=PowerLimitBounds(60, 210, 1, 125),
        )

    def current_power_limits(self) -> CustomPowerLimits:
        return self.power_limits

    def set_power_limits(self, limits: CustomPowerLimits) -> None:
        if self.fail_power:
            raise HelperError("fallo de potencia simulado")
        limits.validate_for(self.power_capabilities())
        self.power_limits = limits

    def set_feature(self, feature: str, enabled: bool) -> None:
        self.features[feature] = enabled

    def restore_firmware_control(self) -> None:
        self.restore_count += 1

    def status(self) -> SimpleNamespace:
        """Only the fields the controller adds on top are under test here."""

        return SimpleNamespace(to_dict=lambda: {"profile": self.profile})


class FakeRgbHardware:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.available = True
        self.applied: RgbConfiguration | None = None

    def is_available(self) -> bool:
        return self.available

    def apply(self, configuration: RgbConfiguration) -> None:
        if self.fail:
            raise RgbHardwareError("fallo RGB simulado")
        self.applied = configuration


class FakeService:
    def __init__(
        self,
        fail_activation: bool = False,
        fail_deactivation: bool = False,
    ) -> None:
        self.active = False
        self.fail_activation = fail_activation
        self.fail_deactivation = fail_deactivation
        self.deactivate_count = 0

    def activate(self) -> None:
        if self.fail_activation:
            raise HelperError("fallo simulado")
        self.active = True

    def deactivate(self) -> None:
        self.active = False
        self.deactivate_count += 1
        if self.fail_deactivation:
            raise HelperError("no se pudo detener")

    def is_active(self) -> bool:
        return self.active


class PrivilegedControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.store = ConfigStore(Path(self.temporary.name) / "fan-config.json")
        self.hardware = FakeHardware()
        self.service = FakeService()
        self.controller = PrivilegedController(self.hardware, self.store, self.service)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_curve_configuration_sets_custom_then_activates_service(self) -> None:
        policy = FanPolicy(FanMode.CURVE, 2500, DEFAULT_CURVE)
        result = self.controller.set_fan_policy(policy)
        self.assertEqual(self.hardware.profile, "custom")
        self.assertTrue(self.service.active)
        self.assertEqual(self.store.load(), policy)
        self.assertEqual(result["mode"], "curve")

    def test_custom_configuration_combines_power_and_fan_policy(self) -> None:
        policy = FanPolicy(FanMode.CURVE, 2500, DEFAULT_CURVE)
        limits = CustomPowerLimits(70, 125)

        result = self.controller.set_custom_configuration(policy, limits)

        self.assertEqual(self.hardware.profile, "custom")
        self.assertEqual(self.hardware.power_limits, limits)
        self.assertEqual(self.store.load(), policy)
        self.assertTrue(self.service.active)
        self.assertEqual(result["power_limits"]["sustained_w"], 70)

    def test_failed_custom_power_restores_previous_profile(self) -> None:
        hardware = FakeHardware(fail_power=True)
        controller = PrivilegedController(hardware, self.store, self.service)

        with self.assertRaisesRegex(HelperError, "potencia"):
            controller.set_custom_configuration(
                FanPolicy(FanMode.CURVE, 2500, DEFAULT_CURVE),
                CustomPowerLimits(70, 125),
            )

        self.assertEqual(hardware.profile, "performance")
        self.assertEqual(self.store.load(), default_policy())
        self.assertGreater(hardware.restore_count, 0)

    def test_failed_custom_activation_restores_previous_power_limits(self) -> None:
        previous = self.hardware.power_limits
        controller = PrivilegedController(
            self.hardware,
            self.store,
            FakeService(fail_activation=True),
        )

        with self.assertRaises(HelperError):
            controller.set_custom_configuration(
                FanPolicy(FanMode.CURVE, 2500, DEFAULT_CURVE),
                CustomPowerLimits(70, 125),
            )

        self.assertEqual(self.hardware.power_limits, previous)
        self.assertEqual(self.hardware.profile, "performance")
        self.assertEqual(self.store.load(), default_policy())

    def test_rgb_is_persisted_only_after_hardware_accepts_reports(self) -> None:
        rgb_store = RgbConfigStore(Path(self.temporary.name) / "rgb-config.json")
        rgb = FakeRgbHardware()
        controller = PrivilegedController(
            self.hardware,
            self.store,
            self.service,
            rgb,
            rgb_store,
        )
        configuration = solid_rgb_configuration(RgbColor(229, 32, 47), 70)

        result = controller.set_rgb_configuration(configuration)

        self.assertEqual(rgb.applied, configuration)
        self.assertEqual(rgb_store.load(), configuration)
        self.assertTrue(result["enabled"])

    def test_failed_rgb_sequence_invalidates_stale_public_readback(self) -> None:
        rgb_store = RgbConfigStore(Path(self.temporary.name) / "rgb-config.json")
        previous = solid_rgb_configuration(RgbColor(0, 255, 0), 40)
        rgb_store.save(previous)
        controller = PrivilegedController(
            self.hardware,
            self.store,
            self.service,
            FakeRgbHardware(fail=True),
            rgb_store,
        )

        with self.assertRaisesRegex(RgbHardwareError, "RGB"):
            controller.set_rgb_configuration(solid_rgb_configuration(RgbColor(0, 0, 255), 70))

        self.assertIsNone(rgb_store.load())

    def test_failed_activation_restores_firmware_and_auto_config(self) -> None:
        controller = PrivilegedController(
            self.hardware,
            self.store,
            FakeService(fail_activation=True),
        )
        with self.assertRaises(HelperError):
            controller.set_fan_policy(FanPolicy(FanMode.CURVE, 2500, DEFAULT_CURVE))
        self.assertGreater(self.hardware.restore_count, 0)
        self.assertEqual(self.store.load(), default_policy())

    def test_standard_profile_disables_manual_control_first(self) -> None:
        self.controller.set_profile("balanced")
        self.assertEqual(self.hardware.restore_count, 1)
        self.assertEqual(self.hardware.profile, "balanced")
        self.assertGreater(self.service.deactivate_count, 0)

    def test_restore_attempts_firmware_even_if_systemd_fails(self) -> None:
        controller = PrivilegedController(
            self.hardware,
            self.store,
            FakeService(fail_deactivation=True),
        )
        with self.assertRaisesRegex(HelperError, "detener el servicio"):
            controller.restore_auto()
        self.assertEqual(self.store.load(), default_policy())
        self.assertEqual(self.hardware.restore_count, 1)

    def test_dispatch_rejects_path_or_shell_arguments(self) -> None:
        with self.assertRaisesRegex(HelperError, "Orden no admitida"):
            _dispatch(self.controller, ["set-feature", "../../etc/shadow", "1", "x"])
        with self.assertRaisesRegex(HelperError, "Orden no admitida"):
            _dispatch(self.controller, ["sh", "-c", "id"])

    def test_control_lock_rejects_a_second_overlapping_operation(self) -> None:
        lock_path = Path(self.temporary.name) / "control.lock"

        with _exclusive_control(lock_path, timeout_seconds=0.05):
            with self.assertRaisesRegex(HelperError, "operación anterior"):
                with _exclusive_control(lock_path, timeout_seconds=0.01):
                    self.fail("El segundo control nunca debe adquirir el lock.")

    @patch("legion_control.helper.subprocess.run")
    def test_systemd_status_probe_is_bounded_and_treats_timeout_as_inactive(
        self,
        run_mock,
    ) -> None:
        run_mock.side_effect = subprocess.TimeoutExpired("systemctl", 5)

        self.assertFalse(SystemdUnitService().is_active())
        self.assertEqual(run_mock.call_args.kwargs["timeout"], 5)


class RgbEffectControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.rgb = FakeRgbHardware()
        self.rgb_store = RgbConfigStore(root / "rgb-config.json")
        self.effect_store = EffectConfigStore(root / "rgb-effect.json")
        self.rgb_service = FakeService()
        self.controller = PrivilegedController(
            FakeHardware(),
            ConfigStore(root / "fan-config.json"),
            FakeService(),
            self.rgb,
            self.rgb_store,
            self.rgb_service,
            self.effect_store,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _effect(**overrides: object) -> EffectSettings:
        values: dict[str, object] = {
            "kind": EffectKind.AURORA,
            "speed_percent": 55,
            "brightness_percent": 70,
            "color": RgbColor(229, 32, 47),
            "enabled": True,
        }
        values.update(overrides)
        return EffectSettings(**values)  # type: ignore[arg-type]

    def test_an_effect_is_saved_before_the_service_starts(self) -> None:
        settings = self._effect()

        result = self.controller.set_rgb_effect(settings)

        self.assertEqual(self.effect_store.load(), settings)
        self.assertTrue(self.rgb_service.active)
        self.assertEqual(result["effect"], "aurora")

    def test_stopping_keeps_the_chosen_effect_for_next_time(self) -> None:
        self.controller.set_rgb_effect(self._effect())

        result = self.controller.set_rgb_effect(self._effect(enabled=False))

        saved = self.effect_store.load()
        assert saved is not None
        self.assertEqual(saved.kind, EffectKind.AURORA)
        self.assertFalse(saved.enabled)
        self.assertFalse(self.rgb_service.active)
        self.assertFalse(result["service_active"])

    def test_zero_brightness_stops_the_animation(self) -> None:
        self.controller.set_rgb_effect(self._effect())

        self.controller.set_rgb_effect(self._effect(brightness_percent=0))

        self.assertFalse(self.rgb_service.active)

    def test_a_static_write_stops_a_running_effect_first(self) -> None:
        """A running animation repaints the keyboard and would erase the frame."""

        self.controller.set_rgb_effect(self._effect())

        self.controller.set_rgb_configuration(solid_rgb_configuration(RgbColor(1, 2, 3), 50))

        self.assertFalse(self.rgb_service.active)
        saved = self.effect_store.load()
        assert saved is not None
        self.assertFalse(saved.enabled)
        self.assertEqual(self.rgb_store.load(), solid_rgb_configuration(RgbColor(1, 2, 3), 50))

    def test_a_static_write_does_not_call_systemd_when_nothing_is_animating(self) -> None:
        self.controller.set_rgb_configuration(solid_rgb_configuration(RgbColor(1, 2, 3), 50))

        self.assertEqual(self.rgb_service.deactivate_count, 0)

    def test_a_failed_activation_leaves_the_effect_disabled(self) -> None:
        self.controller.rgb_service = FakeService(fail_activation=True)

        with self.assertRaises(HelperError):
            self.controller.set_rgb_effect(self._effect())

        saved = self.effect_store.load()
        assert saved is not None
        self.assertFalse(saved.enabled)

    def test_a_missing_controller_refuses_the_effect(self) -> None:
        self.rgb.available = False

        with self.assertRaisesRegex(HelperError, "048d:c195"):
            self.controller.set_rgb_effect(self._effect())

    def test_status_reports_the_saved_effect_and_the_service_state(self) -> None:
        self.controller.set_rgb_effect(self._effect())

        report = self.controller.status()

        self.assertTrue(report["rgb_effect_active"])
        self.assertEqual(report["rgb_effect"]["kind"], "aurora")

    def test_status_reports_no_effect_when_none_was_ever_chosen(self) -> None:
        report = self.controller.status()

        self.assertIsNone(report["rgb_effect"])
        self.assertFalse(report["rgb_effect_active"])

    def test_dispatch_accepts_the_effect_command_and_refuses_bad_grammar(self) -> None:
        payload = effect_settings_to_json(self._effect())

        result = _dispatch(self.controller, ["set-rgb-effect", payload])
        self.assertEqual(result["effect"], "aurora")

        with self.assertRaises(HelperError):
            _dispatch(self.controller, ["set-rgb-effect"])
        with self.assertRaises(HelperError):
            _dispatch(self.controller, ["set-rgb-effect", payload, "extra"])


if __name__ == "__main__":
    unittest.main()
