"""Storm cell + per-station water accumulation + calibration against the April 2024 closures.

Rain at station i, time t (mm/h):
    R_i(t) = I(t) * [ b + (1 - b) * exp(-d_i(t)^2 / (2 r^2)) ] * noise_i
  I(t)   triangular intensity profile over the storm duration, peak = peak_mmh, scaled so the
         storm-centre total equals total_mm (peak is capped at what that total allows)
  d_i(t) distance from station to the storm centre, which moves linearly along `path`
  b      background share (the 2024 storm was widespread), r = cell radius, noise ~ lognormal
Water (mm):
    W_i(t+dt) = max(0, W_i(t) + dt * (s_i * R_i(t) - drainage * D))
  s_i = floor + (1 - floor) * vulnerability_i, vulnerability_i from the observed April-2024
        ridership drop (data.py). This is a data-driven proxy, not a hydrological model: stated openly.
A station closes (and stays closed) once W_i >= threshold.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from src.config import CFG
from src.core.data import haversine_km


@dataclass
class Storm:
    total_mm: float
    peak_mmh: float
    duration_h: float
    start_hour: float
    path: list[list[float]]   # [[lon, lat] start, [lon, lat] end]
    radius_km: float
    drainage: float = 1.0     # drainage effectiveness multiplier (1 = 2024 conditions)

    @classmethod
    def preset(cls, name: str, **override) -> "Storm":
        p = {k: v for k, v in CFG["presets"][name].items() if k in cls.__dataclass_fields__}
        p.update({k: v for k, v in override.items() if v is not None})
        return cls(**p)

    def intensity(self, hour: float) -> float:
        """Storm-centre intensity (mm/h) at clock time `hour`: triangle with area total_mm."""
        x = (hour - self.start_hour) / self.duration_h
        if x < 0 or x > 1:
            return 0.0
        peak = min(self.peak_mmh, 2 * self.total_mm / self.duration_h)
        if peak <= 0:
            return 0.0
        # trapezoid with the given peak and the requested total: plateau length solves area
        plateau = max(0.0, min(1.0, self.total_mm / (peak * self.duration_h) * 2 - 1))
        ramp = (1 - plateau) / 2
        if x < ramp:
            return peak * x / ramp
        if x > 1 - ramp:
            return peak * (1 - x) / ramp
        return peak

    def centre(self, hour: float) -> tuple[float, float]:
        """(lat, lon) of the storm cell."""
        x = np.clip((hour - self.start_hour) / self.duration_h, 0, 1)
        (lo0, la0), (lo1, la1) = self.path
        return la0 + (la1 - la0) * x, lo0 + (lo1 - lo0) * x


def susceptibility(vulnerability: np.ndarray) -> np.ndarray:
    f = CFG["flood"]["susceptibility_floor"]
    return f + (1 - f) * np.asarray(vulnerability)


def simulate_water(storm: Storm, lat: np.ndarray, lon: np.ndarray, sus: np.ndarray, hours: np.ndarray,
                   rng: np.random.Generator, threshold: float | None = None, base_drain: float | None = None):
    """Returns rain (T, N) mm/h, water (T, N) mm, closed (T, N) bool, closed_at index (N,) or -1."""
    fc = CFG["flood"]
    threshold = fc["threshold_mm"] if threshold is None else threshold
    base_drain = fc["base_drainage_mmh"] if base_drain is None else base_drain
    dt = (hours[1] - hours[0]) if len(hours) > 1 else 0.25
    noise = rng.lognormal(0, fc["rain_noise_sd"], size=len(lat))
    T, N = len(hours), len(lat)
    rain, water, closed = np.zeros((T, N)), np.zeros((T, N)), np.zeros((T, N), bool)
    w, c = np.zeros(N), np.zeros(N, bool)
    b = fc["background_share"]
    for t, h in enumerate(hours):
        cl, co = storm.centre(h)
        d = haversine_km(lat, lon, cl, co)
        r = storm.intensity(h) * (b + (1 - b) * np.exp(-d ** 2 / (2 * storm.radius_km ** 2))) * noise
        w = np.maximum(0.0, w + dt * (sus * r - storm.drainage * base_drain))
        c = c | (w >= threshold)
        rain[t], water[t], closed[t] = r, w, c
    closed_at = np.where(closed.any(0), closed.argmax(0), -1)
    return rain, water, closed, closed_at


def calibrate(lat, lon, vuln, names, hours, target: set[str], seeds: int = 10):
    """Grid-search threshold and base drainage so the April-2024 replay closes `target`.

    Score = mean F1 over seeds (ties broken by fewer false positives). Returns params + precision/recall.
    """
    storm = Storm.preset("april_2024_replay")
    sus = susceptibility(vuln)
    y = np.array([n in target for n in names])
    best = None
    for thr in np.arange(5, 121, 2.5):
        for drain in np.arange(3, 14.1, 1.0):  # drainage > 0 so the drainage slider has an effect
            ps, rs, fs = [], [], []
            for s in range(seeds):
                _, _, closed, _ = simulate_water(storm, lat, lon, sus, hours, np.random.default_rng(s), thr, drain)
                pred = closed[-1]
                tp = (pred & y).sum()
                p = tp / pred.sum() if pred.sum() else 0.0
                r = tp / y.sum()
                ps.append(p), rs.append(r), fs.append(2 * p * r / (p + r) if p + r else 0.0)
            # best F1, then precision; among ties prefer the highest threshold (least hair-trigger model)
            key = (round(float(np.mean(fs)), 3), round(float(np.mean(ps)), 3), float(thr))
            if best is None or key > best[0]:
                best = (key, {"threshold_mm": float(thr), "base_drainage_mmh": float(drain),
                              "precision": float(np.mean(ps)), "recall": float(np.mean(rs)), "f1": float(np.mean(fs))})
    return best[1]
