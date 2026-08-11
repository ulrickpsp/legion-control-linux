"""Shared save-destination flow for the local export actions."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gio, GLib, Gtk  # noqa: E402

from legion_control.i18n import translate  # noqa: E402


CANCELLED_CODES = (Gtk.DialogError.DISMISSED, Gtk.DialogError.CANCELLED)


def choose_save_path(
    widget: Gtk.Widget,
    *,
    title: str,
    suggested_name: str,
    on_path: Callable[[Path], None],
    on_error: Callable[[str], None],
) -> None:
    """Ask for a destination and hand the resolved path to ``on_path``.

    Cancelling is a normal outcome and reports nothing back to the user.
    """

    dialog = Gtk.FileDialog()
    dialog.set_title(title)
    dialog.set_initial_name(suggested_name)
    root = widget.get_root()
    parent = root if isinstance(root, Gtk.Window) else None

    def finished(source: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            selected = source.save_finish(result)
        except GLib.Error as error:
            if not _is_cancelled(error):
                on_error(
                    translate(
                        "No se pudo elegir el destino: {error}",
                        error=error.message,
                    )
                )
            return
        path = selected.get_path() if selected is not None else None
        if path is None:
            on_error(translate("No se pudo resolver la ruta de destino."))
            return
        on_path(Path(path))

    dialog.save(parent, None, finished)


def _is_cancelled(error: GLib.Error) -> bool:
    return (
        error.domain == GLib.quark_to_string(Gtk.dialog_error_quark())
        and error.code in CANCELLED_CODES
    )
