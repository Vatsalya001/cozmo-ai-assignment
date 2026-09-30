"""Measurements and their intervals.

The brief scores calibration at every tier and says confident garbage on thin input caps the
total score, so no physical quantity leaves the pipeline as a bare float. Every one carries a
nominal 90% interval, and the widening factor per tier is fitted from measured error in
bench/calibrate_intervals.py -- not guessed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

Z90 = 1.645  # two-sided 90% normal quantile


@dataclass
class Measurement:
    value: float
    ci_low: float
    ci_high: float
    confidence: float = 0.9
    method: str = ""
    observed: bool = True

    def as_dict(self) -> dict:
        d = {"value": round(self.value, 4), "ci_low": round(self.ci_low, 4),
             "ci_high": round(self.ci_high, 4), "confidence": self.confidence}
        if self.method:
            d["method"] = self.method
        if not self.observed:
            d["observed"] = False
        return d

    def contains(self, truth: float) -> bool:
        return self.ci_low <= truth <= self.ci_high


def from_sigma(value: float, sigma: float, *, method: str = "", observed: bool = True,
               widen: float = 1.0, floor_m: float = 0.0) -> Measurement:
    """Interval from a standard deviation, widened by the tier's calibrated factor.

    `floor_m` is a minimum half-width: it keeps an interval honest when the formal covariance
    is optimistic about a bias we know exists but have not yet measured out.
    """
    half = max(Z90 * sigma * widen, floor_m)
    return Measurement(value, value - half, value + half, method=method, observed=observed)


def log_scale(value: float, factor: float, *, method: str = "", observed: bool = True) -> Measurement:
    """Multiplicative interval for very uncertain quantities, so the low end never goes
    negative. `factor` of 1.3 means roughly -23% / +30%."""
    factor = max(factor, 1.0 + 1e-9)
    return Measurement(value, value / factor, value * factor, method=method, observed=observed)


def unobserved(typical: float, factor: float, *, method: str = "") -> Measurement:
    """A value the sensor never saw: a population typical value with a deliberately wide
    interval, flagged observed=false so no reader mistakes it for a measurement."""
    m = log_scale(typical, factor, method=method, observed=False)
    m.observed = False
    return m


def propagate_length(sigma_a: float, sigma_b: float) -> float:
    """Sigma of the distance between two independently estimated corners."""
    return math.hypot(sigma_a, sigma_b)


def propagate_area(length: float, width: float, sigma_l: float, sigma_w: float) -> float:
    """Sigma of a rectangular area from its two side sigmas (first-order)."""
    return math.hypot(width * sigma_l, length * sigma_w)


def coverage(measurements: list[Measurement], truths: list[float]) -> float:
    """Fraction of intervals containing the truth. A-CALIB wants 0.85 to 0.95."""
    if not measurements:
        return float("nan")
    return sum(m.contains(t) for m, t in zip(measurements, truths)) / len(measurements)
