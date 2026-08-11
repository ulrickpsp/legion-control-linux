"""Optional StatusNotifierItem tray icon with a harmless no-watcher fallback."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Final

import gi

gi.require_version("Gio", "2.0")

from gi.repository import Gio, GLib  # noqa: E402

from legion_control.i18n import translate  # noqa: E402


WATCHER_BUS_NAME: Final = "org.kde.StatusNotifierWatcher"
WATCHER_OBJECT_PATH: Final = "/StatusNotifierWatcher"
WATCHER_INTERFACE: Final = "org.kde.StatusNotifierWatcher"
ITEM_INTERFACE: Final = "org.kde.StatusNotifierItem"
ITEM_OBJECT_PATH: Final = "/StatusNotifierItem"
PROPERTIES_INTERFACE: Final = "org.freedesktop.DBus.Properties"
ITEM_XML: Final = """
<node>
  <interface name='org.kde.StatusNotifierItem'>
    <method name='Activate'><arg type='i' direction='in'/><arg type='i' direction='in'/></method>
    <method name='SecondaryActivate'><arg type='i' direction='in'/><arg type='i' direction='in'/></method>
    <method name='ContextMenu'><arg type='i' direction='in'/><arg type='i' direction='in'/></method>
    <method name='Scroll'><arg type='i' direction='in'/><arg type='s' direction='in'/></method>
    <property name='Category' type='s' access='read'/>
    <property name='Id' type='s' access='read'/>
    <property name='Title' type='s' access='read'/>
    <property name='Status' type='s' access='read'/>
    <property name='WindowId' type='i' access='read'/>
    <property name='IconName' type='s' access='read'/>
    <property name='IconPixmap' type='a(iiay)' access='read'/>
    <property name='ToolTip' type='(sa(iiay)ss)' access='read'/>
    <property name='ItemIsMenu' type='b' access='read'/>
  </interface>
</node>
"""


class TrayController:
    """Exports a tray item only when a StatusNotifier watcher accepts it."""

    def __init__(self, activate: Callable[[], None]) -> None:
        self._activate = activate
        self._connection: Gio.DBusConnection | None = None
        self._registration_id = 0
        self._owner_id = 0
        self._available = False
        self._tooltip = "Legion Control"
        self._bus_name = f"io.github.ulrickpsp.LegionControl.Tray{os.getpid()}"

    @property
    def available(self) -> bool:
        return self._available

    def start(self) -> None:
        if self._owner_id:
            return
        self._owner_id = Gio.bus_own_name(
            Gio.BusType.SESSION,
            self._bus_name,
            Gio.BusNameOwnerFlags.NONE,
            self._on_bus_acquired,
            None,
            self._on_name_lost,
        )

    def stop(self) -> None:
        self._available = False
        if self._connection is not None and self._registration_id:
            self._connection.unregister_object(self._registration_id)
        self._registration_id = 0
        self._connection = None
        if self._owner_id:
            Gio.bus_unown_name(self._owner_id)
        self._owner_id = 0

    def update_status(self, status: dict[str, object]) -> None:
        self._tooltip = _tooltip_from_status(status)
        if not self._available or self._connection is None:
            return
        changed = {"ToolTip": self._property("ToolTip")}
        try:
            self._connection.emit_signal(
                None,
                ITEM_OBJECT_PATH,
                PROPERTIES_INTERFACE,
                "PropertiesChanged",
                GLib.Variant("(sa{sv}as)", (ITEM_INTERFACE, changed, [])),
            )
        except GLib.Error:
            self._available = False

    def _on_bus_acquired(
        self,
        connection: Gio.DBusConnection,
        _name: str,
    ) -> None:
        node = Gio.DBusNodeInfo.new_for_xml(ITEM_XML)
        interface = node.interfaces[0]
        self._connection = connection
        self._registration_id = connection.register_object(
            ITEM_OBJECT_PATH,
            interface,
            self._on_method_call,
            self._on_get_property,
            None,
        )
        try:
            connection.call_sync(
                WATCHER_BUS_NAME,
                WATCHER_OBJECT_PATH,
                WATCHER_INTERFACE,
                "RegisterStatusNotifierItem",
                GLib.Variant("(s)", (self._bus_name,)),
                None,
                Gio.DBusCallFlags.NONE,
                1000,
                None,
            )
        except GLib.Error:
            self._available = False
        else:
            self._available = True

    def _on_name_lost(
        self,
        _connection: Gio.DBusConnection | None,
        _name: str,
    ) -> None:
        self._available = False

    def _on_method_call(
        self,
        _connection: Gio.DBusConnection,
        _sender: str,
        _object_path: str,
        _interface_name: str,
        method_name: str,
        _parameters: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        if method_name in {"Activate", "SecondaryActivate", "ContextMenu"}:
            self._activate()
            invocation.return_value(None)
            return
        if method_name == "Scroll":
            invocation.return_value(None)
            return
        invocation.return_dbus_error(
            "org.freedesktop.DBus.Error.UnknownMethod",
            translate("Método no admitido: {method}", method=method_name),
        )

    def _on_get_property(
        self,
        _connection: Gio.DBusConnection,
        _sender: str,
        _object_path: str,
        _interface_name: str,
        property_name: str,
    ) -> GLib.Variant | None:
        return self._property(property_name)

    def _property(self, name: str) -> GLib.Variant | None:
        values: dict[str, GLib.Variant] = {
            "Category": GLib.Variant("s", "Hardware"),
            "Id": GLib.Variant("s", "legion-control"),
            "Title": GLib.Variant("s", "Legion Control"),
            "Status": GLib.Variant("s", "Active"),
            "WindowId": GLib.Variant("i", 0),
            "IconName": GLib.Variant("s", "io.github.ulrickpsp.LegionControl"),
            "IconPixmap": GLib.Variant("a(iiay)", []),
            "ToolTip": GLib.Variant(
                "(sa(iiay)ss)",
                ("", [], "Legion Control", self._tooltip),
            ),
            "ItemIsMenu": GLib.Variant("b", False),
        }
        return values.get(name)


def _tooltip_from_status(status: dict[str, object]) -> str:
    readings = []
    cpu = status.get("cpu_temperature_c")
    gpu = status.get("gpu_temperature_c")
    battery = status.get("battery_percent")
    if type(cpu) is int:
        readings.append(f"CPU {cpu} °C")
    if type(gpu) is int:
        readings.append(f"GPU {gpu} °C")
    if type(battery) is int:
        readings.append(f"{translate('Batería')} {battery}%")
    return " · ".join(readings) if readings else "Legion Control"
