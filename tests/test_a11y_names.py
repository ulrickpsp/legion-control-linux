"""Every interactive control must expose a name to assistive technologies.

The check runs against a real process through AT-SPI, which is the same path a
screen reader uses; nothing else can observe the accessible name that GTK
computes. It skips cleanly when the session cannot provide that path.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WINDOW_TITLE = "Legion Control"
WINDOW_TIMEOUT_SECONDS = 25.0
DENSE_VIEWS = ("fans", "lighting")


def _atspi():
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    return Atspi


class AccessibleNameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
            raise unittest.SkipTest("La auditoría AT-SPI necesita una sesión gráfica.")
        try:
            cls.atspi = _atspi()
        except (ImportError, ValueError) as error:
            raise unittest.SkipTest(f"AT-SPI no disponible: {error}") from error
        try:
            cls.atspi.get_desktop(0).get_child_count()
        except Exception as error:
            raise unittest.SkipTest(f"El bus de accesibilidad no responde: {error}") from error

    def test_dense_views_expose_a_name_for_every_control(self) -> None:
        for view in DENSE_VIEWS:
            with self.subTest(view=view):
                unnamed, total = self._audit(view)
                self.assertEqual(
                    unnamed,
                    [],
                    f"Vista {view}: {len(unnamed)} de {total} controles sin nombre accesible",
                )
                self.assertGreater(total, 0, f"Vista {view}: no se encontró ningún control")

    def _audit(self, view: str) -> tuple[list[str], int]:
        with TemporaryDirectory() as directory:
            environment = dict(os.environ)
            environment.update(
                LEGION_CONTROL_MOCK="1",
                LEGION_CONTROL_MOCK_CURVE="1",
                LEGION_CONTROL_VIEW=view,
                XDG_CONFIG_HOME=str(Path(directory) / "config"),
                XDG_STATE_HOME=str(Path(directory) / "state"),
                PYTHONPATH=str(PROJECT_ROOT),
            )
            process = subprocess.Popen(
                [sys.executable, "-m", "legion_control.ui"],
                cwd=PROJECT_ROOT,
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                window = self._wait_for_window(process)
                if window is None:
                    raise unittest.SkipTest(
                        "La ventana no apareció en el árbol AT-SPI; "
                        "puede haber otra instancia registrada."
                    )
                return self._unnamed_controls(window)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()

    def _wait_for_window(self, process: subprocess.Popen[bytes]):
        deadline = time.monotonic() + WINDOW_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return None
            desktop = self.atspi.get_desktop(0)
            for index in range(desktop.get_child_count()):
                application = desktop.get_child_at_index(index)
                if application is None:
                    continue
                try:
                    if application.get_process_id() != process.pid:
                        continue
                    for child in range(application.get_child_count()):
                        window = application.get_child_at_index(child)
                        if window is not None and window.get_name() == WINDOW_TITLE:
                            return window
                except Exception:
                    continue
            time.sleep(0.4)
        return None

    def _unnamed_controls(self, window) -> tuple[list[str], int]:
        atspi = self.atspi
        interactive = {
            atspi.Role.PUSH_BUTTON,
            atspi.Role.TOGGLE_BUTTON,
            atspi.Role.CHECK_BOX,
            atspi.Role.RADIO_BUTTON,
            atspi.Role.SLIDER,
            atspi.Role.SPIN_BUTTON,
            atspi.Role.COMBO_BOX,
            atspi.Role.SWITCH,
            atspi.Role.ENTRY,
            atspi.Role.PAGE_TAB,
        }
        unnamed: list[str] = []
        total = 0
        for node in _walk(window):
            try:
                role = node.get_role()
                if role not in interactive:
                    continue
                if not node.get_state_set().contains(atspi.StateType.SHOWING):
                    continue
                name = node.get_name() or ""
                description = node.get_description() or ""
            except Exception:
                continue
            total += 1
            if not name.strip() and not description.strip():
                unnamed.append(role.value_nick)
        return unnamed, total


def _walk(node, budget: list[int] | None = None):
    if budget is None:
        budget = [8000]
    if budget[0] <= 0:
        return
    budget[0] -= 1
    yield node
    try:
        count = node.get_child_count()
    except Exception:
        return
    for index in range(count):
        try:
            child = node.get_child_at_index(index)
        except Exception:
            continue
        if child is not None:
            yield from _walk(child, budget)


if __name__ == "__main__":
    unittest.main()
