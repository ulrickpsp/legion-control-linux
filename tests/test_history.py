from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from legion_control.history import (
    MAX_ARCHIVE_BYTES,
    TelemetryArchive,
    TelemetryEvent,
    TelemetryHistory,
)


_NOW = 1_700_000_000.0


class TelemetryHistoryTests(unittest.TestCase):
    def test_keeps_only_the_requested_time_window(self) -> None:
        history = TelemetryHistory(max_age_seconds=600)
        history.append_status(_status(50, 2000), timestamp=100)
        history.append_status(_status(60, 3000), timestamp=500)
        history.append_status(_status(70, 4000), timestamp=701)

        samples = history.samples

        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[0].cpu_temperature_c, 60)
        self.assertEqual(samples[-1].fan1_rpm, 4000)

    def test_ignores_status_without_thermal_or_fan_values(self) -> None:
        history = TelemetryHistory(max_age_seconds=600)
        history.append_status({}, timestamp=100)
        self.assertEqual(history.samples, ())

    def test_archive_samples_at_a_bounded_interval_and_exports_events(self) -> None:
        with TemporaryDirectory() as directory:
            archive = TelemetryArchive(
                Path(directory) / "telemetry.jsonl",
                sample_interval_seconds=30,
            )
            archive.append_status(_status(50, 2000), timestamp=100)
            archive.append_status(_status(55, 2200), timestamp=110)
            archive.append_status(_status(60, 2400), timestamp=130)
            archive.append_event("Escena Trabajo aplicada.", timestamp=131)

            samples, events = archive.load(timestamp=132)
            destination = Path(directory) / "telemetry.csv"
            archive.export_csv(destination, timestamp=132)

            self.assertEqual([sample.cpu_temperature_c for sample in samples], [50, 60])
            self.assertEqual(events, (TelemetryEvent(131, "Escena Trabajo aplicada."),))
            self.assertIn("Escena Trabajo aplicada.", destination.read_text(encoding="utf-8"))

    def test_reads_an_archive_larger_than_the_size_budget(self) -> None:
        with TemporaryDirectory() as directory:
            path = _oversized_archive(Path(directory) / "telemetry.jsonl")
            archive = TelemetryArchive(path)

            samples, _events = archive.load(timestamp=_NOW)

            self.assertGreater(path.stat().st_size, MAX_ARCHIVE_BYTES)
            self.assertGreater(len(samples), 1000)

    def test_compaction_bounds_the_file_without_discarding_the_history(self) -> None:
        with TemporaryDirectory() as directory:
            path = _oversized_archive(Path(directory) / "telemetry.jsonl")
            archive = TelemetryArchive(path)

            archive.append_status(_status(61, 2100), timestamp=_NOW + 60)
            samples, _events = archive.load(timestamp=_NOW + 60)

            self.assertLessEqual(path.stat().st_size, MAX_ARCHIVE_BYTES)
            self.assertGreater(len(samples), 1000)
            self.assertEqual(samples[-1].cpu_temperature_c, 61)


def _oversized_archive(path: Path) -> Path:
    """Write a still-retained archive that is deliberately over the size budget."""

    record = {
        "kind": "sample",
        "timestamp": _NOW,
        "cpu_temperature_c": 60,
        "gpu_temperature_c": 50,
        "fan1_rpm": 2000,
        "fan2_rpm": 2000,
    }
    line_length = len(json.dumps(record, separators=(",", ":"))) + 1
    with path.open("w", encoding="utf-8") as handle:
        for offset in range(MAX_ARCHIVE_BYTES // line_length + 500):
            handle.write(
                json.dumps({**record, "timestamp": _NOW - offset}, separators=(",", ":")) + "\n"
            )
    return path


def _status(temperature_c: int, rpm: int) -> dict[str, object]:
    return {
        "cpu_temperature_c": temperature_c,
        "gpu_temperature_c": temperature_c - 5,
        "fan1_rpm": rpm,
        "fan2_rpm": rpm,
    }


if __name__ == "__main__":
    unittest.main()
