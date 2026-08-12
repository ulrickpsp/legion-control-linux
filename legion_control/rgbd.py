"""Root service that paints animated RGB frames on the verified transport.

An animation is a sequence of ordinary static frames. Sending each one through
`pkexec` would spawn a privileged process per frame, so this daemon holds the
controller open instead and writes frames directly, the same way the fan daemon
holds the hwmon targets. It sends no firmware animation command: every frame is
the physically validated colour report and nothing else.

The daemon exits when the effect is switched off, and always tries to leave the
keyboard on the last static configuration the user applied.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
from time import monotonic
from typing import Final, Protocol

from legion_control.effects import EffectConfigStore, EffectSettings, effect_zones
from legion_control.rgb import (
    LegionRgbHardware,
    RgbColor,
    RgbConfiguration,
    RgbConfigStore,
    RgbHardwareError,
    RgbSessionPort,
    default_rgb_configuration,
    reports_for,
    zone_reports_for,
)
from legion_control.system_contract import RGB_CONFIG_PATH, RGB_EFFECT_CONFIG_PATH


# Measured on the 83LU: a 24-group colour report takes about 56 ms, 67 ms at the
# 95th percentile, so the controller tops out near 17 frames per second. Asking
# for more only makes the loop run flat out and miss every deadline. 80 ms keeps
# headroom above the slowest measured frame and still reads as motion, since one
# cycle of these effects lasts seconds. See docs/RGB-PROTOCOL.md.
FRAME_INTERVAL_SECONDS: Final = 0.08
# How often the daemon notices that the UI rewrote the effect file.
RELOAD_INTERVAL_SECONDS: Final = 1.0
# One reopen covers a USB re-enumeration after resume. Beyond that the daemon
# fails instead of looping, and systemd's start limit stops the restarts.
MAX_SESSION_REOPENS: Final = 1

LOGGER = logging.getLogger("legion-control-rgbd")


class RgbAnimationPort(Protocol):
    def is_available(self) -> bool: ...
    def open_session(self) -> RgbSessionPort: ...
    def apply(self, configuration: RgbConfiguration) -> None: ...


class RgbAnimationDaemon:
    def __init__(
        self,
        hardware: RgbAnimationPort,
        effect_store: EffectConfigStore,
        static_store: RgbConfigStore,
    ) -> None:
        self._hardware = hardware
        self._effect_store = effect_store
        self._static_store = static_store
        self._stop = threading.Event()

    def request_stop(self, _signal_number: int, _frame: object) -> None:
        self._stop.set()

    def run(self) -> int:
        settings = self._active_settings()
        if settings is None:
            LOGGER.info("No hay ningún efecto activo; finaliza el daemon.")
            return 0
        if not self._hardware.is_available():
            LOGGER.error("No aparece el teclado RGB 048d:c195 en la interfaz esperada.")
            return 2
        try:
            self._animate(settings)
        except RgbHardwareError as error:
            LOGGER.error("%s", error)
            return 2
        finally:
            self.restore_static()
        return 0

    def _animate(self, settings: EffectSettings) -> None:
        session = self._hardware.open_session()
        reopens = 0
        try:
            last_zones: tuple[RgbColor, ...] | None = self._prime(session, settings)
            started = monotonic()
            next_reload = started + RELOAD_INTERVAL_SECONDS
            frame_index = 0
            while not self._stop.is_set():
                now = monotonic()
                if now >= next_reload:
                    next_reload = now + RELOAD_INTERVAL_SECONDS
                    replacement = self._active_settings()
                    if replacement is None:
                        LOGGER.info("El efecto se ha desactivado; finaliza el daemon.")
                        return
                    if replacement != settings:
                        settings = replacement
                        last_zones = self._prime(session, settings)
                        started = monotonic()
                        frame_index = 0
                        LOGGER.info("Efecto %s cargado.", settings.kind.value)

                zones = effect_zones(settings, monotonic() - started)
                if zones != last_zones:
                    try:
                        session.send(zone_reports_for(zones))
                    except OSError as error:
                        if reopens >= MAX_SESSION_REOPENS:
                            raise RgbHardwareError(
                                f"El teclado RGB dejó de aceptar frames: {error}."
                            ) from error
                        reopens += 1
                        LOGGER.warning("Reabriendo el teclado RGB tras un fallo: %s", error)
                        session.close()
                        session = self._hardware.open_session()
                        self._prime(session, settings)
                        last_zones = None
                        continue
                    last_zones = zones

                frame_index += 1
                self._stop.wait(
                    max(0.0, started + frame_index * FRAME_INTERVAL_SECONDS - monotonic())
                )
        finally:
            session.close()

    def _prime(self, session: RgbSessionPort, settings: EffectSettings) -> tuple[RgbColor, ...]:
        """Select the profile and set brightness once, so frames carry colour only."""

        zones = effect_zones(settings, 0.0)
        session.send(
            reports_for(
                RgbConfiguration(
                    enabled=settings.enabled,
                    brightness_percent=settings.brightness_percent,
                    zones=zones,
                )
            )
        )
        return zones

    def _active_settings(self) -> EffectSettings | None:
        try:
            settings = self._effect_store.load()
        except (OSError, ValueError) as error:
            LOGGER.error("Configuración de efectos ilegible: %s", error)
            return None
        if settings is None or not settings.enabled or settings.brightness_percent == 0:
            return None
        return settings

    def restore_static(self) -> None:
        try:
            self._hardware.apply(self._static_configuration())
            LOGGER.info("Iluminación estática restaurada.")
        except (RgbHardwareError, OSError, ValueError) as error:
            LOGGER.critical("Fallo restaurando la iluminación estática: %s", error)

    def _static_configuration(self) -> RgbConfiguration:
        try:
            saved = self._static_store.load()
        except (OSError, ValueError):
            saved = None
        return saved if saved is not None else default_rgb_configuration()


def main(arguments: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if os.geteuid() != 0:
        LOGGER.error("El daemon debe ejecutarse como root.")
        return 2
    daemon = RgbAnimationDaemon(
        LegionRgbHardware(),
        EffectConfigStore(RGB_EFFECT_CONFIG_PATH),
        RgbConfigStore(RGB_CONFIG_PATH),
    )
    if arguments == ["--restore-static"]:
        daemon.restore_static()
        return 0
    if arguments:
        LOGGER.error("Argumentos no admitidos.")
        return 2
    signal.signal(signal.SIGTERM, daemon.request_stop)
    signal.signal(signal.SIGINT, daemon.request_stop)
    try:
        return daemon.run()
    except (RgbHardwareError, OSError, ValueError) as error:
        LOGGER.error("%s", error)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
