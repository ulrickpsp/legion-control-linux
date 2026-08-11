from __future__ import annotations

import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

from legion_control.effects import EffectConfigStore, EffectKind, EffectSettings
from legion_control.rgb import (
    RGB_FEATURE_REPORT_SIZE,
    RgbColor,
    RgbConfigStore,
    RgbConfiguration,
    RgbHardwareError,
    solid_rgb_configuration,
)
from legion_control.rgbd import RgbAnimationDaemon


def _effect(**overrides: object) -> EffectSettings:
    values: dict[str, object] = {
        "kind": EffectKind.RAINBOW,
        "speed_percent": 50,
        "brightness_percent": 70,
        "color": RgbColor(229, 32, 47),
        "enabled": True,
    }
    values.update(overrides)
    return EffectSettings(**values)  # type: ignore[arg-type]


class FakeSession:
    """Records report sequences and can stop the daemon after N of them."""

    def __init__(
        self,
        *,
        stop_after: int | None = None,
        fail_from: int | None = None,
        on_send: Callable[[int], None] | None = None,
    ) -> None:
        self.sequences: list[tuple[bytes, ...]] = []
        self.closed = 0
        self._stop_after = stop_after
        self._fail_from = fail_from
        self._on_send = on_send
        self.daemon: RgbAnimationDaemon | None = None

    def send(self, reports: tuple[bytes, ...]) -> None:
        self.sequences.append(reports)
        if self._on_send is not None:
            self._on_send(len(self.sequences))
        if self._fail_from is not None and len(self.sequences) >= self._fail_from:
            raise OSError("el controlador rechazó el frame")
        if self._stop_after is not None and len(self.sequences) >= self._stop_after:
            assert self.daemon is not None
            self.daemon.request_stop(0, None)

    def close(self) -> None:
        self.closed += 1


class FakeRgbHardware:
    def __init__(self, *sessions: FakeSession, available: bool = True) -> None:
        self._sessions = list(sessions) or [FakeSession()]
        self._available = available
        self.opened: list[FakeSession] = []
        self.applied: list[RgbConfiguration] = []

    def is_available(self) -> bool:
        return self._available

    def open_session(self) -> FakeSession:
        session = self._sessions.pop(0)
        self.opened.append(session)
        return session

    def apply(self, configuration: RgbConfiguration) -> None:
        self.applied.append(configuration)


class RgbAnimationDaemonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.effect_store = EffectConfigStore(root / "rgb-effect.json")
        self.static_store = RgbConfigStore(root / "rgb-config.json")
        self.static = solid_rgb_configuration(RgbColor(0, 255, 0), 40)
        self.static_store.save(self.static)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _run_with(self, hardware: FakeRgbHardware, sessions: list[FakeSession]) -> int:
        daemon = RgbAnimationDaemon(hardware, self.effect_store, self.static_store)
        for session in sessions:
            session.daemon = daemon
        return daemon.run()

    def test_without_a_saved_effect_the_daemon_exits_without_touching_hardware(self) -> None:
        hardware = FakeRgbHardware()

        self.assertEqual(self._run_with(hardware, []), 0)
        self.assertEqual(hardware.opened, [])
        self.assertEqual(hardware.applied, [])

    def test_a_disabled_effect_does_not_start_an_animation(self) -> None:
        self.effect_store.save(_effect(enabled=False))
        hardware = FakeRgbHardware()

        self.assertEqual(self._run_with(hardware, []), 0)
        self.assertEqual(hardware.opened, [])

    def test_zero_brightness_does_not_start_an_animation(self) -> None:
        self.effect_store.save(_effect(brightness_percent=0))
        hardware = FakeRgbHardware()

        self.assertEqual(self._run_with(hardware, []), 0)
        self.assertEqual(hardware.opened, [])

    def test_a_missing_controller_fails_instead_of_animating(self) -> None:
        self.effect_store.save(_effect())
        hardware = FakeRgbHardware(available=False)

        self.assertEqual(self._run_with(hardware, []), 2)
        self.assertEqual(hardware.opened, [])

    def test_the_first_sequence_primes_profile_and_brightness_then_frames_carry_colour(
        self,
    ) -> None:
        """Repeating profile and brightness on every frame would cost two extra
        ioctls per frame without changing anything the controller shows."""

        self.effect_store.save(_effect())
        session = FakeSession(stop_after=4)
        hardware = FakeRgbHardware(session)

        self.assertEqual(self._run_with(hardware, [session]), 0)

        self.assertEqual(len(session.sequences[0]), 3)
        for frame in session.sequences[1:]:
            self.assertEqual(len(frame), 1)
        for sequence in session.sequences:
            for report in sequence:
                self.assertEqual(len(report), RGB_FEATURE_REPORT_SIZE)

    def test_stopping_closes_the_session_and_restores_the_saved_static_frame(self) -> None:
        self.effect_store.save(_effect())
        session = FakeSession(stop_after=2)
        hardware = FakeRgbHardware(session)

        self.assertEqual(self._run_with(hardware, [session]), 0)

        self.assertEqual(session.closed, 1)
        self.assertEqual(hardware.applied, [self.static])

    def test_without_a_saved_static_frame_the_default_is_restored(self) -> None:
        self.static_store.clear()
        self.effect_store.save(_effect())
        session = FakeSession(stop_after=2)
        hardware = FakeRgbHardware(session)

        self._run_with(hardware, [session])

        self.assertEqual(len(hardware.applied), 1)
        self.assertFalse(hardware.applied[0].enabled)

    def test_switching_the_effect_off_while_running_ends_the_daemon(self) -> None:
        self.effect_store.save(_effect())
        session = FakeSession(
            stop_after=20,
            on_send=lambda count: self._rewrite(count, _effect(enabled=False)),
        )
        hardware = FakeRgbHardware(session)

        with patch("legion_control.rgbd.RELOAD_INTERVAL_SECONDS", 0.0):
            self.assertEqual(self._run_with(hardware, [session]), 0)

        self.assertEqual(session.closed, 1)
        self.assertEqual(hardware.applied, [self.static])

    def test_a_new_effect_is_picked_up_without_reopening_the_controller(self) -> None:
        self.effect_store.save(_effect())
        session = FakeSession(
            stop_after=4,
            on_send=lambda count: self._rewrite(count, _effect(kind=EffectKind.FIRE)),
        )
        hardware = FakeRgbHardware(session)

        with patch("legion_control.rgbd.RELOAD_INTERVAL_SECONDS", 0.0):
            self.assertEqual(self._run_with(hardware, [session]), 0)

        self.assertEqual(len(hardware.opened), 1)
        # The reload re-primes, so a second three-report sequence appears.
        self.assertEqual([len(sequence) for sequence in session.sequences][:2], [3, 3])

    def _rewrite(self, send_count: int, settings: EffectSettings) -> None:
        """Change the saved effect once the animation is already running."""

        if send_count == 1:
            self.effect_store.save(settings)

    def test_a_rejected_frame_reopens_the_controller_once(self) -> None:
        self.effect_store.save(_effect())
        failing = FakeSession(fail_from=2)
        recovered = FakeSession(stop_after=3)
        hardware = FakeRgbHardware(failing, recovered)

        self.assertEqual(self._run_with(hardware, [failing, recovered]), 0)

        self.assertEqual(len(hardware.opened), 2)
        self.assertEqual(failing.closed, 1)
        self.assertEqual(recovered.closed, 1)

    def test_a_second_failure_stops_instead_of_retrying_forever(self) -> None:
        self.effect_store.save(_effect())
        first = FakeSession(fail_from=2)
        second = FakeSession(fail_from=2)
        hardware = FakeRgbHardware(first, second)

        self.assertEqual(self._run_with(hardware, [first, second]), 2)

        self.assertEqual(len(hardware.opened), 2)
        self.assertEqual(hardware.applied, [self.static])

    def test_an_unreadable_effect_file_is_treated_as_no_effect(self) -> None:
        self.effect_store.path.parent.mkdir(parents=True, exist_ok=True)
        self.effect_store.path.write_text("{ not json", encoding="utf-8")
        hardware = FakeRgbHardware()

        self.assertEqual(self._run_with(hardware, []), 0)
        self.assertEqual(hardware.opened, [])

    def test_restore_static_survives_a_failing_controller(self) -> None:
        class FailingHardware(FakeRgbHardware):
            def apply(self, configuration: RgbConfiguration) -> None:
                raise RgbHardwareError("no responde")

        daemon = RgbAnimationDaemon(FailingHardware(), self.effect_store, self.static_store)

        daemon.restore_static()


if __name__ == "__main__":
    unittest.main()
