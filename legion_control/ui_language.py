"""Language preference page for the GTK interface."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gtk  # noqa: E402

from legion_control.i18n import (  # noqa: E402
    LANGUAGE_NAMES,
    LANGUAGES,
    LanguageStore,
    active_language,
    translate,
)


class LanguagePage(Adw.PreferencesPage):
    """Stores the next-launch language; rebuilding GTK live is error-prone."""

    def __init__(
        self,
        store: LanguageStore,
        show_message: Callable[[str], None],
        show_error: Callable[[str], None],
        request_restart: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.add_css_class("control-page")
        self.set_title(translate("Idioma"))
        self.set_icon_name("preferences-desktop-locale-symbolic")
        self._store = store
        self._show_message = show_message
        self._show_error = show_error
        self._request_restart = request_restart
        self._refreshing = True

        group = Adw.PreferencesGroup()
        group.set_title(translate("Idioma de la interfaz"))
        group.set_description(
            translate("El idioma elegido se aplicará al abrir Legion Control de nuevo.")
        )
        self._language = Adw.ComboRow()
        self._language.set_title(translate("Idioma"))
        self._language.set_model(
            Gtk.StringList.new(tuple(LANGUAGE_NAMES[code] for code in LANGUAGES))
        )
        self._language.set_selected(LANGUAGES.index(active_language()))
        self._language.connect("notify::selected", self._on_language_changed)
        group.add(self._language)

        # Offered only once the choice is saved, so it never invites a restart
        # that would change nothing.
        self._restart_row = Adw.ActionRow()
        self._restart_row.set_title(translate("Aplicar ahora"))
        self._restart_row.set_subtitle(
            translate("Reinicia Legion Control · se pierden los cambios sin aplicar")
        )
        self._restart_button = Gtk.Button(label=translate("Reiniciar ahora"))
        self._restart_button.add_css_class("suggested-action")
        self._restart_button.set_valign(Gtk.Align.CENTER)
        self._restart_button.connect("clicked", self._on_restart_clicked)
        self._restart_row.add_suffix(self._restart_button)
        self._restart_row.set_activatable_widget(self._restart_button)
        self._restart_row.set_visible(False)
        group.add(self._restart_row)

        self.add(group)
        self._refreshing = False

    def _on_language_changed(
        self,
        row: Adw.ComboRow,
        _parameter: object,
    ) -> None:
        if self._refreshing:
            return
        selected = row.get_selected()
        if selected >= len(LANGUAGES):
            return
        try:
            self._store.save(LANGUAGES[selected])
        except OSError as error:
            self._show_error(str(error))
            return
        self._restart_row.set_visible(self._request_restart is not None)
        self._show_message(translate("Idioma guardado. Reinicia Legion Control para aplicarlo."))

    def _on_restart_clicked(self, _button: Gtk.Button) -> None:
        if self._request_restart is not None:
            self._request_restart()
