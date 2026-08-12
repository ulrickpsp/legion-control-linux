from __future__ import annotations

import unittest
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from legion_control.automation import AutomationStore  # noqa: E402
from legion_control.domain import DEFAULT_CURVE, FanMode  # noqa: E402
from legion_control.history import TelemetryArchive  # noqa: E402
from legion_control.i18n import localize_widget_tree, set_language, translate  # noqa: E402
from legion_control.mock import MockControlClient  # noqa: E402
from legion_control.scenes import SceneSlot, SceneStore  # noqa: E402
from legion_control.ui import (  # noqa: E402
    PROFILE_VALUES,
    SELECTABLE_PROFILE_VALUES,
    FanPage,
    HomePage,
    MainWindow,
    Operation,
)
from legion_control.doctor import SystemProbe  # noqa: E402
from legion_control.ui_automation import AutomationPage  # noqa: E402
from legion_control.ui_doctor import DoctorPage  # noqa: E402
from legion_control.ui_lighting import LightingPage  # noqa: E402
from legion_control.ui_scenes import ScenePanel  # noqa: E402
from legion_control.updates import (  # noqa: E402
    RELEASES_PAGE_URL,
    UpdateConfig,
    UpdateResult,
    UpdateState,
    UpdateStore,
)


class MutationCapture:
    def __init__(self) -> None:
        self.calls: list[
            tuple[
                Operation,
                str,
                Callable[[], None] | None,
                Callable[[], None] | None,
            ]
        ] = []

    def __call__(
        self,
        operation: Operation,
        message: str,
        on_success: Callable[[], None] | None,
        on_failure: Callable[[], None] | None,
    ) -> None:
        self.calls.append((operation, message, on_success, on_failure))


class PageStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if Gdk.Display.get_default() is None:
            raise unittest.SkipTest(
                "Los tests GTK necesitan un display; usa un runner Wayland/X11 virtual."
            )
        Adw.init()

    def setUp(self) -> None:
        self.client = MockControlClient()
        self.mutations = MutationCapture()

    def _archive(self) -> TelemetryArchive:
        """A private archive per test, so history never leaks between tests."""
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return TelemetryArchive(Path(directory.name) / "telemetry.jsonl")

    def test_refresh_does_not_overwrite_unapplied_fan_mode(self) -> None:
        page = FanPage(self.client, self.mutations, lambda: None)
        page.update_status(self.client.read_status())

        page._mode_buttons[FanMode.CURVE].set_active(True)
        page.update_status(self.client.read_status())

        self.assertTrue(page._mode_buttons[FanMode.CURVE].get_active())
        self.assertIn("sin aplicar", page._editor_group.get_description().lower())

    def test_refresh_does_not_overwrite_unapplied_custom_power(self) -> None:
        page = FanPage(self.client, self.mutations, lambda: None)
        page.update_status(self.client.read_status())

        page._mode_buttons[FanMode.CURVE].set_active(True)
        page._sustained_adjustment.set_value(82)
        page._slow_adjustment.set_value(145)
        page.update_status(self.client.read_status())

        self.assertEqual(page._sustained_spin.get_value_as_int(), 82)
        self.assertEqual(page._slow_spin.get_value_as_int(), 145)

    def test_manual_apply_combines_fans_and_power(self) -> None:
        page = FanPage(self.client, self.mutations, lambda: None)
        page.update_status(self.client.read_status())
        page._mode_buttons[FanMode.CURVE].set_active(True)
        page._sustained_adjustment.set_value(80)
        page._slow_adjustment.set_value(140)

        page._on_apply_clicked(page._apply_button)
        operation, _, _, _ = self.mutations.calls[-1]
        operation()

        self.assertEqual(self.client.profile, "custom")
        self.assertEqual(self.client.policy.mode, FanMode.CURVE)
        self.assertEqual(self.client.power_limits.sustained_w, 80)
        self.assertEqual(self.client.power_limits.slow_w, 140)

    def test_refresh_does_not_overwrite_pending_profile(self) -> None:
        page = HomePage(
            self.client,
            self.mutations,
            lambda: None,
            telemetry_archive=self._archive(),
        )
        page.update_status(self.client.read_status())

        page._profile_row.set_selected(1)
        page.update_status(self.client.read_status())

        self.assertEqual(page._profile_row.get_selected(), 1)
        self.assertIn("confirmando", page._profile_row.get_subtitle().lower())

    def test_successful_profile_change_shows_kernel_readback(self) -> None:
        page = HomePage(
            self.client,
            self.mutations,
            lambda: None,
            telemetry_archive=self._archive(),
        )
        page.update_status(self.client.read_status())
        page._profile_row.set_selected(1)
        operation, _, on_success, _ = self.mutations.calls[-1]

        operation()
        self.assertIsNotNone(on_success)
        on_success()
        page.update_status(self.client.read_status())

        self.assertEqual(page._profile_row.get_selected(), 1)
        self.assertIn("confirmado", page._profile_row.get_subtitle().lower())

    def test_home_collects_short_history_on_each_refresh(self) -> None:
        page = HomePage(
            self.client,
            self.mutations,
            lambda: None,
            telemetry_archive=self._archive(),
        )
        page.update_status(self.client.read_status())
        page.update_status(self.client.read_status())

        self.assertEqual(len(page._history_panel.history.samples), 2)

    def test_refresh_preserves_a_preset_waiting_to_be_written(self) -> None:
        page = LightingPage(
            self.client,
            self.mutations,
            lambda: None,
            lambda _message: None,
        )
        page.update_status(self.client.read_status())

        page._preset_white()
        page.update_status(self.client.read_status())

        configuration = page.current_configuration()
        self.assertEqual(configuration.zones[0].red, 235)
        self.assertTrue(page._pending_write)

    def test_a_preset_keeps_the_brightness_the_user_chose(self) -> None:
        page = LightingPage(
            self.client,
            self.mutations,
            lambda: None,
            lambda _message: None,
        )
        page.update_status(self.client.read_status())
        page._brightness.set_value(23)

        page._preset_white()

        # "Blanco" ships 45 %, but brightness belongs to the user, not the preset.
        self.assertEqual(page.current_configuration().brightness_percent, 23)
        self.assertEqual(page.current_configuration().zones[0].red, 235)

    def test_edits_are_written_without_an_apply_button(self) -> None:
        page = LightingPage(
            self.client,
            self.mutations,
            lambda: None,
            lambda _message: None,
        )
        page.update_status(self.client.read_status())
        page._preset_legion()

        self.assertTrue(page._pending_write)
        page._flush_write()
        operation, _message, _success, _failure = self.mutations.calls[-1]
        operation()

        self.assertFalse(page._pending_write)
        self.assertEqual(self.client.rgb_configuration.zones[0].red, 229)

    def test_a_failed_write_keeps_the_colours_on_screen(self) -> None:
        page = LightingPage(
            self.client,
            self.mutations,
            lambda: None,
            lambda _message: None,
        )
        page.update_status(self.client.read_status())
        page._preset_white()
        page._flush_write()
        _operation, _message, _success, failure = self.mutations.calls[-1]

        self.assertIsNotNone(failure)
        failure()
        page.update_status(self.client.read_status())

        # The keyboard still holds the old colours; the draft must survive so
        # the user can retry instead of watching their edit disappear.
        self.assertEqual(page.current_configuration().zones[0].red, 235)

    def test_an_edit_made_during_a_write_is_not_lost(self) -> None:
        page = LightingPage(
            self.client,
            self.mutations,
            lambda: None,
            lambda _message: None,
        )
        page.update_status(self.client.read_status())
        page._preset_legion()
        page._flush_write()

        page._preset_white()
        page._flush_write()

        self.assertTrue(page._pending_write)

    def test_quick_scene_applies_rgb_and_thermal_profile(self) -> None:
        with TemporaryDirectory() as directory:
            panel = ScenePanel(
                self.client,
                SceneStore(Path(directory) / "scenes.json"),
                self.mutations,
                lambda: None,
                lambda _message: None,
                lambda _message: None,
            )
            panel.update_status(self.client.read_status())

            panel._on_apply_clicked(
                panel._apply_buttons[SceneSlot.WORK],
                SceneSlot.WORK,
            )
            operation, _, _, _ = self.mutations.calls[-1]
            operation()

        self.assertEqual(self.client.profile, "balanced")
        self.assertEqual(self.client.rgb_configuration.brightness_percent, 25)

    def test_window_rejects_a_second_mutation_before_it_reaches_the_helper(self) -> None:
        operation_called = False
        failure_called = False

        def operation() -> dict[str, object]:
            nonlocal operation_called
            operation_called = True
            return {}

        def on_failure() -> None:
            nonlocal failure_called
            failure_called = True

        class BusyWindow:
            _mutations_in_progress = 1

            def __init__(self) -> None:
                self.messages: list[str] = []

            def show_message(self, message: str) -> None:
                self.messages.append(message)

        window = BusyWindow()

        MainWindow.run_mutation(window, operation, "hecho", None, on_failure)

        self.assertFalse(operation_called)
        self.assertTrue(failure_called)
        self.assertEqual(window.messages, ["Espera a que termine el cambio en curso."])


