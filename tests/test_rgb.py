from __future__ import annotations

import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

from legion_control.rgb import (
    RGB_FEATURE_REPORT_SIZE,
    RGB_REPORT_DELAY_SECONDS,
    RGB_ZONE_COUNT,
    LegionRgbHardware,
    RgbColor,
    RgbConfiguration,
    _send_feature_reports,
    _validate_open_device,
    gradient_rgb_configuration,
    rgb_configuration_from_json,
    rgb_configuration_to_json,
    wave_rgb_configuration,
)


class FeatureReportCapture:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, tuple[bytes, ...]]] = []

    def __call__(self, device: Path, reports: tuple[bytes, ...]) -> None:
        self.calls.append((device, reports))


def build_rgb_device(root: Path, *, product_id: str = "C195", interface: str = "00") -> None:
    product = root / "sys/devices/virtual/dmi/id/product_name"
    product.parent.mkdir(parents=True, exist_ok=True)
    product.write_text("83LU", encoding="utf-8")

    interface_directory = root / "sys/devices/fake-usb/3-4:1.1"
    interface_directory.mkdir(parents=True)
    (interface_directory / "bInterfaceNumber").write_text(interface, encoding="utf-8")
    hid_device = interface_directory / f"0003:048D:{product_id}.0001"
    hid_device.mkdir()
    (hid_device / "uevent").write_text(
        f"HID_ID=0003:0000048D:0000{product_id}\n",
        encoding="utf-8",
    )
    (hid_device / "report_descriptor").write_bytes(
        bytes((0x06, 0x89, 0xFF, 0x09, 0x07, 0xA1, 0x01, 0x85, 0x07))
    )

    hidraw = root / "sys/class/hidraw/hidraw0"
    hidraw.mkdir(parents=True)
    (hidraw / "device").symlink_to(hid_device)
    device = root / "dev/hidraw0"
    device.parent.mkdir(parents=True)
    device.touch()


class RgbConfigurationTests(unittest.TestCase):
    def test_round_trip_preserves_all_24_zones(self) -> None:
        zones = tuple(
            RgbColor(red=index, green=255 - index, blue=index // 2)
            for index in range(RGB_ZONE_COUNT)
        )
        configuration = RgbConfiguration(True, 65, zones)
        self.assertEqual(
            rgb_configuration_from_json(rgb_configuration_to_json(configuration)),
            configuration,
        )

    def test_rejects_wrong_zone_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "24 zonas"):
            RgbConfiguration(True, 50, (RgbColor(255, 0, 0),))

    def test_static_effect_helpers_stay_within_24_verified_zones(self) -> None:
        gradient = gradient_rgb_configuration(RgbColor(0, 0, 0), RgbColor(255, 120, 0), 60)
        wave = wave_rgb_configuration(70)

        self.assertEqual(gradient.zones[0], RgbColor(0, 0, 0))
        self.assertEqual(gradient.zones[-1], RgbColor(255, 120, 0))
        self.assertEqual(len(wave.zones), RGB_ZONE_COUNT)


class LegionRgbHardwareTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.capture = FeatureReportCapture()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_detects_controller_and_writes_exact_vendor_profile(self) -> None:
        build_rgb_device(self.root)
        hardware = LegionRgbHardware(self.root, self.capture)
        configuration = RgbConfiguration(
            True,
            100,
            tuple(RgbColor(index * 5, 20, 30) for index in range(RGB_ZONE_COUNT)),
        )

        self.assertTrue(hardware.is_available())
        hardware.apply(configuration)

        self.assertEqual(len(self.capture.calls), 1)
        device, reports = self.capture.calls[0]
        self.assertEqual(device, self.root / "dev/hidraw0")
        self.assertEqual(len(reports), 3)
        self.assertTrue(all(len(report) == RGB_FEATURE_REPORT_SIZE for report in reports))
        self.assertEqual(reports[0][:5], bytes((0x07, 0xC8, 0x01, 0x00, 0x01)))

        save_profile = reports[1]
        self.assertEqual(save_profile[:7], bytes((0x07, 0xCB, 0xFB, 0x01, 1, 1, 1)))
        offset = 7
        for group_index, color in enumerate(configuration.zones):
            self.assertEqual(
                save_profile[offset : offset + 19],
                bytes(
                    (
                        group_index + 1,
                        6,
                        1,
                        0x0B,
                        2,
                        2,
                        3,
                        0,
                        4,
                        0,
                        5,
                        2,
                        6,
                        0,
                        1,
                        color.red,
                        color.green,
                        color.blue,
                        1,
                    )
                ),
            )
            self.assertEqual(
                int.from_bytes(save_profile[offset + 19 : offset + 21], "little"),
                group_index + 1,
            )
            offset += 21
        self.assertEqual(offset, 511)
        self.assertEqual(reports[2][:5], bytes((0x07, 0xCE, 0x01, 0x00, 0x09)))

    def test_solid_color_collapses_to_one_complete_range(self) -> None:
        build_rgb_device(self.root)
        hardware = LegionRgbHardware(self.root, self.capture)

        hardware.apply(
            RgbConfiguration(
                True,
                100,
                (RgbColor(255, 0, 0),) * RGB_ZONE_COUNT,
            )
        )

        _, reports = self.capture.calls[0]
        self.assertEqual(reports[0][:5], bytes((0x07, 0xC8, 1, 0, 1)))
        self.assertEqual(
            reports[1][:26],
            bytes(
                (
                    0x07,
                    0xCB,
                    0x46,
                    0x00,
                    1,
                    1,
                    1,
                    1,
                    6,
                    1,
                    0x0B,
                    2,
                    2,
                    3,
                    0,
                    4,
                    0,
                    5,
                    2,
                    6,
                    0,
                    1,
                    255,
                    0,
                    0,
                    24,
                )
            ),
        )
        self.assertEqual(
            reports[1][26:74],
            b"".join(led_id.to_bytes(2, "little") for led_id in range(1, 25)),
        )
        self.assertEqual(reports[2][:5], bytes((0x07, 0xCE, 1, 0, 9)))

    def test_disabled_configuration_writes_off_profile(self) -> None:
        build_rgb_device(self.root)
        hardware = LegionRgbHardware(self.root, self.capture)

        hardware.apply(
            RgbConfiguration(
                False,
                100,
                (RgbColor(255, 0, 0),) * RGB_ZONE_COUNT,
            )
        )

        _, reports = self.capture.calls[0]
        self.assertEqual(len(reports), 2)
        self.assertEqual(reports[0][:5], bytes((0x07, 0xC8, 1, 0, 1)))
        self.assertEqual(reports[1][:7], bytes((0x07, 0xCB, 3, 0, 1, 1, 1)))

    def test_rejects_unknown_product_id_or_interface(self) -> None:
        build_rgb_device(self.root, product_id="FFFF")
        self.assertFalse(LegionRgbHardware(self.root, self.capture).is_available())


