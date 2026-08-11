from __future__ import annotations

from pathlib import Path


def build_fake_sysfs(root: Path, product: str = "83LU") -> None:
    _write(root / "sys/devices/virtual/dmi/id/product_name", product)
    _write(
        root / "sys/devices/virtual/dmi/id/product_version",
        "Legion Pro 5 16IAX10H",
    )

    fan = root / "sys/class/hwmon/hwmon0"
    _write(fan / "name", "lenovo_wmi_other")
    for index in (1, 2):
        _write(fan / f"fan{index}_input", "2100")
        _write(fan / f"fan{index}_target", "0")
        _write(fan / f"fan{index}_min", "1700")
        _write(fan / f"fan{index}_max", "5300")
        _write(fan / f"fan{index}_div", "100")

    coretemp = root / "sys/class/hwmon/hwmon1"
    _write(coretemp / "name", "coretemp")
    _write(coretemp / "temp1_label", "Package id 0")
    _write(coretemp / "temp1_input", "61000")

    profile = root / "sys/class/platform-profile/platform-profile-0"
    _write(profile / "name", "lenovo-wmi-gamezone")
    _write(profile / "choices", "low-power balanced performance max-power custom")
    _write(profile / "profile", "performance")

    power = root / "sys/class/firmware-attributes/lenovo-wmi-other-0/attributes"
    _build_power_attribute(power / "ppt_pl1_spl", 50, 135, 1, 70, 60)
    _build_power_attribute(power / "ppt_pl2_sppt", 60, 210, 1, 125, 119)

    features = root / "sys/bus/platform/devices/VPC2004:00"
    _write(features / "conservation_mode", "0")
    _write(features / "fn_lock", "0")
    _write(features / "camera_power", "1")

    battery = root / "sys/class/power_supply/BAT0"
    _write(battery / "capacity", "78")
    _write(battery / "status", "Charging")


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _build_power_attribute(
    path: Path,
    minimum: int,
    maximum: int,
    step: int,
    default: int,
    current: int,
) -> None:
    _write(path / "min_value", str(minimum))
    _write(path / "max_value", str(maximum))
    _write(path / "scalar_increment", str(step))
    _write(path / "default_value", str(default))
    _write(path / "current_value", str(current))
