"""April 2024 replay: exactly the four real closures, flood-timed, and fully reproducible."""
import numpy as np
import pytest

from src.config import CFG
from src.core import flood
from src.sim.engine import hours_axis, load_net, run

REAL_2024 = {"Noor Bank", "First Abu Dhabi Bank", "Mashreq", "Energy"}   # Onpassive, Equiti, Mashreq, Energy


@pytest.fixture(scope="module")
def replay():
    return run("april_2024_replay", 42)


def test_config_lists_the_real_closures():
    assert set(CFG["closures_2024"]) == REAL_2024
    assert set(CFG["presets"]["april_2024_replay"]["force_closed"]) == REAL_2024


@pytest.mark.parametrize("seed", [0, 1, 42])
def test_replay_closes_exactly_the_four_real_stations(seed):
    out = run("april_2024_replay", seed, detail=False)
    assert set(out["closed_final"]) == REAL_2024


def test_replay_closure_times_come_from_the_flood_model(replay):
    """Each station closes at its first threshold crossing, or at its peak water level if it never crosses."""
    net = load_net()
    thr = CFG["flood"]["threshold_mm"]
    # recompute the exact (unrounded) water levels the run used: same storm, same seed, same first draw
    hours = hours_axis()
    _, water, _, _ = flood.simulate_water(flood.Storm.preset("april_2024_replay"), net.lat, net.lon,
                                          flood.susceptibility(net.vuln), hours, np.random.default_rng(42))
    closed_at = replay["closed_at"]
    for i, name in enumerate(net.names):
        if name not in REAL_2024:
            assert closed_at[i] == -1, f"{name} must stay open in the replay"
            continue
        cross = np.flatnonzero(water[:, i] >= thr)
        expected = cross[0] if cross.size else int(np.argmax(water[:, i]))
        assert closed_at[i] == expected
        assert 0 <= closed_at[i] < len(hours_axis())


def test_flood_only_validation_is_reported(replay):
    cal = replay["calibration"]
    assert set(cal["target"]) == REAL_2024
    assert 0 <= cal["precision"] <= 1 and 0 <= cal["recall"] <= 1


def test_same_seed_same_result():
    a = run("april_2024_replay", 3, detail=False)["summary"]
    b = run("april_2024_replay", 3, detail=False)["summary"]
    assert a == b
