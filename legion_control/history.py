"""Short dashboard history plus bounded, user-owned telemetry retention."""

from __future__ import annotations

import json
import os
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Final


DEFAULT_HISTORY_SECONDS: Final = 600
DAY_SECONDS: Final = 24 * 60 * 60
DEFAULT_ARCHIVE_SECONDS: Final = 7 * DAY_SECONDS
ARCHIVE_SAMPLE_INTERVAL_SECONDS: Final = 30
MAX_ARCHIVE_BYTES: Final = 2 * 1024 * 1024
MAX_ARCHIVE_RECORDS: Final = 40_000
MAX_EVENT_LABEL_LENGTH: Final = 180


@dataclass(frozen=True, slots=True)
class TelemetrySample:
    timestamp: float
    cpu_temperature_c: int | None
    gpu_temperature_c: int | None
    fan1_rpm: int | None
    fan2_rpm: int | None


@dataclass(frozen=True, slots=True)
class TelemetryEvent:
    timestamp: float
    label: str


class TelemetryHistory:
    def __init__(
        self,
        max_age_seconds: int = DEFAULT_HISTORY_SECONDS,
        *,
        samples: tuple[TelemetrySample, ...] = (),
        events: tuple[TelemetryEvent, ...] = (),
    ) -> None:
        if max_age_seconds <= 0:
            raise ValueError("La ventana histórica debe ser positiva.")
        self._max_age_seconds = max_age_seconds
        self._samples: deque[TelemetrySample] = deque(samples)
        self._events: deque[TelemetryEvent] = deque(events)
        latest_timestamp = max(
            (item.timestamp for item in (*samples, *events)),
            default=None,
        )
        if latest_timestamp is not None:
            self._prune(latest_timestamp)

    @property
    def max_age_seconds(self) -> int:
        return self._max_age_seconds

    @property
    def samples(self) -> tuple[TelemetrySample, ...]:
        return tuple(self._samples)

    @property
    def events(self) -> tuple[TelemetryEvent, ...]:
        return tuple(self._events)

    def replace(
        self,
        *,
        max_age_seconds: int,
        samples: tuple[TelemetrySample, ...],
        events: tuple[TelemetryEvent, ...],
    ) -> None:
        if max_age_seconds <= 0:
            raise ValueError("La ventana histórica debe ser positiva.")
        self._max_age_seconds = max_age_seconds
        self._samples = deque(samples)
        self._events = deque(events)
        latest_timestamp = max(
            (item.timestamp for item in (*samples, *events)),
            default=None,
        )
        if latest_timestamp is not None:
            self._prune(latest_timestamp)

    def append_status(
        self,
        status: dict[str, object],
        *,
        timestamp: float | None = None,
    ) -> None:
        self.append_sample(
            TelemetrySample(
                timestamp=time.time() if timestamp is None else timestamp,
                cpu_temperature_c=_optional_integer(status.get("cpu_temperature_c")),
                gpu_temperature_c=_optional_integer(status.get("gpu_temperature_c")),
                fan1_rpm=_optional_integer(status.get("fan1_rpm")),
                fan2_rpm=_optional_integer(status.get("fan2_rpm")),
            )
        )

    def append_sample(self, sample: TelemetrySample) -> None:
        if not isinstance(sample, TelemetrySample):
            raise ValueError("La muestra térmica no es válida.")
        if all(
            value is None
            for value in (
                sample.cpu_temperature_c,
                sample.gpu_temperature_c,
                sample.fan1_rpm,
                sample.fan2_rpm,
            )
        ):
            return
        self._samples.append(sample)
        self._prune(sample.timestamp)

    def append_event(self, event: TelemetryEvent) -> None:
        if not isinstance(event, TelemetryEvent) or not event.label:
            raise ValueError("El evento térmico no es válido.")
        self._events.append(event)
        self._prune(event.timestamp)

    def _prune(self, current_timestamp: float) -> None:
        oldest_allowed = current_timestamp - self._max_age_seconds
        while self._samples and self._samples[0].timestamp < oldest_allowed:
            self._samples.popleft()
        while self._events and self._events[0].timestamp < oldest_allowed:
            self._events.popleft()


