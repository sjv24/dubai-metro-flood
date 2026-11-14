"""Fuzzy priority: output range, monotonic sanity checks, and the explain() trace matching priority()."""
import numpy as np
import pytest

from src.ai import fuzzy


def test_fuzzy_output_in_range():
    rng = np.random.default_rng(0)
    out = fuzzy.priority(rng.random(500) * 2, rng.random(500) * 1.5, rng.integers(0, 2, 500), rng.random(500) * 10)
    assert np.all((out >= 0) & (out <= 100))


def test_fuzzy_monotonic_sanity():
    loads = np.linspace(0, 2, 21)
    p = fuzzy.priority(loads, np.zeros(21), np.zeros(21), np.full(21, 2.0))
    assert p[-1] > p[0]
    assert np.all(np.diff(p) >= -3)  # non-decreasing up to small centroid wobble
    near = fuzzy.priority(1.0, 0.0, 0, 0)[0]
    far = fuzzy.priority(1.0, 0.0, 0, 10)[0]
    assert near > far
    assert fuzzy.priority(1.2, 0.0, 1, 1)[0] >= fuzzy.priority(1.2, 0.0, 0, 1)[0]
    assert fuzzy.label(90) == "Critical" and fuzzy.label(10) == "Low"


def test_interchange_never_lowers_priority():
    for load in np.linspace(0, 2, 11):
        for flood in np.linspace(0, 1.5, 4):
            for dist in range(0, 11, 2):
                assert fuzzy.priority(load, flood, 1, dist)[0] >= fuzzy.priority(load, flood, 0, dist)[0] - 3


@pytest.mark.parametrize("inputs", [(1.89, 0.2, 0, 1), (0.65, 0.13, 0, 10), (1.2, 0.3, 1, 1), (0.9, 0.9, 0, 3)])
def test_explain_matches_priority(inputs):
    e = fuzzy.explain(*inputs)
    assert e["centroid"] == pytest.approx(fuzzy.priority(*inputs)[0], abs=0.01)
    assert len(e["rules"]) == len(fuzzy.RULES)
    for r in e["rules"]:  # rule strength = min of its antecedent degrees
        assert r["strength"] == pytest.approx(min(c["degree"] for c in r["if"]), abs=1e-4)
