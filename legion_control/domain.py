"""Thermal-control rules with no dependency on Linux or GTK."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from statistics import median_high
from typing import Final


EMERGENCY_FULL_SPEED_C: Final = 92
EMERGENCY_FIRMWARE_CONTROL_C: Final = 98
TEMPERATURE_FILTER_SAMPLES: Final = 3
DOWNWARD_HYSTERESIS_C: Final = 3
DOWNWARD_CONFIRMATION_SAMPLES: Final = 3
MAX_DOWNWARD_STEP_COUNT: Final = 3


class DomainError(ValueError):
    """A requested thermal configuration violates a domain invariant."""


class TemperatureUnavailableError(RuntimeError):
    """No trustworthy temperature is available for manual fan control."""


class CriticalTemperatureError(RuntimeError):
    """Temperature is high enough that firmware must regain fan control."""


class FanMode(StrEnum):
    AUTO = "auto"
    FIXED = "fixed"
    CURVE = "curve"


@dataclass(frozen=True, slots=True)
class FanBounds:
    """Validated physical fan limits and accepted target granularity."""

    minimum_rpm: int
    maximum_rpm: int
    step_rpm: int = 100

    def __post_init__(self) -> None:
        if self.minimum_rpm <= 0:
            raise DomainError("La RPM mínima debe ser positiva.")
        if self.maximum_rpm <= self.minimum_rpm:
            raise DomainError("La RPM máxima debe superar la mínima.")
        if self.step_rpm <= 0:
            raise DomainError("El paso de RPM debe ser positivo.")

    def quantize(self, rpm: int) -> int:
        """Clamp an RPM target to hardware bounds and granularity."""
        clamped = min(max(rpm, self.minimum_rpm), self.maximum_rpm)
        steps = round((clamped - self.minimum_rpm) / self.step_rpm)
        quantized = self.minimum_rpm + steps * self.step_rpm
        return min(max(quantized, self.minimum_rpm), self.maximum_rpm)


@dataclass(frozen=True, slots=True)
class CurvePoint:
    temperature_c: int
    rpm: int

    def __post_init__(self) -> None:
        if not 20 <= self.temperature_c <= 100:
            raise DomainError("Cada temperatura debe estar entre 20 y 100 °C.")
        if self.rpm <= 0:
            raise DomainError("Cada objetivo debe tener RPM positivas.")


@dataclass(frozen=True, slots=True)
class FanCurve:
    """An immutable monotonic fan curve."""

    points: tuple[CurvePoint, ...]

    def __post_init__(self) -> None:
        if not 2 <= len(self.points) <= 10:
            raise DomainError("La curva debe contener entre 2 y 10 puntos.")
        temperatures = [point.temperature_c for point in self.points]
        speeds = [point.rpm for point in self.points]
        if temperatures != sorted(set(temperatures)):
            raise DomainError("Las temperaturas deben crecer sin repetirse.")
        if speeds != sorted(speeds):
            raise DomainError("Las RPM no pueden bajar al subir la temperatura.")

    def validate_for(self, bounds: FanBounds) -> None:
        for point in self.points:
            if not bounds.minimum_rpm <= point.rpm <= bounds.maximum_rpm:
                raise DomainError(
                    f"{point.rpm} RPM queda fuera de "
                    f"{bounds.minimum_rpm}–{bounds.maximum_rpm} RPM."
                )
            if bounds.quantize(point.rpm) != point.rpm:
                raise DomainError(f"{point.rpm} RPM no respeta pasos de {bounds.step_rpm}.")

    def target_at(self, temperature_c: int, bounds: FanBounds) -> int:
        """Interpolate a quantized target at a measured temperature."""
        self.validate_for(bounds)
        if temperature_c <= self.points[0].temperature_c:
            return bounds.quantize(self.points[0].rpm)
        if temperature_c >= self.points[-1].temperature_c:
            return bounds.quantize(self.points[-1].rpm)

        for lower, upper in zip(self.points, self.points[1:], strict=True):
            if temperature_c <= upper.temperature_c:
                span = upper.temperature_c - lower.temperature_c
                progress = (temperature_c - lower.temperature_c) / span
                rpm = round(lower.rpm + progress * (upper.rpm - lower.rpm))
                return bounds.quantize(rpm)
        raise AssertionError("Una curva válida siempre contiene la temperatura intermedia.")


@dataclass(frozen=True, slots=True)
class ThermalSnapshot:
    cpu_temperature_c: int | None
    gpu_temperature_c: int | None
    fan1_rpm: int
    fan2_rpm: int

    def hottest_temperature(self) -> int:
        available = [
            temperature
            for temperature in (self.cpu_temperature_c, self.gpu_temperature_c)
            if temperature is not None
        ]
        if not available:
            raise TemperatureUnavailableError(
                "No hay una temperatura fiable; se devuelve el control al firmware."
            )
        return max(available)


@dataclass(frozen=True, slots=True)
class FanTargets:
    fan1_rpm: int
    fan2_rpm: int


@dataclass(frozen=True, slots=True)
class FanPolicy:
    mode: FanMode
    fixed_rpm: int
    curve: FanCurve

    def validate_for(self, bounds: FanBounds) -> None:
        self.curve.validate_for(bounds)
        if not bounds.minimum_rpm <= self.fixed_rpm <= bounds.maximum_rpm:
            raise DomainError(
                f"La RPM fija debe estar entre {bounds.minimum_rpm} y "
                f"{bounds.maximum_rpm}."
            )
        if bounds.quantize(self.fixed_rpm) != self.fixed_rpm:
            raise DomainError(
                f"La RPM fija debe respetar pasos de {bounds.step_rpm} RPM."
            )

    def target_for(self, temperature_c: int, bounds: FanBounds) -> int | None:
        self.validate_for(bounds)
        if self.mode is FanMode.AUTO:
            return None
        if temperature_c >= EMERGENCY_FIRMWARE_CONTROL_C:
            raise CriticalTemperatureError(
                "Temperatura crítica; se devuelve el control al firmware."
            )
        if temperature_c >= EMERGENCY_FULL_SPEED_C:
            return bounds.maximum_rpm
        if self.mode is FanMode.FIXED:
            return bounds.quantize(self.fixed_rpm)
        return self.curve.target_at(temperature_c, bounds)


class FanController:
    """Asymmetric smoothing and hysteresis around an immutable fan policy."""

    def __init__(self, policy: FanPolicy, bounds: FanBounds) -> None:
        policy.validate_for(bounds)
        self._policy = policy
        self._bounds = bounds
        self._temperatures: deque[int] = deque(maxlen=TEMPERATURE_FILTER_SAMPLES)
        self._held_temperature_c: int | None = None
        self._target_rpm: int | None = None
        self._cooling_samples = 0
        self._control_temperature_c: int | None = None

    def next_targets(self, snapshot: ThermalSnapshot) -> FanTargets | None:
        hottest = snapshot.hottest_temperature()
        raw_target = self._policy.target_for(hottest, self._bounds)
        if raw_target is None:
            return None
        if (
            self._policy.mode is FanMode.FIXED
            or hottest >= EMERGENCY_FULL_SPEED_C
        ):
            self._control_temperature_c = hottest
            self._held_temperature_c = hottest
            self._target_rpm = raw_target
            self._cooling_samples = 0
            return FanTargets(fan1_rpm=raw_target, fan2_rpm=raw_target)

        self._temperatures.append(hottest)
        filtered = int(median_high(self._temperatures))
        self._control_temperature_c = filtered
        desired = self._policy.target_for(filtered, self._bounds)
        assert desired is not None
        target = self._stabilize_curve_target(filtered, desired)
        return FanTargets(fan1_rpm=target, fan2_rpm=target)

    @property
    def control_temperature_c(self) -> int | None:
        """Temperature used for normal curve interpolation after filtering."""
        return self._control_temperature_c

    def _stabilize_curve_target(self, temperature_c: int, desired_rpm: int) -> int:
        previous_rpm = self._target_rpm
        reference_temperature = self._held_temperature_c
        if previous_rpm is None or reference_temperature is None:
            self._held_temperature_c = temperature_c
            self._target_rpm = desired_rpm
            return desired_rpm

        if desired_rpm >= previous_rpm:
            self._cooling_samples = 0
            if desired_rpm > previous_rpm:
                self._held_temperature_c = temperature_c
                self._target_rpm = desired_rpm
            return self._target_rpm

        if temperature_c > reference_temperature - DOWNWARD_HYSTERESIS_C:
            self._cooling_samples = 0
            return previous_rpm

        self._cooling_samples += 1
        if self._cooling_samples < DOWNWARD_CONFIRMATION_SAMPLES:
            return previous_rpm

        maximum_drop = self._bounds.step_rpm * MAX_DOWNWARD_STEP_COUNT
        next_rpm = self._bounds.quantize(
            max(desired_rpm, previous_rpm - maximum_drop)
        )
        self._target_rpm = next_rpm
        self._cooling_samples = 0
        if next_rpm == desired_rpm:
            self._held_temperature_c = temperature_c
        return next_rpm


DEFAULT_CURVE = FanCurve(
    (
        CurvePoint(45, 1700),
        CurvePoint(60, 2500),
        CurvePoint(75, 3600),
        CurvePoint(85, 4600),
        CurvePoint(90, 5300),
    )
)