@dataclass(slots=True)
class TelemetryArchive:
    """Append-only local archive, sampled to limit write volume and wear."""

    path: Path
    max_age_seconds: int = DEFAULT_ARCHIVE_SECONDS
    sample_interval_seconds: int = ARCHIVE_SAMPLE_INTERVAL_SECONDS
    _last_sample_timestamp: float | None = None
    _last_compaction_timestamp: float | None = None

    def __post_init__(self) -> None:
        if self.max_age_seconds <= 0 or self.sample_interval_seconds <= 0:
            raise ValueError("La retención y el intervalo deben ser positivos.")

    def append_status(
        self,
        status: dict[str, object],
        *,
        timestamp: float | None = None,
    ) -> TelemetrySample | None:
        now = time.time() if timestamp is None else timestamp
        if (
            self._last_sample_timestamp is not None
            and now - self._last_sample_timestamp < self.sample_interval_seconds
        ):
            return None
        sample = TelemetrySample(
            timestamp=now,
            cpu_temperature_c=_optional_integer(status.get("cpu_temperature_c")),
            gpu_temperature_c=_optional_integer(status.get("gpu_temperature_c")),
            fan1_rpm=_optional_integer(status.get("fan1_rpm")),
            fan2_rpm=_optional_integer(status.get("fan2_rpm")),
        )
        if all(
            value is None
            for value in (
                sample.cpu_temperature_c,
                sample.gpu_temperature_c,
                sample.fan1_rpm,
                sample.fan2_rpm,
            )
        ):
            return
        self._append_record(_sample_record(sample))
        self._last_sample_timestamp = now
        self._compact_if_needed(now)
        return sample

    def append_event(self, label: str, *, timestamp: float | None = None) -> None:
        if not isinstance(label, str) or not label.strip():
            raise ValueError("El evento necesita una etiqueta.")
        if len(label) > MAX_EVENT_LABEL_LENGTH:
            raise ValueError("La etiqueta de evento es demasiado larga.")
        now = time.time() if timestamp is None else timestamp
        self._append_record({"kind": "event", "timestamp": now, "label": label})
        self._compact_if_needed(now)

    def load(
        self,
        *,
        max_age_seconds: int | None = None,
        timestamp: float | None = None,
    ) -> tuple[tuple[TelemetrySample, ...], tuple[TelemetryEvent, ...]]:
        age = self.max_age_seconds if max_age_seconds is None else max_age_seconds
        if age <= 0:
            raise ValueError("La ventana histórica debe ser positiva.")
        now = time.time() if timestamp is None else timestamp
        if not self.path.exists():
            return (), ()
        minimum = now - age
        # Read line by line and keep only the newest retained records, so an
        # oversized file degrades to a shorter history instead of no history.
        recent_samples: deque[TelemetrySample] = deque(maxlen=MAX_ARCHIVE_RECORDS)
        recent_events: deque[TelemetryEvent] = deque(maxlen=MAX_ARCHIVE_RECORDS)
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    record = _record_from_line(line)
                    if record is None:
                        continue
                    item = _archive_item_from_record(record)
                    if (
                        item is None
                        or item.timestamp < minimum
                        or item.timestamp > now + DAY_SECONDS
                    ):
                        continue
                    if isinstance(item, TelemetrySample):
                        recent_samples.append(item)
                    else:
                        recent_events.append(item)
        except (OSError, UnicodeDecodeError):
            return (), ()
        samples = sorted(recent_samples, key=lambda item: item.timestamp)
        events = sorted(recent_events, key=lambda item: item.timestamp)
        if samples:
            self._last_sample_timestamp = samples[-1].timestamp
        return tuple(samples), tuple(events)

    def export_csv(
        self,
        destination: Path,
        *,
        timestamp: float | None = None,
    ) -> None:
        samples, events = self.load(timestamp=timestamp)
        rows = ["kind,timestamp,cpu_temperature_c,gpu_temperature_c,fan1_rpm,fan2_rpm,label"]
        rows.extend(_sample_csv_row(sample) for sample in samples)
        rows.extend(_event_csv_row(event) for event in events)
        destination.write_text("\n".join(rows) + "\n", encoding="utf-8")

    def _append_record(self, record: dict[str, object]) -> None:
        payload = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        encoded = payload.encode("utf-8")
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(
            self.path,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o600,
        )
        try:
            written = os.write(descriptor, encoded)
            if written != len(encoded):
                raise OSError("Escritura incompleta de historial.")
        finally:
            os.close(descriptor)

    def _compact_if_needed(self, now: float) -> None:
        if self._last_compaction_timestamp is not None and (
            now - self._last_compaction_timestamp < DAY_SECONDS
        ):
            return
        try:
            size = self.path.stat().st_size
        except OSError:
            return
        if size <= MAX_ARCHIVE_BYTES and self._last_compaction_timestamp is not None:
            return
        samples, events = self.load(timestamp=now)
        records = [
            *(_sample_record(sample) for sample in samples),
            *(
                {"kind": "event", "timestamp": event.timestamp, "label": event.label}
                for event in events
            ),
        ]
        records.sort(key=lambda item: float(item["timestamp"]))
        payload = _payload_within_budget(records)
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=".telemetry-",
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary.flush()
            temporary_path = Path(temporary.name)
        try:
            temporary_path.chmod(0o600)
            os.replace(temporary_path, self.path)
        finally:
            temporary_path.unlink(missing_ok=True)
        self._last_compaction_timestamp = now


