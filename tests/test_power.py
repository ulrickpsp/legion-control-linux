from __future__ import annotations

import unittest

from legion_control.power import (
    CustomPowerLimits,
    PowerLimitBounds,
    PowerLimitCapabilities,
    power_limits_from_json,
    power_limits_to_json,
)


class CustomPowerLimitsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.capabilities = PowerLimitCapabilities(
            sustained=PowerLimitBounds(50, 135, 1, 70),
            slow=PowerLimitBounds(60, 210, 1, 125),
        )

    def test_validates_limits_against_firmware_bounds(self) -> None:
        limits = CustomPowerLimits(sustained_w=70, slow_w=125)
        limits.validate_for(self.capabilities)

        with self.assertRaisesRegex(ValueError, "sostenida"):
            CustomPowerLimits(sustained_w=136, slow_w=125).validate_for(self.capabilities)

    def test_round_trip_uses_strict_versioned_json(self) -> None:
        limits = CustomPowerLimits(sustained_w=70, slow_w=125)
        self.assertEqual(power_limits_from_json(power_limits_to_json(limits)), limits)

    def test_rejects_extra_keys_and_boolean_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "claves"):
            power_limits_from_json('{"version":1,"sustained_w":70,"slow_w":125,"path":"/tmp/x"}')
        with self.assertRaisesRegex(ValueError, "entero"):
            power_limits_from_json('{"version":1,"sustained_w":true,"slow_w":125}')


if __name__ == "__main__":
    unittest.main()
