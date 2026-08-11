from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from legion_control.client import (
    HELPER,
    PKEXEC,
    ControlError,
    LocalControlClient,
    _service_is_active,
)
from legion_control.effects import EffectKind, EffectSettings, effect_settings_to_json
from legion_control.rgb import RgbColor
from legion_control.system_contract import FAN_SERVICE_NAME, RGB_SERVICE_NAME


class LocalControlClientTests(unittest.TestCase):
    @patch("legion_control.client.subprocess.run")
    def test_mutation_uses_exact_privileged_argv_and_bounded_process(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            [],
            0,
            stdout='{"ok":true,"result":{"profile":"balanced"}}',
            stderr="",
        )

        result = LocalControlClient._mutate("set-profile", "balanced")

        self.assertEqual(result, {"profile": "balanced"})
        arguments, keywords = run_mock.call_args
        self.assertEqual(
            arguments[0],
            [str(PKEXEC), str(HELPER), "set-profile", "balanced"],
        )
        self.assertFalse(keywords["check"])
        self.assertEqual(keywords["timeout"], 120)
        self.assertEqual(
            keywords["env"]["PATH"],
            "/usr/sbin:/usr/bin:/sbin:/bin",
        )

    @patch("legion_control.client.subprocess.run")
    def test_policykit_cancel_has_clear_error_even_without_json(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            [],
            126,
            stdout="",
            stderr="pkexec cancelled",
        )

        with self.assertRaisesRegex(ControlError, "Autorización cancelada"):
            LocalControlClient._mutate("restore-auto")

    @patch("legion_control.client.subprocess.run")
    def test_mutation_timeout_has_clear_error(self, run_mock) -> None:
        run_mock.side_effect = subprocess.TimeoutExpired("pkexec", 120)

        with self.assertRaisesRegex(ControlError, "agotó el tiempo"):
            LocalControlClient._mutate("restore-auto")

    @patch("legion_control.client.subprocess.run")
    def test_success_without_result_object_is_rejected(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            [],
            0,
            stdout='{"ok":true,"result":[]}',
            stderr="",
        )

        with self.assertRaisesRegex(ControlError, "respuesta incorrecta"):
            LocalControlClient._mutate("restore-auto")

    @patch("legion_control.client.subprocess.run")
    def test_non_boolean_success_marker_is_rejected(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            [],
            0,
            stdout='{"ok":"yes","result":{}}',
            stderr="",
        )

        with self.assertRaisesRegex(ControlError, "respuesta incorrecta"):
            LocalControlClient._mutate("restore-auto")

    @patch("legion_control.client.subprocess.run")
    def test_service_probe_is_bounded_and_treats_timeout_as_inactive(self, run_mock) -> None:
        run_mock.side_effect = subprocess.TimeoutExpired("systemctl", 5)

        self.assertFalse(_service_is_active(FAN_SERVICE_NAME))
        self.assertEqual(run_mock.call_args.kwargs["timeout"], 5)

    @patch("legion_control.client.subprocess.run")
    def test_effect_probe_asks_about_the_effect_unit(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess([], 0)

        self.assertTrue(_service_is_active(RGB_SERVICE_NAME))
        self.assertIn(RGB_SERVICE_NAME, run_mock.call_args.args[0])

    @patch("legion_control.client.subprocess.run")
    def test_set_rgb_effect_sends_the_serialized_settings(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            [],
            0,
            stdout='{"ok":true,"result":{"effect":"comet","service_active":true}}',
            stderr="",
        )
        settings = EffectSettings(
            kind=EffectKind.COMET,
            speed_percent=64,
            brightness_percent=80,
            color=RgbColor(12, 240, 90),
        )

        result = LocalControlClient(hardware=None).set_rgb_effect(settings)  # type: ignore[arg-type]

        self.assertEqual(result["effect"], "comet")
        self.assertEqual(
            run_mock.call_args.args[0],
            [str(PKEXEC), str(HELPER), "set-rgb-effect", effect_settings_to_json(settings)],
        )


if __name__ == "__main__":
    unittest.main()
