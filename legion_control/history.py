"""Short in-memory telemetry history for the native dashboard."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Final


DEFAULT_HISTORY_SECONDS: Final = 600


@dataclass(frozen=True, slots=True)
class TelemetrySample:
    timestamp: float
    cpu_temperature_c: int | None
    gpu_temperature_c: int | None
    fan1_rpm: int | None
    fan2_rpm: int | None


class TelemetryHistory:
    def __init__(self, max_age_seconds: int = DEFAULT_HISTORY_SECONDS) -> None:
        if max_age_seconds <= 0:
            raise ValueError("La ventana histórica debe ser positiva.")
        self._max_age_seconds = max_age_seconds
        self._samples: deque[TelemetrySample] = deque()

    @property
    def max_age_seconds(self) -> int:
        return self._max_age_seconds

    @property
    def samples(self) -> tuple[TelemetrySample, ...]:
        return tuple(self._samples)

    def append_status(
        self,
        status: dict[str, object],
        *,
        timestamp: float | None = None,
    ) -> None:
        sample = TelemetrySample(
            timestamp=time.monotonic() if timestamp is None else timestamp,
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
        self._samples.append(sample)
        self._prune(sample.timestamp)

    def _prune(self, current_timestamp: float) -> None:
        oldest_allowed = current_timestamp - self._max_age_seconds
        while self._samples and self._samples[0].timestamp < oldest_allowed:
            self._samples.popleft()


def _optional_integer(value: object) -> int | None:
    return value if type(value) is int else None
