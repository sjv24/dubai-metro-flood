"""Time-step simulation entry point: storm -> closures -> both policies -> loads, priorities, metrics.

The work is split across modules:
  network.py     stations, base graph, time axis           closures.py   forced / flood closures
  assignment.py  A* routing, queue waits, station loads    terminals.py  bus-bridge design (evaluated with A*)
  hubs.py        GA hub problem, relief coverage           state.py      everything per closure state
  metrics.py     per-step day loop and reported metrics
Heavy work runs once per distinct closure state and is cached; each 15-minute step then only scales demand.
"""

from __future__ import annotations

import numpy as np

from src.ai.search import astar, dijkstra
from src.config import CFG
from src.core import crowd, flood
from src.core.data import haversine_km
from src.core.graph import Graph, street
from src.sim.closures import apply_forced_closures
from src.sim.metrics import simulate_day
from src.sim.network import Net, hours_axis, load_net
from src.sim.state import solve_state

__all__ = ["run", "load_net", "hours_axis", "search_demo", "apply_forced_closures", "solve_state", "Net"]


def flows(net: Net, ev: dict, min_share: float = 0.04) -> list[dict]:
    """Where displaced passengers board instead: [{from, to, share}] for the map's rerouting arcs."""
    out = []
    for s, sh in ev["share"].items():
        for i in np.argsort(-sh)[:4]:
            if sh[i] >= min_share:
                out.append({"from": s, "to": net.names[i], "share": round(float(sh[i]), 3)})
    return out


def search_demo(net: Net, g: Graph, displaced: list[str]) -> dict | None:
    """A* vs Dijkstra on the AI graph for the busiest displaced station to a far, busy destination."""
    if not displaced:
        return None
    s = max(displaced, key=lambda n: net.daily[net.idx[n]])
    cand = [n for n in net.names if n not in displaced]
    d = max(cand, key=lambda n: net.daily[net.idx[n]] * float(haversine_km(*net.pos[s], *net.pos[n])))
    out = {"origin": s, "dest": d}
    for name, fn in (("astar", astar), ("dijkstra", dijkstra)):
        r = fn(g, street(s), street(d), record=True)
        out[name] = {"cost": round(r.cost, 2), "expanded": r.expanded, "runtime_ms": round(r.runtime_ms, 3),
                     "order": [[g.pos[n][1], g.pos[n][0]] for n in r.order],
                     "path": [[g.pos[n][1], g.pos[n][0]] for n in r.path], "modes": r.modes}
    return out


def run(scenario: str = "april_2024_replay", seed: int | None = None, storm_override: dict | None = None,
        detail: bool = True) -> dict:
    net = load_net()
    seed = CFG["seed"] if seed is None else seed
    rng = np.random.default_rng(seed)
    storm = flood.Storm.preset(scenario, **(storm_override or {}))
    hours = hours_axis()
    sus = flood.susceptibility(net.vuln)
    rain, water, closed, closed_at = flood.simulate_water(storm, net.lat, net.lon, sus, hours, rng)
    flood_only = set(np.array(net.names)[closed[-1]].tolist())   # what the flood model alone closes (validation)
    closed = apply_forced_closures(net, scenario, closed, water, storm, hours, rng)
    closed_at = np.where(closed.any(0), closed.argmax(0), -1)
    base = crowd.base_load(net.daily, hours)
    cap = crowd.capacity(base)

    states: dict[frozenset, dict] = {}
    step_state = []
    for t in range(len(hours)):
        key = frozenset(np.array(net.names)[closed[t]].tolist())
        if key not in states:
            # GA and routing are solved against the busiest remaining step of the day (worst case)
            peak_t = t + int(np.argmax(base[t:].sum(1)))
            states[key] = solve_state(net, key, peak_t, base, cap, water[t], seed)
        step_state.append(key)

    steps, summary = simulate_day(net, states, step_state, base, cap, water, hours)

    final_key = step_state[-1]
    fs = states[final_key]
    target = set(CFG["closures_2024"])
    tp = len(flood_only & target)
    out = {
        "scenario": scenario, "seed": seed,
        "storm": storm.__dict__,
        "closed_final": sorted(final_key),
        # validation: how well the flood model ALONE (no forcing) reproduces the real 2024 closures
        "calibration": {"target": sorted(target), "flood_only_closed": sorted(flood_only),
                        "precision": round(tp / len(flood_only), 3) if flood_only else 0.0,
                        "recall": round(tp / len(target), 3)} if scenario == "april_2024_replay" else None,
        "summary": summary,
        "ga": None if fs["empty"] else {k: v for k, v in fs["ga"].items()},
    }
    if not detail:
        return out
    out.update({
        "hours": hours.round(3).tolist(),
        "capacity": np.round(cap).astype(int).tolist(),
        "rain": np.round(rain, 2).tolist(), "water": np.round(water, 1).tolist(),
        "closed_at": closed_at.tolist(),
        "storm_track": [[*storm.centre(h)[::-1], round(storm.intensity(h), 2)] for h in hours],
        "steps": steps,
        "states": [{"from_step": step_state.index(k), "displaced": s.get("displaced", []),
                    "stranded": s.get("stranded", []), "breaks": s.get("breaks", []),
                    "baseline": None if s["empty"] else s["baseline"]["plan"],
                    "ai": None if s["empty"] else s["ai"]["plan"],
                    "hubs": None if s["empty"] else s["ga"]["hubs"],
                    "ga": None if s["empty"] else s["ga"],
                    "dist": s.get("dist"), "terminals": s.get("terminals"),
                    "terminal_designs": s.get("terminal_designs"), "extras": s.get("extras"),
                    "flows": None if s["empty"] else {pol: flows(net, s[pol]) for pol in ("baseline", "ai")}}
                   for k, s in states.items()],
        "search": None if fs["empty"] else search_demo(net, fs["ai"]["graph"], fs["displaced"]),
    })
    return out
