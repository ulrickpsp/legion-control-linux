"""Strict RGB configuration and exact HID transport for the 83LU keyboard."""

from __future__ import annotations

import colorsys
import errno
import fcntl
import json
import os
import struct
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Callable, Final, Protocol


RGB_CONFIG_VERSION: Final = 1
RGB_ZONE_COUNT: Final = 24
RGB_FEATURE_REPORT_SIZE: Final = 960
RGB_REPORT_ID: Final = 0x07
RGB_PROFILE_ID: Final = 0x01
RGB_RAW_BRIGHTNESS_MAX: Final = 9
RGB_REPORT_DELAY_SECONDS: Final = 0.01
HID_MAX_DESCRIPTOR_SIZE: Final = 4096
HID_BUS_USB: Final = 0x03
HID_VENDOR_ID: Final = 0x048D
HID_PRODUCT_ID: Final = 0xC195
MAX_RGB_CONFIG_BYTES: Final = 8192
SUPPORTED_PRODUCT: Final = "83LU"
SUPPORTED_HID_ID: Final = "HID_ID=0003:0000048D:0000C195"
SUPPORTED_INTERFACE: Final = "00"
SUPPORTED_DESCRIPTOR_SIGNATURE: Final = bytes(
    (0x06, 0x89, 0xFF, 0x09, 0x07, 0xA1, 0x01, 0x85, RGB_REPORT_ID)
)
EXPECTED_RGB_KEYS: Final = frozenset({"version", "enabled", "brightness_percent", "zones"})
EXPECTED_COLOR_KEYS: Final = frozenset({"red", "green", "blue"})


class RgbSessionPort(Protocol):
    """A held-open controller that accepts successive report sequences."""

    def send(self, reports: tuple[bytes, ...]) -> None: ...
    def close(self) -> None: ...


FeatureReportWriter = Callable[[Path, tuple[bytes, ...]], None]
SessionFactory = Callable[[Path], RgbSessionPort]
_RGB_REPORT_LOCK = threading.Lock()


class RgbHardwareError(RuntimeError):
    """The exact supported RGB controller is missing or rejected a report."""


@dataclass(frozen=True, slots=True)
class RgbColor:
    red: int
    green: int
    blue: int

    def __post_init__(self) -> None:
        channels = (self.red, self.green, self.blue)
        if any(type(channel) is not int for channel in channels):
            raise ValueError("Cada canal RGB debe ser un entero.")
        if any(not 0 <= channel <= 255 for channel in channels):
            raise ValueError("Cada canal RGB debe estar entre 0 y 255.")

    def to_dict(self) -> dict[str, int]:
        return {
            "red": self.red,
            "green": self.green,
            "blue": self.blue,
        }


@dataclass(frozen=True, slots=True)
class RgbConfiguration:
    enabled: bool
    brightness_percent: int
    zones: tuple[RgbColor, ...]

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ValueError("El estado RGB debe ser booleano.")
        if type(self.brightness_percent) is not int:
            raise ValueError("El brillo RGB debe ser un entero.")
        if not 0 <= self.brightness_percent <= 100:
            raise ValueError("El brillo RGB debe estar entre 0 y 100.")
        if len(self.zones) != RGB_ZONE_COUNT:
            raise ValueError("La configuración RGB necesita exactamente 24 zonas.")
        if any(not isinstance(color, RgbColor) for color in self.zones):
            raise ValueError("Cada zona RGB necesita un color válido.")

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "brightness_percent": self.brightness_percent,
            "zones": [color.to_dict() for color in self.zones],
        }


@dataclass(slots=True)
class RgbConfigStore:
    path: Path
    mode: int = 0o644

    def load(self) -> RgbConfiguration | None:
        if not self.path.exists():
            return None
        if self.path.stat().st_size > MAX_RGB_CONFIG_BYTES:
            raise ValueError("La configuración RGB es demasiado grande.")
        return rgb_configuration_from_json(self.path.read_text(encoding="utf-8"))

    def save(self, configuration: RgbConfiguration) -> None:
        write_text_atomically(
            self.path,
            rgb_configuration_to_json(configuration) + "\n",
            mode=self.mode,
            prefix=".rgb-config-",
        )

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            return
        _sync_directory(self.path.parent)


