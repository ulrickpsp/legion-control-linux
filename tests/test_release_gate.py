from __future__ import annotations

import os
import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


class ReleaseGateContractTests(unittest.TestCase):
    def test_repository_hygiene_files_cover_generated_artifacts(self) -> None:
        gitignore = set(_read(".gitignore").splitlines())
        self.assertTrue(
            {
                "__pycache__/",
                "*.py[cod]",
                "build/",
                "dist/",
                "*.egg-info/",
                "*.deb",
                ".venv/",
                ".env",
            }.issubset(gitignore)
        )

        editorconfig = _read(".editorconfig")
        self.assertIn("root = true", editorconfig)
        self.assertIn("end_of_line = lf", editorconfig)
        self.assertIn("insert_final_newline = true", editorconfig)

        attributes = _read(".gitattributes")
        self.assertIn("* text=auto eol=lf", attributes)
        self.assertIn("*.deb binary", attributes)

    def test_release_gate_is_executable_posix_shell(self) -> None:
        gate_path = PROJECT_ROOT / "scripts/check.sh"
        self.assertTrue(os.access(gate_path, os.X_OK))
        self.assertTrue(_read("scripts/check.sh").startswith("#!/bin/sh\n"))

    def test_release_gate_covers_tests_metadata_and_package_inspection(self) -> None:
        gate = _read("scripts/check.sh")
        expected_fragments = {
            "python3 -m compileall",
            "python3 -m unittest discover -v",
            "desktop-file-validate",
            "appstreamcli validate --no-net",
            'sh "$PROJECT_DIR/scripts/build-deb.sh"',
            "dpkg-deb --info",
            "dpkg-deb --contents",
            "dpkg-deb --control",
            "cmp -s",
        }
        for fragment in expected_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, gate)

    def test_release_gate_stays_offline_and_unprivileged(self) -> None:
        gate = _read("scripts/check.sh")
        forbidden_commands = re.compile(
            r"(?m)^\s*(?:sudo|pkexec|apt|apt-get|curl|wget)(?:\s|$)"
        )
        self.assertIsNone(forbidden_commands.search(gate))
        self.assertNotIn("dpkg --install", gate)
        self.assertNotIn("dpkg -i", gate)


if __name__ == "__main__":
    unittest.main()
