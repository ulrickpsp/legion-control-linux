from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from legion_control.i18n import (
    LANGUAGES,
    LanguageStore,
    active_language,
    configure_startup_language,
    normalize_language,
    set_language,
    translate,
)


class InternationalizationTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_language("es")

    def test_all_requested_languages_translate_interface_text(self) -> None:
        expected = {
            "en": "Fans",
            "es": "Ventilación",
            "fr": "Ventilation",
            "zh": "风扇",
            "ru": "Вентиляторы",
        }
        self.assertEqual(set(LANGUAGES), set(expected))
        for language, label in expected.items():
            set_language(language)
            self.assertEqual(translate("Ventilación"), label)

    def test_normalizes_system_locale_codes(self) -> None:
        self.assertEqual(normalize_language("fr_FR.UTF-8"), "fr")
        self.assertEqual(normalize_language("zh-CN"), "zh")
        self.assertEqual(normalize_language("ru_RU"), "ru")
        self.assertIsNone(normalize_language("de_DE"))

    def test_saved_language_is_used_when_no_environment_override_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "language.json"
            store = LanguageStore(path)
            store.save("ru")
            self.assertEqual(store.load(), "ru")
            with patch("legion_control.i18n.LanguageStore", return_value=store):
                with patch.dict(os.environ, {"LEGION_CONTROL_LANGUAGE": ""}):
                    configure_startup_language()
            self.assertEqual(active_language(), "ru")

    def test_environment_override_wins_over_saved_language(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = LanguageStore(Path(directory) / "language.json")
            store.save("fr")
            with patch("legion_control.i18n.LanguageStore", return_value=store):
                with patch.dict(os.environ, {"LEGION_CONTROL_LANGUAGE": "zh_CN"}):
                    configure_startup_language()
            self.assertEqual(active_language(), "zh")


if __name__ == "__main__":
    unittest.main()
