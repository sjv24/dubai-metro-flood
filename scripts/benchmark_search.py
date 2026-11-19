"""A* vs Dijkstra on the disrupted April 2024 network over many random origin-destination trips.

The graph is the replay's final closure state (the four real closures) with the 2024-style bus
bridges added, i.e. the network stranded passengers actually have to route on. For every trip both
searches run; we record nodes expanded, queue pushes and runtime, and check the path costs are
identical (and equal to networkx's Dijkstra).

Usage:  python scripts/benchmark_search.py [--trips 200] [--seed 0]
Writes: results/search_benchmark.csv (one row per trip), results/search_summary.csv
"""
from __future__ import annotations

import argparse
import math
import os
import time

from _common import RESULTS, ensure_dirs

import networkx as nx  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.ai.search import astar, dijkstra  # noqa: E402
from src.config import CFG  # noqa: E402
from src.core import crowd  # noqa: E402
from src.core.graph import build_graph, street  # noqa: E402
from src.sim.engine import load_net  # noqa: E402
from src.sim.policies import apply_routes, baseline_plan, find_breaks  # noqa: E402


def timed(fn, g, s, t, repeats: int = 5):
    """Best-of-N runtime (ms) to reduce timer noise; returns the result of the last call."""
    best, r = math.inf, None
    for _ in range(repeats):
        t0 = time.perf_counter()
        r = fn(g, s, t)
        best = min(best, (time.perf_counter() - t0) * 1000)
    return r, best


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trips", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    ensure_dirs()
    net = load_net()
    closed = set(CFG["closures_2024"])
    g = build_graph(net.raw, closed)
    displaced = closed | crowd.stranded_stations(g, net.names, closed)
    apply_routes(g, baseline_plan(find_breaks(net.raw["lines"], displaced), net.pos, {n: 1.0 for n in net.names}).routes)
    G = nx.DiGraph()
    for u, es in g.adj.items():
        for e in es:
            if not G.has_edge(u, e.to) or G[u][e.to]["weight"] > e.cost:
                G.add_edge(u, e.to, weight=e.cost)

    rng = np.random.default_rng(args.seed)
    rows = []
    while len(rows) < args.trips:
        o, d = rng.choice(net.names, size=2, replace=False)
        a, ta = timed(astar, g, street(o), street(d))
        k, tk = timed(dijkstra, g, street(o), street(d))
        if not a.found and not k.found:
            continue  # no route at all (both agree); skip so every row is a real comparison
        try:
            ref = nx.dijkstra_path_length(G, street(o), street(d))
        except nx.NetworkXNoPath:
            ref = math.inf
        rows.append({"origin": o, "dest": d, "cost_astar": a.cost, "cost_dijkstra": k.cost, "cost_networkx": ref,
                     "same_cost": abs(a.cost - k.cost) < 1e-9 and abs(a.cost - ref) < 1e-9,
                     "expanded_astar": a.expanded, "expanded_dijkstra": k.expanded,
                     "pushes_astar": a.pushes, "pushes_dijkstra": k.pushes,
                     "ms_astar": ta, "ms_dijkstra": tk})
    df = pd.DataFrame(rows)
    df["expansion_saving_pct"] = 100 * (1 - df.expanded_astar / df.expanded_dijkstra)
    df.to_csv(os.path.join(RESULTS, "search_benchmark.csv"), index=False)

    summ = []
    for col, label in [("expanded", "Nodes expanded"), ("pushes", "Queue pushes"), ("ms", "Runtime (ms, best of 5)")]:
        for alg in ("astar", "dijkstra"):
            v = df[f"{col}_{alg}"]
            summ.append({"measure": label, "algorithm": "A*" if alg == "astar" else "Dijkstra",
                         "mean": round(v.mean(), 3), "std": round(v.std(), 3), "median": round(v.median(), 3)})
    s = df.expansion_saving_pct
    summ.append({"measure": "A* expansion saving vs Dijkstra (%)", "algorithm": "A*", "mean": round(s.mean(), 1),
                 "std": round(s.std(), 1), "median": round(s.median(), 1)})
    summ.append({"measure": "Trips with identical optimal cost (A* = Dijkstra = networkx)", "algorithm": "both",
                 "mean": int(df.same_cost.sum()), "std": None, "median": None})
    summ.append({"measure": "Trips where A* expanded fewer or equal nodes", "algorithm": "A*",
                 "mean": int((df.expanded_astar <= df.expanded_dijkstra).sum()), "std": None, "median": None})
    summ.append({"measure": "Graph size (nodes / directed edges)", "algorithm": "-",
                 "mean": len(g.adj), "std": g.n_edges(), "median": None})
    pd.DataFrame(summ).to_csv(os.path.join(RESULTS, "search_summary.csv"), index=False)
    print(pd.DataFrame(summ).to_string(index=False))


if __name__ == "__main__":
    main()
