from __future__ import annotations

import re
import tomllib
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import legion_control


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


class PackagingSafetyTests(unittest.TestCase):
    def test_public_identity_is_consistent(self) -> None:
        app_id = "io.github.ulrickpsp.LegionControl"
        project_url = "https://github.com/ulrickpsp/legion-control-linux"
        project = tomllib.loads(_read("pyproject.toml"))
        self.assertEqual(project["project"]["urls"]["Homepage"], project_url)
        self.assertIn(
            "Development Status :: 4 - Beta",
            project["project"]["classifiers"],
        )

        desktop = _read(f"packaging/applications/{app_id}.desktop")
        self.assertIn(f"Icon={app_id}", desktop)
        metainfo = _read(f"packaging/metainfo/{app_id}.metainfo.xml")
        self.assertIn(f"<id>{app_id}</id>", metainfo)
        self.assertIn(f'<url type="homepage">{project_url}</url>', metainfo)
        self.assertIn(f'APPLICATION_ID: Final = "{app_id}"', _read("legion_control/ui.py"))
        self.assertIn(f"Homepage: {project_url}", _read("packaging/debian/control"))

    def test_public_beta_scope_and_disclaimer_are_explicit(self) -> None:
        readme = _read("README.md")
        for fragment in (
            "**Status: beta.**",
            "one unit",
            "Use it at your own risk",
            "MIT License",
            "does not expand its\n> allowlist",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, readme)

        metainfo = _read("packaging/metainfo/io.github.ulrickpsp.LegionControl.metainfo.xml")
        self.assertIn("Controles beta para el Lenovo Legion 83LU", metainfo)
        self.assertIn("una sola unidad", metainfo)

    def test_privileged_helper_requires_active_admin_authentication(self) -> None:
        policy = ET.fromstring(_read("packaging/polkit/io.github.ulrickpsp.policy"))
        action = policy.find("./action[@id='io.github.ulrickpsp.control']")
        self.assertIsNotNone(action)
        assert action is not None

        self.assertEqual(action.findtext("./defaults/allow_any"), "no")
        self.assertEqual(action.findtext("./defaults/allow_inactive"), "no")
        self.assertEqual(action.findtext("./defaults/allow_active"), "auth_admin_keep")
        paths = {
            item.attrib.get("key"): (item.text or "").strip()
            for item in action.findall("./annotate")
        }
        self.assertEqual(
            paths["org.freedesktop.policykit.exec.path"],
            "/usr/libexec/legion-control-helper",
        )

    def test_fan_service_restores_firmware_and_has_no_network(self) -> None:
        unit = _read("packaging/systemd/legion-control-fand.service")
        required_lines = {
            "ExecStopPost=/usr/libexec/legion-control-fand --restore-auto",
            "NoNewPrivileges=yes",
            "PrivateNetwork=yes",
            "PrivateDevices=yes",
            "ProtectSystem=strict",
            "ProtectHome=yes",
            "ProtectKernelModules=yes",
            "CapabilityBoundingSet=",
            "AmbientCapabilities=",
            "RestartPreventExitStatus=3",
        }
        self.assertTrue(required_lines.issubset(set(unit.splitlines())))

    def test_package_removal_attempts_firmware_restore(self) -> None:
        prerm = _read("packaging/debian/prerm")
        self.assertIn("systemctl disable --now legion-control-fand.service", prerm)
        self.assertIn("/usr/libexec/legion-control-fand --restore-auto", prerm)

    def test_future_upgrades_restore_an_active_manual_service(self) -> None:
        marker = "/run/legion-control-fand.restart-after-upgrade"
        prerm = _read("packaging/debian/prerm")
        postinst = _read("packaging/debian/postinst")

        self.assertIn('[ "$1" = "upgrade" ]', prerm)
        self.assertIn("systemctl is-active --quiet legion-control-fand.service", prerm)
        self.assertIn(marker, prerm)
        self.assertIn(f"RESTART_MARKER={marker}", postinst)
        self.assertIn('[ -f "$RESTART_MARKER" ]', postinst)
        self.assertIn("systemctl enable --now legion-control-fand.service", postinst)

    def test_an_upgrade_cannot_keep_running_the_previous_release(self) -> None:
        """Reproducible builds pin source mtimes, so cached bytecode never expires.

        Python invalidates a .pyc by the source's (mtime, size). Both survive an
        upgrade for any file whose length is unchanged, so a stale cache would
        keep executing the previous version. Two guards: the entry points never
        write bytecode, and installation clears what earlier versions wrote.
        """

        cache = "/usr/lib/legion-control/legion_control/__pycache__"
        for entry_point in (
            "packaging/bin/legion-control",
            "packaging/libexec/legion-control-helper",
            "packaging/libexec/legion-control-fand",
        ):
            with self.subTest(entry_point=entry_point):
                self.assertTrue(_read(entry_point).startswith("#!/usr/bin/python3 -IB\n"))
        # Bounded to .pyc files in one directory: no recursive delete anywhere.
        for script in ("packaging/debian/postinst", "packaging/debian/postrm"):
            with self.subTest(script=script):
                self.assertIn(f"rm -f {cache}/*.pyc", _read(script))

    def test_purge_removes_only_known_state_files(self) -> None:
        postrm = _read("packaging/debian/postrm")
        self.assertIn("/var/lib/legion-control/fan-config.json", postrm)
        self.assertIn("/var/lib/legion-control/rgb-config.json", postrm)
        self.assertNotIn("rm -rf", postrm)
        self.assertNotIn("rm -r ", postrm)

    def test_installed_python_launchers_use_isolated_mode_and_fixed_path(self) -> None:
        launchers = (
            "packaging/bin/legion-control",
            "packaging/libexec/legion-control-helper",
            "packaging/libexec/legion-control-fand",
        )
        for relative_path in launchers:
            with self.subTest(launcher=relative_path):
                launcher = _read(relative_path)
                # -I isolates the interpreter; -B keeps it from caching bytecode
                # that a later upgrade could not invalidate.
                self.assertTrue(launcher.startswith("#!/usr/bin/python3 -IB\n"))
                self.assertIn('sys.path.insert(0, "/usr/lib/legion-control")', launcher)

    def test_release_version_is_consistent_across_package_metadata(self) -> None:
        project = tomllib.loads(_read("pyproject.toml"))
        expected = project["project"]["version"]
        self.assertEqual(legion_control.__version__, expected)

        control_match = re.search(
            r"^Version: (?P<version>\S+)$",
            _read("packaging/debian/control"),
            re.MULTILINE,
        )
        self.assertIsNotNone(control_match)
        assert control_match is not None
        self.assertEqual(control_match.group("version"), expected)

        build_match = re.search(
            r'^PACKAGE_NAME="legion-control_(?P<version>[^_]+)_all\.deb"$',
            _read("scripts/build-deb.sh"),
            re.MULTILINE,
        )
        self.assertIsNotNone(build_match)
        assert build_match is not None
        self.assertEqual(build_match.group("version"), expected)

        metainfo = ET.fromstring(
            _read("packaging/metainfo/io.github.ulrickpsp.LegionControl.metainfo.xml")
        )
        newest_release = metainfo.find("./releases/release")
        self.assertIsNotNone(newest_release)
        assert newest_release is not None
        self.assertEqual(newest_release.attrib.get("version"), expected)

    def test_build_script_packages_only_python_sources(self) -> None:
        build_script = _read("scripts/build-deb.sh")
        self.assertIn('"$PROJECT_DIR"/legion_control/*.py', build_script)
        self.assertNotIn("__pycache__", build_script)
        self.assertNotIn("*.pyc", build_script)
        self.assertIn("THIRD_PARTY_NOTICES.md", build_script)
        self.assertIn("legion-control.1.gz", build_script)
        self.assertIn("SOURCE_DATE_EPOCH", build_script)
        self.assertIn("Installed-Size", build_script)
        self.assertIn("DEBIAN/md5sums", build_script)


if __name__ == "__main__":
    unittest.main()
