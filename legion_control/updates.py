"""Opt-in release notice.

The application never downloads, installs, or executes anything from the
network.  When the user explicitly enables it, one HTTPS request asks the
project's release page which version is current and the answer is shown next to
the installed one.  Everything else about updating stays with the package
manager, which already verifies what it installs.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Final

from legion_control import __version__


# The list endpoint rather than /releases/latest: every release of this project
# is a pre-release while it is alpha, and /releases/latest omits those entirely.
RELEASES_API_URL: Final = (
    "https://api.github.com/repos/ulrickpsp/legion-control-linux/releases?per_page=5"
)
RELEASES_PAGE_URL: Final = "https://github.com/ulrickpsp/legion-control-linux/releases"
# Five release entries with their notes and assets; anything larger is not that.
MAX_RESPONSE_BYTES: Final = 262144
REQUEST_TIMEOUT_SECONDS: Final = 8
# One answer a day is enough for a notice, and it keeps the request rare.
CHECK_INTERVAL_SECONDS: Final = 86400
UPDATE_CONFIG_VERSION: Final = 1
MAX_UPDATE_CONFIG_BYTES: Final = 2048
MAX_VERSION_LENGTH: Final = 32
EXPECTED_UPDATE_KEYS: Final = frozenset({"version", "enabled", "last_checked", "last_seen_version"})

ReleaseFetcher = Callable[[], str | None]


class UpdateState(StrEnum):
    DISABLED = "disabled"
    UNKNOWN = "unknown"
    CURRENT = "current"
    AVAILABLE = "available"


@dataclass(frozen=True, slots=True)
class UpdateResult:
    state: UpdateState
    latest_version: str = ""
    url: str = RELEASES_PAGE_URL


@dataclass(frozen=True, slots=True)
class UpdateConfig:
    enabled: bool = False
    last_checked: int = 0
    last_seen_version: str = ""

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ValueError("El aviso de versión debe ser booleano.")
        if type(self.last_checked) is not int or self.last_checked < 0:
            raise ValueError("La marca de tiempo de comprobación no es válida.")
        if type(self.last_seen_version) is not str:
            raise ValueError("La última versión vista no es texto.")
        if len(self.last_seen_version) > MAX_VERSION_LENGTH:
            raise ValueError("La última versión vista es demasiado larga.")

    def to_dict(self) -> dict[str, object]:
        return {
            "version": UPDATE_CONFIG_VERSION,
            "enabled": self.enabled,
            "last_checked": self.last_checked,
            "last_seen_version": self.last_seen_version,
        }


@dataclass(slots=True)
class UpdateStore:
    path: Path

    def load(self) -> UpdateConfig:
        if not self.path.exists():
            return UpdateConfig()
        if self.path.stat().st_size > MAX_UPDATE_CONFIG_BYTES:
            raise ValueError("La configuración de avisos es demasiado grande.")
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"JSON de avisos inválido: {error.msg}.") from error
        return update_config_from_document(document)

    def save(self, configuration: UpdateConfig) -> None:
        payload = (
            json.dumps(
                configuration.to_dict(),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        )
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=".updates-",
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        try:
            temporary_path.chmod(0o600)
            os.replace(temporary_path, self.path)
            _sync_directory(self.path.parent)
        finally:
            temporary_path.unlink(missing_ok=True)


def check_for_update(
    configuration: UpdateConfig,
    *,
    current_version: str = __version__,
    fetch: ReleaseFetcher | None = None,
    now: int | None = None,
) -> tuple[UpdateResult, UpdateConfig]:
    """Answer from the stored result, and ask the network only when it is stale.

    Returns the notice to show and the configuration to persist.  The caller
    decides when to save, so a failed request never rewrites the stored state.
    """

    if not configuration.enabled:
        return UpdateResult(UpdateState.DISABLED), configuration
    moment = now if now is not None else int(time.time())
    fresh = moment - configuration.last_checked < CHECK_INTERVAL_SECONDS
    if fresh and configuration.last_seen_version:
        return _compare(configuration.last_seen_version, current_version), configuration
    latest = (fetch or fetch_latest_version)()
    if latest is None:
        return UpdateResult(UpdateState.UNKNOWN), configuration
    updated = replace(configuration, last_checked=moment, last_seen_version=latest)
    return _compare(latest, current_version), updated


def fetch_latest_version() -> str | None:
    """Read the current release tag over HTTPS, or nothing at all.

    Every failure is an answer of "unknown".  A release notice must never take
    the application down, and it must never become a reason to retry loudly.
    """

    request = urllib.request.Request(
        RELEASES_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            # GitHub rejects requests without one; it carries no identifier.
            "User-Agent": f"legion-control/{__version__}",
        },
    )
    if request.type != "https":
        return None
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            if urllib.parse.urlparse(response.url).scheme != "https":
                return None
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if len(payload) > MAX_RESPONSE_BYTES:
        return None
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return version_from_document(document)


def version_from_document(document: Any) -> str | None:
    """Pick the highest published version from an untrusted release listing.

    Drafts are unpublished, so they are skipped; pre-releases are not, and this
    project has shipped nothing else.  Ordering is decided here rather than
    trusting the order the listing arrives in.
    """

    if not isinstance(document, list):
        return None
    published = [
        version for entry in document if (version := _published_version(entry)) is not None
    ]
    if not published:
        return None
    return max(published, key=lambda version: parse_version(version) or ())


def _published_version(entry: Any) -> str | None:
    if not isinstance(entry, dict) or entry.get("draft") is True:
        return None
    tag = entry.get("tag_name")
    if not isinstance(tag, str) or len(tag) > MAX_VERSION_LENGTH:
        return None
    normalized = tag[1:] if tag.startswith("v") else tag
    return normalized if parse_version(normalized) is not None else None


def parse_version(text: str) -> tuple[int, ...] | None:
    parts = text.split(".")
    if not 1 <= len(parts) <= 4:
        return None
    if not all(part.isdigit() and len(part) <= 6 for part in parts):
        return None
    return tuple(int(part) for part in parts)


def update_config_from_document(document: Any) -> UpdateConfig:
    if not isinstance(document, dict) or frozenset(document) != EXPECTED_UPDATE_KEYS:
        raise ValueError("El aviso de versión contiene claves incorrectas.")
    if document["version"] != UPDATE_CONFIG_VERSION:
        raise ValueError(f"Solo se admiten avisos versión {UPDATE_CONFIG_VERSION}.")
    try:
        return UpdateConfig(
            enabled=document["enabled"],
            last_checked=document["last_checked"],
            last_seen_version=document["last_seen_version"],
        )
    except (TypeError, ValueError) as error:
        raise ValueError("El aviso de versión contiene valores inválidos.") from error


def default_update_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    parent = Path(config_home) if config_home else Path.home() / ".config"
    return parent / "legion-control/updates.json"


def _compare(latest: str, current: str) -> UpdateResult:
    published = parse_version(latest)
    installed = parse_version(current)
    if published is None or installed is None:
        return UpdateResult(UpdateState.UNKNOWN)
    if published > installed:
        return UpdateResult(UpdateState.AVAILABLE, latest)
    return UpdateResult(UpdateState.CURRENT, latest)


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
