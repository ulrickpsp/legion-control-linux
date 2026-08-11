"""Root service that continuously applies a validated fan policy."""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
from time import monotonic
from typing import Final

from legion_control.config import ConfigStore
from legion_control.domain import (
    CriticalTemperatureError,
    FanController,
    FanMode,
    TemperatureUnavailableError,
)
from legion_control.linux import HardwareError, SysfsHardware
from legion_control.system_contract import FAN_CONFIG_PATH


CONTROL_INTERVAL_SECONDS: Final = 2.0
LOGGER = logging.getLogger("legion-control-fand")


class FanDaemon:
    def __init__(self, hardware: SysfsHardware, store: ConfigStore) -> None:
        self._hardware = hardware
        self._store = store
        self._stop = threading.Event()

    def request_stop(self, _signal_number: int, _frame: object) -> None:
        self._stop.set()

    def run(self) -> int:
        self._hardware.require_supported()
        active_signature: tuple[object, ...] | None = None
        controller: FanController | None = None
        try:
            while not self._stop.is_set():
                started = monotonic()
                policy = self._store.load()
                if policy.mode is FanMode.AUTO:
                    LOGGER.info("La configuración pide control automático; finaliza el daemon.")
                    return 0
                signature = (
                    policy.mode,
                    policy.fixed_rpm,
                    tuple(policy.curve.points),
                )
                if signature != active_signature:
                    controller = FanController(policy, self._hardware.fan_bounds())
                    self._ensure_custom_profile()
                    active_signature = signature
                    LOGGER.info("Política de ventilación %s cargada.", policy.mode.value)
                assert controller is not None
                snapshot = self._hardware.thermal_snapshot()
                targets = controller.next_targets(snapshot)
                if targets is None:
                    return 0
                self._hardware.set_fan_targets(targets)
                hottest = snapshot.hottest_temperature()
                LOGGER.info(
                    "temperatura=%s control=%s fan1=%s fan2=%s objetivo=%s",
                    hottest,
                    controller.control_temperature_c,
                    snapshot.fan1_rpm,
                    snapshot.fan2_rpm,
                    targets.fan1_rpm,
                )
                remaining = max(0.0, CONTROL_INTERVAL_SECONDS - (monotonic() - started))
                self._stop.wait(remaining)
        except (CriticalTemperatureError, TemperatureUnavailableError) as error:
            LOGGER.critical("%s", error)
            return 3
        finally:
            self._restore_safely()
        return 0

    def _ensure_custom_profile(self) -> None:
        if self._hardware.current_profile() != "custom":
            self._hardware.set_profile("custom")

    def _restore_safely(self) -> None:
        try:
            self._hardware.restore_firmware_control()
            LOGGER.info("Control automático del firmware restaurado.")
        except HardwareError as error:
            LOGGER.critical("Fallo restaurando control del firmware: %s", error)


def main(arguments: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if os.geteuid() != 0:
        LOGGER.error("El daemon debe ejecutarse como root.")
        return 2
    hardware = SysfsHardware()
    if arguments == ["--restore-auto"]:
        try:
            hardware.restore_firmware_control()
        except HardwareError as error:
            LOGGER.error("%s", error)
            return 2
        return 0
    if arguments:
        LOGGER.error("Argumentos no admitidos.")
        return 2
    daemon = FanDaemon(hardware, ConfigStore(FAN_CONFIG_PATH))
    signal.signal(signal.SIGTERM, daemon.request_stop)
    signal.signal(signal.SIGINT, daemon.request_stop)
    try:
        return daemon.run()
    except (HardwareError, OSError, ValueError) as error:
        LOGGER.error("%s", error)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
