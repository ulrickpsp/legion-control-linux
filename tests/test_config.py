from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path

from legion_control.config import (
    ConfigStore,
    ConfigurationError,
    default_policy,
    policy_from_json,
    policy_to_json,
)
from legion_control.domain import DEFAULT_CURVE, FanMode, FanPolicy


class ConfigurationTests(unittest.TestCase):
    def test_round_trip_preserves_policy(self) -> None:
        policy = FanPolicy(FanMode.CURVE, 2600, DEFAULT_CURVE)
        self.assertEqual(policy_from_json(policy_to_json(policy)), policy)

    def test_rejects_extra_keys(self) -> None:
        document = json.loads(policy_to_json(default_policy()))
        document["path"] = "/etc/shadow"
        with self.assertRaisesRegex(ConfigurationError, "claves incorrectas"):
            policy_from_json(json.dumps(document))

    def test_rejects_boolean_as_integer(self) -> None:
        document = json.loads(policy_to_json(default_policy()))
        document["fixed_rpm"] = True
        with self.assertRaisesRegex(ConfigurationError, "entero"):
            policy_from_json(json.dumps(document))

    def test_store_replaces_atomically_with_public_read_only_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fan-config.json"
            store = ConfigStore(path)
            policy = FanPolicy(FanMode.FIXED, 2700, DEFAULT_CURVE)
            store.save(policy)
            self.assertEqual(store.load(), policy)
            mode = stat.S_IMODE(path.stat().st_mode)
            self.assertEqual(mode, 0o644)


if __name__ == "__main__":
    unittest.main()
