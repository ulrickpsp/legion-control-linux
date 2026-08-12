from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from legion_control.updates import (
    CHECK_INTERVAL_SECONDS,
    MAX_RESPONSE_BYTES,
    RELEASES_API_URL,
    UpdateConfig,
    UpdateState,
    UpdateStore,
    check_for_update,
    parse_version,
    version_from_document,
)


class ReleaseNoticeTests(unittest.TestCase):
    """The notice reads a version. It never downloads, installs, or executes."""

    def test_a_disabled_notice_never_reaches_the_network(self) -> None:
        result, configuration = check_for_update(
            UpdateConfig(enabled=False),
            current_version="0.7.0",
            fetch=_forbidden_fetch,
        )

        self.assertEqual(result.state, UpdateState.DISABLED)
        self.assertEqual(configuration, UpdateConfig(enabled=False))

    def test_a_newer_release_is_reported_with_its_version(self) -> None:
        result, configuration = check_for_update(
            UpdateConfig(enabled=True),
            current_version="0.7.0",
            fetch=lambda: "0.8.0",
            now=1000,
        )

        self.assertEqual(result.state, UpdateState.AVAILABLE)
        self.assertEqual(result.latest_version, "0.8.0")
        self.assertEqual(configuration.last_seen_version, "0.8.0")
        self.assertEqual(configuration.last_checked, 1000)

    def test_the_installed_version_is_reported_as_current(self) -> None:
        result, _ = check_for_update(
            UpdateConfig(enabled=True),
            current_version="0.8.0",
            fetch=lambda: "0.8.0",
            now=1000,
        )

        self.assertEqual(result.state, UpdateState.CURRENT)

    def test_an_older_published_version_is_not_an_update(self) -> None:
        result, _ = check_for_update(
            UpdateConfig(enabled=True),
            current_version="0.9.0",
            fetch=lambda: "0.8.0",
            now=1000,
        )

        self.assertEqual(result.state, UpdateState.CURRENT)

    def test_a_fresh_answer_is_reused_instead_of_asking_again(self) -> None:
        stored = UpdateConfig(enabled=True, last_checked=1000, last_seen_version="0.8.0")

        result, configuration = check_for_update(
            stored,
            current_version="0.7.0",
            fetch=_forbidden_fetch,
            now=1000 + CHECK_INTERVAL_SECONDS - 1,
        )

        self.assertEqual(result.state, UpdateState.AVAILABLE)
        self.assertEqual(configuration, stored)

    def test_a_stale_answer_is_asked_again(self) -> None:
        stored = UpdateConfig(enabled=True, last_checked=1000, last_seen_version="0.8.0")

        _, configuration = check_for_update(
            stored,
            current_version="0.7.0",
            fetch=lambda: "0.9.0",
            now=1000 + CHECK_INTERVAL_SECONDS,
        )

        self.assertEqual(configuration.last_seen_version, "0.9.0")

    def test_a_failed_request_keeps_the_stored_state_untouched(self) -> None:
        stored = UpdateConfig(enabled=True, last_checked=10, last_seen_version="0.8.0")

        result, configuration = check_for_update(
            stored,
            current_version="0.7.0",
            fetch=lambda: None,
            now=10 + CHECK_INTERVAL_SECONDS,
        )

        self.assertEqual(result.state, UpdateState.UNKNOWN)
        self.assertEqual(configuration, stored)


class ReleaseDocumentTests(unittest.TestCase):
    """The answer is untrusted input: only a plain version tag is accepted."""

    def test_a_tag_is_accepted_with_or_without_its_prefix(self) -> None:
        self.assertEqual(version_from_document([{"tag_name": "v0.8.0"}]), "0.8.0")
        self.assertEqual(version_from_document([{"tag_name": "0.8.0"}]), "0.8.0")

    def test_a_pre_release_still_counts_because_the_project_ships_only_those(self) -> None:
        listing = [{"tag_name": "v0.8.0", "prerelease": True, "draft": False}]

        self.assertEqual(version_from_document(listing), "0.8.0")

    def test_a_draft_is_unpublished_and_is_skipped(self) -> None:
        listing = [
            {"tag_name": "v0.9.0", "draft": True},
            {"tag_name": "v0.8.0", "draft": False},
        ]

        self.assertEqual(version_from_document(listing), "0.8.0")

    def test_the_highest_version_wins_regardless_of_listing_order(self) -> None:
        listing = [
            {"tag_name": "v0.6.0"},
            {"tag_name": "v0.9.0"},
            {"tag_name": "v0.7.0"},
        ]

        self.assertEqual(version_from_document(listing), "0.9.0")

    def test_unusable_entries_are_skipped_without_losing_the_usable_one(self) -> None:
        listing = [
            {"tag_name": "latest"},
            {"tag_name": "0.8.0; rm -rf /"},
            {"tag_name": "1" * 64},
            {"tag_name": 8},
            "v9.9.9",
            {},
            {"tag_name": "v0.8.0"},
        ]

        self.assertEqual(version_from_document(listing), "0.8.0")

    def test_anything_that_is_not_a_release_listing_is_refused(self) -> None:
        for document in ({"tag_name": "v0.8.0"}, [], "0.8.0", None, [{"tag_name": "latest"}]):
            self.assertIsNone(version_from_document(document), document)

    def test_version_parsing_refuses_unbounded_input(self) -> None:
        self.assertIsNone(parse_version("1.2.3.4.5"))
        self.assertIsNone(parse_version("1234567"))
        self.assertIsNone(parse_version(""))
        self.assertEqual(parse_version("0.7.0"), (0, 7, 0))

    def test_the_endpoint_is_https_and_the_response_is_bounded(self) -> None:
        self.assertTrue(RELEASES_API_URL.startswith("https://"))
        self.assertLessEqual(MAX_RESPONSE_BYTES, 1 << 20)


class UpdateStoreTests(unittest.TestCase):
    def test_configuration_survives_a_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = UpdateStore(Path(directory) / "updates.json")
            configuration = UpdateConfig(enabled=True, last_checked=42, last_seen_version="0.8.0")

            store.save(configuration)

            self.assertEqual(store.load(), configuration)
            self.assertEqual(store.path.stat().st_mode & 0o777, 0o600)

    def test_a_missing_file_means_the_notice_is_off(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = UpdateStore(Path(directory) / "absent.json")

            self.assertEqual(store.load(), UpdateConfig())

    def test_an_unexpected_document_is_refused_rather_than_guessed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "updates.json"
            path.write_text(json.dumps({"enabled": True}), encoding="utf-8")

            with self.assertRaises(ValueError):
                UpdateStore(path).load()

    def test_an_oversized_version_string_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            UpdateConfig(enabled=True, last_seen_version="9" * 64)


def _forbidden_fetch() -> str | None:
    raise AssertionError("El aviso de versión no debía consultar la red.")


if __name__ == "__main__":
    unittest.main()