def default_telemetry_path() -> Path:
    state_home = os.environ.get("XDG_STATE_HOME")
    parent = Path(state_home) if state_home else Path.home() / ".local/state"
    return parent / "legion-control/telemetry.jsonl"


def _payload_within_budget(records: list[dict[str, object]]) -> str:
    """Serialize the newest records that still fit inside the size budget."""

    lines = [
        json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n" for record in records
    ]
    total = sum(len(line.encode("utf-8")) for line in lines)
    first = 0
    while first < len(lines) and total > MAX_ARCHIVE_BYTES:
        total -= len(lines[first].encode("utf-8"))
        first += 1
    return "".join(lines[first:])


def _sample_record(sample: TelemetrySample) -> dict[str, object]:
    return {
        "kind": "sample",
        "timestamp": sample.timestamp,
        "cpu_temperature_c": sample.cpu_temperature_c,
        "gpu_temperature_c": sample.gpu_temperature_c,
        "fan1_rpm": sample.fan1_rpm,
        "fan2_rpm": sample.fan2_rpm,
    }


def _record_from_line(line: str) -> dict[str, object] | None:
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    return record if isinstance(record, dict) else None


def _archive_item_from_record(
    record: dict[str, object],
) -> TelemetrySample | TelemetryEvent | None:
    timestamp = record.get("timestamp")
    # Two `is` comparisons rather than a set: they keep bools out and let a type
    # checker narrow the value before it is converted.
    if type(timestamp) is not int and type(timestamp) is not float:
        return None
    if record.get("kind") == "sample":
        return TelemetrySample(
            timestamp=float(timestamp),
            cpu_temperature_c=_optional_integer(record.get("cpu_temperature_c")),
            gpu_temperature_c=_optional_integer(record.get("gpu_temperature_c")),
            fan1_rpm=_optional_integer(record.get("fan1_rpm")),
            fan2_rpm=_optional_integer(record.get("fan2_rpm")),
        )
    label = record.get("label")
    if (
        record.get("kind") == "event"
        and isinstance(label, str)
        and 0 < len(label) <= MAX_EVENT_LABEL_LENGTH
    ):
        return TelemetryEvent(float(timestamp), label)
    return None


def _sample_csv_row(sample: TelemetrySample) -> str:
    values = (
        "sample",
        str(sample.timestamp),
        _csv_integer(sample.cpu_temperature_c),
        _csv_integer(sample.gpu_temperature_c),
        _csv_integer(sample.fan1_rpm),
        _csv_integer(sample.fan2_rpm),
        "",
    )
    return ",".join(values)


def _event_csv_row(event: TelemetryEvent) -> str:
    label = event.label.replace('"', '""')
    return f'event,{event.timestamp},,,,,"{label}"'


def _csv_integer(value: int | None) -> str:
    return "" if value is None else str(value)


def _optional_integer(value: object) -> int | None:
    return value if type(value) is int else None
