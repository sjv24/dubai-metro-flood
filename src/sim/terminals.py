"""Bus-bridge design (end stations + optional split shuttle). Part of the response design, not a
separate AI technique: every candidate design is evaluated with crowd-aware A* routing."""
from __future__ import annotations

import numpy as np

from src.config import CFG
from src.sim.assignment import evaluate_policy
from src.sim.policies import ai_bridges, apply_routes, dedupe_breaks

def design_objective(ev) -> float:
    """Minutes-equivalent cost used to compare bridge designs: delay + overload + unserved."""
    over = float(np.maximum(ev["ratio"] - 1, 0).sum())
    uns = float(np.mean(list(ev["unserved"].values()))) if ev["unserved"] else 0.0
    return ev["avg_extra"] + 10.0 * over + 100.0 * uns


def optimise_terminals(net, g_closed, breaks, dem, trips, normal, displaced, peak_dem, cap):
    """Response design evaluated with A* (not a separate AI technique): for each break, enumerate the
    candidate bus-bridge designs (end-station pairs within `terminal_reach` stops, then an optional
    split shuttle), route every sampled passenger on each design with crowd-aware A*, and keep the
    design with the lowest objective (delay + overcrowding + unserved)."""
    reach = CFG["policy"].get("terminal_reach", 3)
    # every 3rd sampled trip, carrying 3x the passengers, so the crowding it creates is unchanged
    trips = [(s, d, 3 * w) for s, d, w in trips[::3]]
    db = dedupe_breaks(breaks)
    terms = {i: (b.end_a, b.end_b) for i, b in enumerate(db)}
    tried, designs = 0, []
    for i, b in enumerate(db):
        opts_a = b.side_a[:reach] or [None]
        opts_b = b.side_b[:reach] or [None]
        best = None
        for a in opts_a:
            for c in opts_b:
                cand = dict(terms)
                cand[i] = (a, c)
                g = g_closed.copy()
                apply_routes(g, ai_bridges(breaks, net.pos, dem, cand))
                ev = evaluate_policy(net, g, trips, normal, displaced, peak_dem, cap, crowd_aware=True)
                tried += 1
                obj = design_objective(ev)
                designs.append({"break": i, "a": a, "b": c, "objective": round(obj, 2),
                                "avg_extra": round(ev["avg_extra"], 2),
                                "overload": round(float(np.maximum(ev["ratio"] - 1, 0).sum()), 3),
                                "unserved": round(float(np.mean(list(ev["unserved"].values()))), 4)})
                if best is None or obj < best[0]:
                    best = (obj, (a, c))
        terms[i] = best[1]
    # phase 2: given the terminals, try adding a split shuttle to one open station further out
    extras: dict[int, str | None] = {i: None for i in terms}
    for i, b in enumerate(db):
        base_obj = min(d["objective"] for d in designs if d["break"] == i and (d["a"], d["b"]) == terms[i])
        best = (base_obj, None)
        opts = [s for s in (b.side_a[1:reach + 1] + b.side_b[1:reach + 1]) if s not in terms[i]]
        for x in opts:
            cand = dict(extras)
            cand[i] = x
            g = g_closed.copy()
            apply_routes(g, ai_bridges(breaks, net.pos, dem, terms, cand))
            ev = evaluate_policy(net, g, trips, normal, displaced, peak_dem, cap, crowd_aware=True)
            obj = design_objective(ev)
            designs.append({"break": i, "a": terms[i][0], "b": terms[i][1], "extra": x, "objective": round(obj, 2),
                            "avg_extra": round(ev["avg_extra"], 2),
                            "overload": round(float(np.maximum(ev["ratio"] - 1, 0).sum()), 3),
                            "unserved": round(float(np.mean(list(ev["unserved"].values()))), 4)})
            if obj < best[0]:
                best = (obj, x)
        extras[i] = best[1]
    return terms, extras, designs
