"""Flood model: no rain closes nothing; the storm delivers the requested total."""
import numpy as np
import pytest

from src.core import flood
from src.core.data import build


def test_zero_rain_closes_nothing():
    net = build()
    lat = np.array([s["lat"] for s in net["stations"]])
    lon = np.array([s["lon"] for s in net["stations"]])
    vul = np.array([s["vulnerability"] for s in net["stations"]])
    storm = flood.Storm(total_mm=0, peak_mmh=0, duration_h=6, start_hour=6, path=[[55.1, 25.0], [55.4, 25.3]], radius_km=10)
    hours = np.arange(5, 24, 0.25)
    _, water, closed, _ = flood.simulate_water(storm, lat, lon, flood.susceptibility(vul), hours, np.random.default_rng(0))
    assert not closed.any() and water.max() == 0


def test_storm_total_matches_request():
    s = flood.Storm(total_mm=120, peak_mmh=40, duration_h=8, start_hour=6, path=[[55, 25], [55, 25]], radius_km=10)
    hours = np.arange(5, 16, 0.01)
    total = sum(s.intensity(h) for h in hours) * 0.01
    assert total == pytest.approx(120, rel=0.02)
