"""Stable filesystem and process contract shared by Linux-facing adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Final


FAN_CONFIG_PATH: Final = Path("/var/lib/legion-control/fan-config.json")
RGB_CONFIG_PATH: Final = Path("/var/lib/legion-control/rgb-config.json")
RGB_EFFECT_CONFIG_PATH: Final = Path("/var/lib/legion-control/rgb-effect.json")
SYSTEMCTL_PATH: Final = Path("/usr/bin/systemctl")
PKEXEC_PATH: Final = Path("/usr/bin/pkexec")
PRIVILEGED_HELPER_PATH: Final = Path("/usr/libexec/legion-control-helper")
FAN_SERVICE_NAME: Final = "legion-control-fand.service"
RGB_SERVICE_NAME: Final = "legion-control-rgbd.service"
CONTROL_LOCK_PATH: Final = Path("/run/lock/legion-control.lock")
