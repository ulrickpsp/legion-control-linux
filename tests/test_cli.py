from __future__ import annotations

import io
import json
import unittest

from legion_control.cli import main
from legion_control.doctor import VALIDATED_BIOS_VERSION, SystemProbe


class CliTests(unittest.TestCase):
    def test_doctor_json_uses_read_only_status(self) -> None:
        client = FakeClient()
        output = io.StringIO()

        exit_code = main(["doctor", "--json"], client=client, output=output, probe=_healthy_probe())

        self.assertEqual(exit_code, 0)
        self.assertEqual(client.reads, 1)
        self.assertEqual(client.mutations, [])
        self.assertEqual(json.loads(output.getvalue())["severity"], "ok")

    def test_doctor_reports_an_environment_problem_the_status_cannot_show(self) -> None:
        client = FakeClient()
        output = io.StringIO()

        exit_code = main(
            ["doctor", "--json"],
            client=client,
            output=output,
            probe=_healthy_probe(helper_installed=False),
        )

        document = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(document["severity"], "error")
        privileges = next(item for item in document["findings"] if item["key"] == "privileges")
        self.assertTrue(privileges["remedy"])

    def test_restore_firmware_uses_the_bounded_client_operation(self) -> None:
        client = FakeClient()
        output = io.StringIO()

        exit_code = main(["restore-firmware"], client=client, output=output)

        self.assertEqual(exit_code, 0)
        self.assertEqual(client.mutations, ["restore"])


def _healthy_probe(**overrides: object) -> SystemProbe:
    defaults: dict[str, object] = {
        "helper_installed": True,
        "polkit_action_installed": True,
        "loaded_modules": ("lenovo_wmi_gamezone", "lenovo_wmi_other"),
        "fan_service_state": "inactive",
        "fan_service_enabled": "disabled",
        "bios_version": VALIDATED_BIOS_VERSION,
    }
    return SystemProbe(**(defaults | overrides))  # type: ignore[arg-type]


class FakeClient:
    def __init__(self) -> None:
        self.reads = 0
        self.mutations: list[str] = []

    def read_status(self) -> dict[str, object]:
        self.reads += 1
        return {
            "capabilities": {
                "product": "83LU",
                "product_version": "Legion Pro 5",
                "supported": True,
                "fan_control": True,
                "rgb_control": True,
            },
            "cpu_temperature_c": 60,
            "gpu_temperature_c": 50,
            "fan1_rpm": 2100,
            "fan2_rpm": 2100,
            "fan_service_active": False,
        }

    def restore_auto(self) -> dict[str, object]:
        self.mutations.append("restore")
        return {"mode": "auto"}


if __name__ == "__main__":
    unittest.main()