def write_text_atomically(path: Path, payload: str, *, mode: int, prefix: str) -> None:
    """Replace a state file in one step so a reader never sees a partial write."""

    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=prefix,
        delete=False,
    ) as temporary:
        temporary.write(payload)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    try:
        temporary_path.chmod(mode)
        os.replace(temporary_path, path)
        _sync_directory(path.parent)
    finally:
        temporary_path.unlink(missing_ok=True)


class RgbSession:
    """One validated descriptor reused for successive frames.

    Reopening and revalidating the controller for every frame of an animation
    would spend more time proving identity than painting. The identity checks
    still run, once, on the descriptor the frames are actually written to.
    """

    __slots__ = ("_descriptor",)

    def __init__(self, device: Path) -> None:
        self._descriptor: int | None = os.open(device, os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            _validate_open_device(self._descriptor)
        except BaseException:
            self.close()
            raise

    def send(self, reports: tuple[bytes, ...]) -> None:
        descriptor = self._descriptor
        if descriptor is None:
            raise OSError(errno.EBADF, "La sesión RGB ya está cerrada")
        _require_valid_reports(reports)
        with _RGB_REPORT_LOCK:
            _write_reports(descriptor, reports)

    def close(self) -> None:
        descriptor, self._descriptor = self._descriptor, None
        if descriptor is not None:
            os.close(descriptor)

    def __enter__(self) -> RgbSession:
        return self

    def __exit__(self, *_exception: object) -> None:
        self.close()


class LegionRgbHardware:
    """Writes only the exact 24-zone ITE controller on supported product 83LU."""

    def __init__(
        self,
        root: Path = Path("/"),
        feature_report_writer: FeatureReportWriter | None = None,
        session_factory: SessionFactory | None = None,
    ) -> None:
        self._root = root.resolve()
        self._sys_root = (self._root / "sys").resolve()
        self._feature_report_writer = feature_report_writer or _send_feature_reports
        self._session_factory = session_factory or RgbSession

    def is_available(self) -> bool:
        return self._is_supported_product() and self._device_path() is not None

    def apply(self, configuration: RgbConfiguration) -> None:
        device = self._require_device()
        try:
            self._feature_report_writer(device, reports_for(configuration))
        except OSError as error:
            raise RgbHardwareError(
                f"El teclado RGB rechazó el cambio: {error.strerror or error}."
            ) from error

    def open_session(self) -> RgbSessionPort:
        """Hold the controller open so an animation can paint frame after frame."""

        device = self._require_device()
        try:
            return self._session_factory(device)
        except OSError as error:
            raise RgbHardwareError(
                f"No se pudo abrir el teclado RGB: {error.strerror or error}."
            ) from error

    def _require_device(self) -> Path:
        if not self._is_supported_product():
            raise RgbHardwareError("El RGB solo está habilitado para el modelo 83LU.")
        device = self._device_path()
        if device is None:
            raise RgbHardwareError("No aparece el controlador RGB Lenovo/ITE 048d:c195.")
        return device

    def _is_supported_product(self) -> bool:
        product_path = self._root / "sys/devices/virtual/dmi/id/product_name"
        try:
            return product_path.read_text(encoding="utf-8").strip() == SUPPORTED_PRODUCT
        except OSError:
            return False

    def _device_path(self) -> Path | None:
        parent = self._root / "sys/class/hidraw"
        if not parent.exists():
            return None
        for entry in sorted(parent.iterdir()):
            resolved = _resolve_inside(entry / "device", self._sys_root)
            if resolved is None:
                continue
            if SUPPORTED_HID_ID not in _read_text(resolved / "uevent"):
                continue
            if _interface_number(resolved, self._sys_root) != SUPPORTED_INTERFACE:
                continue
            if SUPPORTED_DESCRIPTOR_SIGNATURE not in _read_bytes(resolved / "report_descriptor"):
                continue
            device = self._root / "dev" / entry.name
            if device.exists():
                return device
        return None


def solid_rgb_configuration(
    color: RgbColor,
    brightness_percent: int,
    *,
    enabled: bool = True,
) -> RgbConfiguration:
    return RgbConfiguration(
        enabled=enabled,
        brightness_percent=brightness_percent,
        zones=(color,) * RGB_ZONE_COUNT,
    )


def gradient_rgb_configuration(
    start: RgbColor,
    end: RgbColor,
    brightness_percent: int,
    *,
    enabled: bool = True,
) -> RgbConfiguration:
    """Create a static 24-zone gradient using only the verified transport."""

    if RGB_ZONE_COUNT < 2:
        raise ValueError("El teclado RGB necesita al menos dos zonas.")
    zones = tuple(
        RgbColor(
            round(start.red + (end.red - start.red) * index / (RGB_ZONE_COUNT - 1)),
            round(start.green + (end.green - start.green) * index / (RGB_ZONE_COUNT - 1)),
            round(start.blue + (end.blue - start.blue) * index / (RGB_ZONE_COUNT - 1)),
        )
        for index in range(RGB_ZONE_COUNT)
    )
    return RgbConfiguration(enabled, brightness_percent, zones)


def wave_rgb_configuration(
    brightness_percent: int,
    *,
    enabled: bool = True,
) -> RgbConfiguration:
    """Create one static spectrum frame; it does not send unverified animation commands."""

    zones = tuple(
        RgbColor(
            round(red * 255),
            round(green * 255),
            round(blue * 255),
        )
        for index in range(RGB_ZONE_COUNT)
        for red, green, blue in (colorsys.hsv_to_rgb(index / RGB_ZONE_COUNT, 0.92, 1.0),)
    )
    return RgbConfiguration(enabled, brightness_percent, zones)


def alternating_rgb_configuration(
    first: RgbColor,
    second: RgbColor,
    brightness_percent: int,
    *,
    enabled: bool = True,
) -> RgbConfiguration:
    """Alternate two colours across the zones, as one static frame."""

    zones = tuple(first if index % 2 == 0 else second for index in range(RGB_ZONE_COUNT))
    return RgbConfiguration(enabled, brightness_percent, zones)


def default_rgb_configuration() -> RgbConfiguration:
    return solid_rgb_configuration(
        RgbColor(229, 72, 77),
        60,
        enabled=False,
    )


def rgb_configuration_to_json(configuration: RgbConfiguration) -> str:
    document = {
        "version": RGB_CONFIG_VERSION,
        **configuration.to_dict(),
    }
    payload = json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(payload.encode("utf-8")) > MAX_RGB_CONFIG_BYTES:
        raise ValueError("La configuración RGB es demasiado grande.")
    return payload


def rgb_configuration_from_json(payload: str) -> RgbConfiguration:
    if len(payload.encode("utf-8")) > MAX_RGB_CONFIG_BYTES:
        raise ValueError("La configuración RGB es demasiado grande.")
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ValueError(f"JSON RGB inválido: {error.msg}.") from error
    if not isinstance(document, dict):
        raise ValueError("La configuración RGB debe ser un objeto.")
    if frozenset(document) != EXPECTED_RGB_KEYS:
        raise ValueError("La configuración RGB contiene claves incorrectas.")
    if document["version"] != RGB_CONFIG_VERSION:
        raise ValueError(f"Solo se admite RGB versión {RGB_CONFIG_VERSION}.")
    if type(document["enabled"]) is not bool:
        raise ValueError("El estado RGB debe ser booleano.")
    brightness = _require_integer(document["brightness_percent"], "brillo RGB")
    zones_document = document["zones"]
    if not isinstance(zones_document, list):
        raise ValueError("Las zonas RGB deben ser una lista.")
    zones = tuple(_color_from_document(item) for item in zones_document)
    return RgbConfiguration(document["enabled"], brightness, zones)


def rgb_configuration_from_document(document: Any) -> RgbConfiguration:
    if not isinstance(document, dict):
        raise ValueError("La configuración RGB debe ser un objeto.")
    return rgb_configuration_from_json(
        json.dumps(
            {"version": RGB_CONFIG_VERSION, **document},
            ensure_ascii=False,
        )
    )


def _color_from_document(document: Any) -> RgbColor:
    if not isinstance(document, dict) or frozenset(document) != EXPECTED_COLOR_KEYS:
        raise ValueError("Cada zona RGB necesita red, green y blue.")
    return RgbColor(
        _require_integer(document["red"], "red"),
        _require_integer(document["green"], "green"),
        _require_integer(document["blue"], "blue"),
    )


def _require_integer(value: object, name: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{name} debe ser un entero.")
    return value


def reports_for(configuration: RgbConfiguration) -> tuple[bytes, ...]:
    """The exact validated report sequence for one configuration."""

    if configuration.enabled and configuration.brightness_percent > 0:
        return _static_reports(configuration.zones, configuration.brightness_percent)
    return _off_reports()


def zone_reports_for(zones: tuple[RgbColor, ...]) -> tuple[bytes, ...]:
    """Only the colour report, for a frame whose profile and brightness are set.

    An animation selects profile `1` and its brightness once when the session
    opens; repeating either on every frame would add two ioctls per frame
    without changing anything the controller shows.
    """

    return (_save_profile_report(zones),)


def _static_reports(colors: tuple[RgbColor, ...], brightness_percent: int) -> tuple[bytes, ...]:
    return (
        _switch_profile_report(),
        _save_profile_report(colors),
        _brightness_report(brightness_percent),
    )


def _off_reports() -> tuple[bytes, ...]:
    return (_switch_profile_report(), _turn_off_report())


def _packet(command: int, payload_length: int) -> bytearray:
    packet = bytearray(RGB_FEATURE_REPORT_SIZE)
    packet[0] = RGB_REPORT_ID
    packet[1] = command
    packet[2:4] = payload_length.to_bytes(2, "little")
    return packet


def _switch_profile_report() -> bytes:
    packet = _packet(0xC8, 1)
    packet[4] = RGB_PROFILE_ID
    return bytes(packet)


def _save_profile_report(colors: tuple[RgbColor, ...]) -> bytes:
    grouped: dict[RgbColor, list[int]] = {}
    for led_id, color in enumerate(colors, start=1):
        grouped.setdefault(color, []).append(led_id)

    packet = _packet(0xCB, 0)
    packet[4:7] = bytes((RGB_PROFILE_ID, 0x01, 0x01))
    offset = 7
    for group_index, (color, led_ids) in enumerate(grouped.items()):
        encoded = _encode_static_group(group_index, color, led_ids)
        if offset + len(encoded) > RGB_FEATURE_REPORT_SIZE:
            raise ValueError("La configuración RGB supera el informe ITE de 960 bytes.")
        packet[offset : offset + len(encoded)] = encoded
        offset += len(encoded)
    packet[2:4] = (offset - 4).to_bytes(2, "little")
    return bytes(packet)


def _encode_static_group(group_index: int, color: RgbColor, led_ids: list[int]) -> bytes:
    payload = bytearray(
        (
            group_index + 1,
            0x06,
            0x01,
            0x0B,
            0x02,
            0x02,
            0x03,
            0x00,
            0x04,
            0x00,
            0x05,
            0x02,
            0x06,
            0x00,
            0x01,
            color.red,
            color.green,
            color.blue,
            len(led_ids),
        )
    )
    for led_id in led_ids:
        payload.extend(led_id.to_bytes(2, "little"))
    return bytes(payload)


def _brightness_report(brightness_percent: int) -> bytes:
    packet = _packet(0xCE, 1)
    packet[4] = max(
        1,
        min(
            RGB_RAW_BRIGHTNESS_MAX,
            round((brightness_percent / 100) * RGB_RAW_BRIGHTNESS_MAX),
        ),
    )
    return bytes(packet)


def _turn_off_report() -> bytes:
    packet = _packet(0xCB, 3)
    packet[4:7] = bytes((RGB_PROFILE_ID, 0x01, 0x01))
    return bytes(packet)


def _send_feature_reports(device: Path, reports: tuple[bytes, ...]) -> None:
    _require_valid_reports(reports)
    with _RGB_REPORT_LOCK:
        descriptor = os.open(device, os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            _validate_open_device(descriptor)
            _write_reports(descriptor, reports)
        finally:
            os.close(descriptor)


def _require_valid_reports(reports: tuple[bytes, ...]) -> None:
    if not reports or any(
        len(report) != RGB_FEATURE_REPORT_SIZE or report[0] != RGB_REPORT_ID for report in reports
    ):
        raise ValueError("Informe RGB Lenovo/ITE inválido.")


def _write_reports(descriptor: int, reports: tuple[bytes, ...]) -> None:
    """Send a sequence, spacing consecutive reports by the validated delay."""

    for index, report in enumerate(reports):
        if index:
            time.sleep(RGB_REPORT_DELAY_SECONDS)
        written = fcntl.ioctl(
            descriptor,
            _hid_iocsfeature(len(report)),
            bytearray(report),
            True,
        )
        if written != len(report):
            raise OSError(f"Escritura HID incompleta: {written} de {len(report)} bytes.")


def _hid_iocsfeature(length: int) -> int:
    return _hid_ioctl(direction=3, number=0x06, size=length)


def _validate_open_device(descriptor: int) -> None:
    info = bytearray(struct.calcsize("@Ihh"))
    fcntl.ioctl(
        descriptor,
        _hid_ioctl(direction=2, number=0x03, size=len(info)),
        info,
        True,
    )
    bus, vendor, product = struct.unpack("@Ihh", info)
    identity = (bus, vendor & 0xFFFF, product & 0xFFFF)
    if identity != (HID_BUS_USB, HID_VENDOR_ID, HID_PRODUCT_ID):
        raise OSError(errno.ENODEV, "El nodo abierto no es el teclado ITE 048d:c195")

    descriptor_size_buffer = bytearray(struct.calcsize("@I"))
    fcntl.ioctl(
        descriptor,
        _hid_ioctl(
            direction=2,
            number=0x01,
            size=len(descriptor_size_buffer),
        ),
        descriptor_size_buffer,
        True,
    )
    descriptor_size = struct.unpack("@I", descriptor_size_buffer)[0]
    if not 0 < descriptor_size <= HID_MAX_DESCRIPTOR_SIZE:
        raise OSError(errno.EPROTO, "Tamaño de descriptor HID no válido")

    report_descriptor = bytearray(struct.calcsize("@I") + HID_MAX_DESCRIPTOR_SIZE)
    struct.pack_into("@I", report_descriptor, 0, descriptor_size)
    fcntl.ioctl(
        descriptor,
        _hid_ioctl(direction=2, number=0x02, size=len(report_descriptor)),
        report_descriptor,
        True,
    )
    payload = bytes(report_descriptor[4 : 4 + descriptor_size])
    if SUPPORTED_DESCRIPTOR_SIGNATURE not in payload:
        raise OSError(errno.ENODEV, "La interfaz HID abierta no usa el protocolo ITE Gen10")


def _hid_ioctl(*, direction: int, number: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (ord("H") << 8) | number


def _interface_number(device: Path, sys_root: Path) -> str | None:
    for candidate in (device, *device.parents):
        try:
            candidate.relative_to(sys_root)
        except ValueError:
            break
        value = _read_text(candidate / "bInterfaceNumber").strip()
        if value:
            return value
    return None


def _resolve_inside(path: Path, parent: Path) -> Path | None:
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(parent)
    except (OSError, ValueError):
        return None
    return resolved


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        return b""


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
