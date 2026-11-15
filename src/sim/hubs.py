"""Relief-hub placement problem for the genetic algorithm, and relief coverage measurement."""
from __future__ import annotations

import math

import numpy as np

from src.ai.ga import HubProblem
from src.ai.search import dijkstra_all
from src.config import CFG
from src.core.data import haversine_km
from src.core.graph import Graph, street
from src.sim.network import Net

def walk_min(km):
    nc = CFG["network"]
    return np.where(km <= nc["walk_max_km"], km * nc["walk_detour"] / nc["walk_speed_kmh"] * 60, np.inf)


def station_dist_matrix(net: Net, g: Graph) -> np.ndarray:
    """(N, N) minutes between station street nodes on graph g."""
    D = np.full((len(net.names), len(net.names)), np.inf)
    for i, s in enumerate(net.names):
        dist = dijkstra_all(g, street(s))
        for j, n in enumerate(net.names):
            D[i, j] = dist.get(street(n), math.inf)
    return D


def build_hub_problem(net: Net, g: Graph, displaced: set[str], peak_dem: np.ndarray, prio: np.ndarray,
                 ratio: np.ndarray, rng: np.random.Generator):
    """Candidates = open stations + real bus stops within walking reach of a displaced station.
    t[target, cand] = minutes on graph g (which already holds the AI bus bridges); a bus-stop hub is
    reached by travelling to some station and walking from it."""
    pc, gc = CFG["policy"], CFG["ga"]
    open_st = [n for n in net.names if n not in displaced]
    reach = CFG["network"]["walk_max_km"]
    bs = [b for b in net.raw["bus_stops"]
          if any(float(haversine_km(b["lat"], b["lon"], *net.pos[s])) <= reach for s in sorted(displaced))]
    if len(bs) > 200:
        bs = [bs[i] for i in sorted(rng.choice(len(bs), 200, replace=False))]
    cands = [{"node": street(n), "name": n, "lat": net.pos[n][0], "lon": net.pos[n][1], "kind": "station"}
             for n in open_st]
    cands += [{"node": f"B:{b['stop_id']}", "name": b["name"] or b["stop_id"], "lat": b["lat"], "lon": b["lon"],
               "kind": "bus_stop"} for b in bs]
    D = station_dist_matrix(net, g)
    cols = []
    for c in cands:
        if c["kind"] == "station":
            cols.append(D[:, net.idx[c["name"]]])
        else:
            w = walk_min(haversine_km(net.lat, net.lon, c["lat"], c["lon"]))
            cols.append((D + w[None, :]).min(axis=1))
    t = np.stack(cols, axis=1)
    dem = np.array([peak_dem[i] if n in displaced else 0.0 for i, n in enumerate(net.names)])
    pr = np.array([0.0 if n in displaced else max(0.0, prio[i] - 30) for i, n in enumerate(net.names)])
    over = np.array([max(0.0, ratio[net.idx[c["name"]]] - 1) if c["kind"] == "station" else 0.0 for c in cands])
    prob = HubProblem(t, dem, pr, over, gc["k"], pc["relief_radius_min"], gc["w_priority"], gc["w_overload"],
                      gc.get("w_time", 0.5))
    return prob, cands


def relief_coverage(g: Graph, displaced: set[str], relief: list[str], dem: dict[str, float]) -> float:
    if not displaced:
        return 1.0
    T = CFG["policy"]["relief_radius_min"]
    ok = 0.0
    for s in sorted(displaced):
        dist = dijkstra_all(g, street(s))
        if any(dist.get(r, math.inf) <= T for r in relief):
            ok += dem[s]
    return ok / max(sum(dem[s] for s in sorted(displaced)), 1e-9)


def add_hub_nodes(net: Net, g: Graph, hubs: list[dict]) -> None:
    nc = CFG["network"]
    for h in hubs:
        if h["kind"] == "bus_stop" and h["node"] not in g.adj:
            g.add_node(h["node"], h["lat"], h["lon"])
            for n in net.names:
                d = float(haversine_km(h["lat"], h["lon"], *net.pos[n]))
                if d <= nc["walk_max_km"]:
                    g.add_edge(h["node"], street(n), d * nc["walk_detour"] / nc["walk_speed_kmh"] * 60, "walk")
