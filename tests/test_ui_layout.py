from __future__ import annotations

import os
import time
import unittest
from tempfile import TemporaryDirectory

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from legion_control.mock import MockControlClient  # noqa: E402
from legion_control.tray import TrayController  # noqa: E402
from legion_control.ui import MainWindow  # noqa: E402


SMALLEST_SUPPORTED_DESKTOP = (1366, 768)


class HeaderLayoutTests(unittest.TestCase):
    """The view switcher must stay readable at the smallest supported desktop."""

    @classmethod
    def setUpClass(cls) -> None:
        if Gdk.Display.get_default() is None:
            raise unittest.SkipTest(
                "Los tests GTK necesitan un display; usa un runner Wayland/X11 virtual."
            )
        Adw.init()

    def setUp(self) -> None:
        # MainWindow samples telemetry into XDG_STATE_HOME; keep that out of the
        # shared archive so the rest of the suite still sees an empty history.
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        previous = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = directory.name
        self.addCleanup(_restore_state_home, previous)

    def test_no_header_label_is_truncated_at_1366x768(self) -> None:
        application = Adw.Application(application_id="io.github.ulrickpsp.LegionControlTest")
        application.register(None)
        window = MainWindow(application, MockControlClient(), TrayController(lambda: None))
        self.addCleanup(window.destroy)
        window.present()
        _pump(0.6)

        width, height = SMALLEST_SUPPORTED_DESKTOP
        window.set_default_size(width, height)
        deadline = time.monotonic() + 4.0
        while window.get_width() != width and time.monotonic() < deadline:
            _pump(0.1)
        if window.get_width() != width:
            raise unittest.SkipTest(
                f"El compositor no concedió {width}x{height}; no se puede medir el recorte."
            )
        _pump(0.4)

        truncated = [
            label.get_label()
            for label in _walk(window)
            if isinstance(label, Gtk.Label)
            and label.get_mapped()
            and label.get_layout() is not None
            and label.get_layout().is_ellipsized()
        ]

        self.assertEqual(truncated, [])


def _restore_state_home(previous: str | None) -> None:
    if previous is None:
        os.environ.pop("XDG_STATE_HOME", None)
    else:
        os.environ["XDG_STATE_HOME"] = previous


def _walk(widget: Gtk.Widget):
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from _walk(child)
        child = child.get_next_sibling()


def _pump(seconds: float) -> None:
    context = GLib.MainContext.default()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        time.sleep(0.002)


if __name__ == "__main__":
    unittest.main()