class FeatureReportTransportTests(unittest.TestCase):
    @patch("legion_control.rgb.time.sleep")
    @patch("legion_control.rgb.os.close")
    @patch("legion_control.rgb.fcntl.ioctl")
    @patch("legion_control.rgb.os.open", return_value=42)
    @patch("legion_control.rgb._validate_open_device")
    def test_writes_complete_frame_on_one_open_descriptor(
        self,
        validate_mock,
        open_mock,
        ioctl_mock,
        close_mock,
        sleep_mock,
    ) -> None:
        reports = tuple(bytes((0x07,)) + bytes(RGB_FEATURE_REPORT_SIZE - 1) for _ in range(3))
        ioctl_mock.side_effect = [RGB_FEATURE_REPORT_SIZE] * 3

        _send_feature_reports(Path("/dev/hidraw2"), reports)

        open_mock.assert_called_once()
        _, open_flags = open_mock.call_args.args
        self.assertTrue(open_flags & os.O_NOFOLLOW)
        validate_mock.assert_called_once_with(42)
        self.assertEqual(ioctl_mock.call_count, 3)
        self.assertTrue(all(invocation.args[0] == 42 for invocation in ioctl_mock.call_args_list))
        self.assertEqual(
            sleep_mock.call_args_list,
            [call(RGB_REPORT_DELAY_SECONDS)] * 3,
        )
        close_mock.assert_called_once_with(42)

    @patch("legion_control.rgb.os.close")
    @patch("legion_control.rgb.fcntl.ioctl", return_value=0)
    @patch("legion_control.rgb.os.open", return_value=42)
    @patch("legion_control.rgb._validate_open_device")
    def test_rejects_short_feature_report_write(
        self,
        _validate_mock,
        _open_mock,
        _ioctl_mock,
        close_mock,
    ) -> None:
        with self.assertRaisesRegex(OSError, "Escritura HID incompleta"):
            _send_feature_reports(
                Path("/dev/hidraw2"),
                (bytes((0x07,)) + bytes(RGB_FEATURE_REPORT_SIZE - 1),),
            )

        close_mock.assert_called_once_with(42)


class OpenDeviceValidationTests(unittest.TestCase):
    @patch("legion_control.rgb.fcntl.ioctl")
    def test_validates_identity_and_descriptor_from_open_file_descriptor(
        self,
        ioctl_mock,
    ) -> None:
        descriptor_payload = bytes((0x06, 0x89, 0xFF, 0x09, 0x07, 0xA1, 0x01, 0x85, 0x07))

        def ioctl_side_effect(_fd, request, buffer, _mutate):
            number = request & 0xFF
            if number == 0x03:
                struct.pack_into("@Ihh", buffer, 0, 0x03, 0x048D, -0x3E6B)
            elif number == 0x01:
                struct.pack_into("@I", buffer, 0, len(descriptor_payload))
            elif number == 0x02:
                buffer[4 : 4 + len(descriptor_payload)] = descriptor_payload
            return 0

        ioctl_mock.side_effect = ioctl_side_effect

        _validate_open_device(42)

        self.assertEqual(ioctl_mock.call_count, 3)

    @patch("legion_control.rgb.fcntl.ioctl")
    def test_rejects_replaced_hidraw_node_with_wrong_product(self, ioctl_mock) -> None:
        def ioctl_side_effect(_fd, request, buffer, _mutate):
            if request & 0xFF == 0x03:
                struct.pack_into("@Ihh", buffer, 0, 0x03, 0x048D, 0x1234)
            return 0

        ioctl_mock.side_effect = ioctl_side_effect

        with self.assertRaisesRegex(OSError, "048d:c195"):
            _validate_open_device(42)


if __name__ == "__main__":
    unittest.main()