class ConfigurationClarityTests(unittest.TestCase):
    """Choices the interface offers must be choices the hardware accepts."""

    @classmethod
    def setUpClass(cls) -> None:
        if Gdk.Display.get_default() is None:
            raise unittest.SkipTest(
                "Los tests GTK necesitan un display; usa un runner Wayland/X11 virtual."
            )
        Adw.init()

    def setUp(self) -> None:
        self.client = MockControlClient()
        self.mutations = MutationCapture()

    def _home(self) -> HomePage:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return HomePage(
            self.client,
            self.mutations,
            lambda: None,
            telemetry_archive=TelemetryArchive(Path(directory.name) / "telemetry.jsonl"),
        )

    def test_profile_row_does_not_offer_custom_as_a_choice(self) -> None:
        page = self._home()
        model = page._profile_row.get_model()

        offered = [model.get_string(index) for index in range(model.get_n_items())]

        self.assertNotIn("custom", SELECTABLE_PROFILE_VALUES)
        self.assertEqual(len(offered), len(PROFILE_VALUES) - 1)
        self.assertNotIn("Personalizado", offered)

    def test_custom_profile_is_reported_as_state_rather_than_a_selection(self) -> None:
        page = self._home()
        self.client.profile = "custom"

        page.update_status(self.client.read_status())

        self.assertIn("lo activa", page._profile_row.get_subtitle())

    def test_selecting_a_profile_still_maps_to_the_right_value(self) -> None:
        page = self._home()
        page.update_status(self.client.read_status())

        page._profile_row.set_selected(SELECTABLE_PROFILE_VALUES.index("low-power"))
        operation, _message, _success, _failure = self.mutations.calls[-1]
        operation()

        self.assertEqual(self.client.profile, "low-power")

    def test_reset_curve_restores_the_shipped_points_as_a_draft(self) -> None:
        page = FanPage(self.client, self.mutations, lambda: None)
        page.update_status(self.client.read_status())
        temperature_spin, rpm_spin = page._point_spins[0]
        temperature_spin.set_value(99)
        rpm_spin.set_value(5300)

        page._on_reset_curve_clicked(page._reset_curve_button)

        first = DEFAULT_CURVE.points[0]
        self.assertEqual(temperature_spin.get_value_as_int(), first.temperature_c)
        self.assertEqual(rpm_spin.get_value_as_int(), first.rpm)
        self.assertTrue(page._editor_dirty)

    def test_scene_rows_follow_their_automation_switch(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        page = AutomationPage(
            AutomationStore(Path(directory.name) / "automation.json"),
            lambda _message: None,
            lambda _message: None,
        )

        self.assertFalse(page._ac_scene.get_sensitive())
        page._ac_enabled.set_active(True)
        self.assertTrue(page._ac_scene.get_sensitive())
        page._ac_enabled.set_active(False)
        self.assertFalse(page._ac_scene.get_sensitive())


class DoctorPresentationTests(unittest.TestCase):
    """A report the reader cannot scan is not a diagnosis."""

    @classmethod
    def setUpClass(cls) -> None:
        if Gdk.Display.get_default() is None:
            raise unittest.SkipTest(
                "Los tests GTK necesitan un display; usa un runner Wayland/X11 virtual."
            )
        Adw.init()

    def setUp(self) -> None:
        self.messages: list[str] = []
        self.probes = 0

    def _page(self, **overrides: object) -> DoctorPage:
        def reader() -> SystemProbe:
            self.probes += 1
            return _probe(**overrides)

        page = DoctorPage(lambda _message: None, self.messages.append, reader)
        page.update_status(MockControlClient().read_status())
        return page

    def test_each_row_carries_its_own_severity_and_its_remedy(self) -> None:
        page = self._page(active_profile_competitors=("power-profiles-daemon.service",))

        conflict, conflict_icon, _ = page._rows["profile_conflict"]
        kernel, kernel_icon, _ = page._rows["kernel"]

        self.assertIn("status-warm", conflict_icon.get_css_classes())
        self.assertTrue(conflict.get_subtitle())
        self.assertIn("status-stable", kernel_icon.get_css_classes())
        # An acceptable reading needs no instructions underneath it.
        self.assertFalse(kernel.get_subtitle())

    def test_the_environment_is_read_once_per_poll_cycle_not_once_per_poll(self) -> None:
        page = self._page()

        page.update_status(MockControlClient().read_status())
        page.update_status(MockControlClient().read_status())

        self.assertEqual(self.probes, 1)

        page._on_recheck_clicked(Gtk.Button())

        self.assertEqual(self.probes, 2)
        self.assertEqual(len(self.messages), 1)


class LocalizationCoverageTests(unittest.TestCase):
    """No static label may be left showing the source language.

    This pins the contract, not the walker's internals: it catches a button the
    localization pass cannot reach or a catalog entry nobody added.
    """

    @classmethod
    def setUpClass(cls) -> None:
        if Gdk.Display.get_default() is None:
            raise unittest.SkipTest(
                "Los tests GTK necesitan un display; usa un runner Wayland/X11 virtual."
            )
        Adw.init()

    def tearDown(self) -> None:
        set_language("es")

    def test_every_button_on_the_doctor_page_reaches_the_chosen_language(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        set_language("fr")
        page = DoctorPage(
            lambda _message: None,
            lambda _message: None,
            lambda: _probe(),
            UpdateStore(Path(directory.name) / "updates.json"),
            lambda: None,
        )

        localize_widget_tree(page)

        untranslated = [
            label
            for label in _button_labels(page)
            # A label with a French translation must not still read as Spanish.
            if translate(label) != label
        ]
        self.assertEqual(untranslated, [])


def _button_labels(widget: Gtk.Widget) -> list[str]:
    labels = []
    child = widget.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.Button) and child.get_label():
            labels.append(child.get_label())
        labels.extend(_button_labels(child))
        child = child.get_next_sibling()
    return labels


class ReleaseNoticeTests(unittest.TestCase):
    """The notice stays off until asked, and never installs anything."""

    @classmethod
    def setUpClass(cls) -> None:
        if Gdk.Display.get_default() is None:
            raise unittest.SkipTest(
                "Los tests GTK necesitan un display; usa un runner Wayland/X11 virtual."
            )
        Adw.init()

    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = UpdateStore(Path(directory.name) / "updates.json")
        self.errors: list[str] = []

    def _page(self, fetch: Callable[[], str | None]) -> DoctorPage:
        return DoctorPage(
            self.errors.append,
            lambda _message: None,
            lambda: _probe(),
            self.store,
            fetch,
        )

    def test_the_notice_is_off_and_silent_until_the_user_enables_it(self) -> None:
        def forbidden() -> str | None:
            raise AssertionError("El aviso no debía consultar la red.")

        page = self._page(forbidden)

        self.assertFalse(page._update_switch.get_active())
        self.assertFalse(page._releases_button.get_visible())
        self.assertEqual(self.errors, [])

    def test_enabling_the_notice_is_saved_immediately(self) -> None:
        page = self._page(lambda: "0.8.0")

        page._update_switch.set_active(True)

        self.assertTrue(self.store.load().enabled)
        self.assertEqual(self.errors, [])

    def test_an_available_release_offers_the_page_and_nothing_else(self) -> None:
        page = self._page(lambda: "0.8.0")
        configuration = UpdateConfig(enabled=True, last_checked=1, last_seen_version="0.8.0")

        page._finish_update_check(UpdateResult(UpdateState.AVAILABLE, "0.8.0"), configuration)

        self.assertIn("0.8.0", page._update_value.get_label())
        self.assertTrue(page._releases_button.get_visible())
        self.assertEqual(page._releases_url, RELEASES_PAGE_URL)
        self.assertEqual(self.store.load().last_seen_version, "0.8.0")

    def test_a_failed_check_says_so_without_offering_anything(self) -> None:
        page = self._page(lambda: None)

        page._finish_update_check(UpdateResult(UpdateState.UNKNOWN), UpdateConfig(enabled=True))

        self.assertFalse(page._releases_button.get_visible())
        self.assertEqual(self.errors, [])


def _probe(**overrides: object) -> SystemProbe:
    defaults: dict[str, object] = {
        "helper_installed": True,
        "polkit_action_installed": True,
        "loaded_modules": ("lenovo_wmi_gamezone", "lenovo_wmi_other"),
        "fan_service_state": "inactive",
        "fan_service_enabled": "disabled",
        "bios_version": "Q6CN79WW",
    }
    return SystemProbe(**(defaults | overrides))  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
