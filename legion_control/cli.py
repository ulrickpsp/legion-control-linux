"""Small terminal workflows backed by the same bounded client as the UI."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Protocol, TextIO

from legion_control.client import LocalControlClient
from legion_control.doctor import build_doctor_report
from legion_control.i18n import configure_startup_language, translate
from legion_control.linux import SysfsHardware
from legion_control.scenes import (
    SceneSlot,
    SceneStore,
    apply_scene,
    default_scene_path,
    load_scenes_for_status,
)


class CommandClient(Protocol):
    def read_status(self) -> dict[str, object]: ...
    def restore_auto(self) -> dict[str, object]: ...
    def set_profile(self, profile: str) -> dict[str, object]: ...
    def set_custom_configuration(
        self, policy: object, power_limits: object
    ) -> dict[str, object]: ...
    def set_rgb_configuration(self, configuration: object) -> dict[str, object]: ...


def main(
    arguments: Sequence[str] | None = None,
    *,
    client: CommandClient | None = None,
    output: TextIO | None = None,
) -> int:
    configure_startup_language()
    parser = _parser()
    parsed = parser.parse_args(arguments)
    out = output or sys.stdout
    control = client or LocalControlClient(SysfsHardware())
    if parsed.command == "status":
        _write_json(out, control.read_status())
        return 0
    if parsed.command == "doctor":
        report = build_doctor_report(control.read_status())
        out.write(report.to_json() if parsed.json else report.to_text())
        return 0
    if parsed.command == "restore-firmware":
        _write_json(out, control.restore_auto())
        return 0
    if parsed.command == "scene":
        status = control.read_status()
        scene = load_scenes_for_status(SceneStore(default_scene_path()), status)[
            SceneSlot(parsed.slot)
        ]
        capabilities = status.get("capabilities")
        rgb_available = isinstance(capabilities, dict) and bool(capabilities.get("rgb_control"))
        _write_json(out, apply_scene(control, scene, rgb_available=rgb_available))
        return 0
    parser.error(translate("Orden no admitida."))
    return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="legion-control",
        description=translate("Atajos locales de Legion Control."),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help=translate("Muestra estado JSON solo lectura"))
    doctor = commands.add_parser(
        "doctor",
        help=translate("Genera informe Doctor solo lectura"),
    )
    doctor.add_argument("--json", action="store_true", help=translate("Emite JSON"))
    commands.add_parser(
        "restore-firmware",
        help=translate("Detiene curva manual y devuelve ventiladores al firmware"),
    )
    scene = commands.add_parser("scene", help=translate("Aplica una escena guardada"))
    scene.add_argument("slot", choices=[slot.value for slot in SceneSlot])
    return parser


def _write_json(output: TextIO, document: dict[str, object]) -> None:
    output.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
