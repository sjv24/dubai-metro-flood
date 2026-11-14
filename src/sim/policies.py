"""Baseline (modelled on the 2024 response) vs AI response.

Both policies get the SAME shuttle fleet (config policy.bus_fleet); headway = round trip / buses.

Baseline (a MODEL of the 2024 response, not measured 2024 outcomes):
  - one shuttle per break between the open stations either side (Business Bay <-> Al Khail style),
    stopping at the closed stations in between (policy.baseline_stops_at_closed)
  - fleet split equally between breaks
  - relief points only at the shuttle terminals
  - plain shortest-path rerouting (no crowd awareness)
  - staff sent to affected stations in line order
AI (three AI techniques: A* search, fuzzy logic, genetic algorithm):
  - crowd-aware A* with incremental assignment routes every stranded passenger
  - bus-bridge design (end stations + optional split shuttle) is part of the response design, not a
    separate AI technique: each candidate design is evaluated by routing every passenger with
    crowd-aware A* and the best one is kept (engine.optimise_terminals)
  - fleet split by displaced demand
  - k relief hubs (open stations or real bus stops) placed by the GA
  - staff sent by fuzzy priority
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from src.config import CFG
from src.core.data import haversine_km
from src.core.graph import Graph, street


@dataclass
class Break:
    line: str
    closed: list[str]          # displaced stations in the break, in line order
    end_a: str | None          # open station before the break
    end_b: str | None          # open station after the break
    side_a: list[str] = field(default_factory=list)  # open stations before the break, nearest first
    side_b: list[str] = field(default_factory=list)  # open stations after the break, nearest first


@dataclass
class Route:
    kind: str                  # "bridge"
    stops: list[str]           # graph node ids
    coords: list[tuple[float, float]]
    weight: float = 1.0        # displaced demand served, used to share the fleet
    buses: int = 0
    headway_min: float = 0.0
    names: list[str] = field(default_factory=list)


@dataclass
class PolicyPlan:
    name: str
    routes: list[Route] = field(default_factory=list)
    relief_nodes: list[str] = field(default_factory=list)
    relief_points: list[dict] = field(default_factory=list)


def find_breaks(lines: dict[str, list[str]], displaced: set[str]) -> list[Break]:
    """Maximal runs of displaced stations on each line, with the open stations on either side."""
    out = []
    for line, names in lines.items():
        i = 0
        while i < len(names):
            if names[i] in displaced:
                j = i
                while j + 1 < len(names) and names[j + 1] in displaced:
                    j += 1
                before = [n for n in reversed(names[:i])]
                after = list(names[j + 1:])
                side_a = []
                for n in before:
                    if n in displaced:
                        break
                    side_a.append(n)
                side_b = []
                for n in after:
                    if n in displaced:
                        break
                    side_b.append(n)
                out.append(Break(line, names[i:j + 1], side_a[0] if side_a else None,
                                 side_b[0] if side_b else None, side_a, side_b))
                i = j + 1
            else:
                i += 1
    return out


def _road_km(coords: list[tuple[float, float]]) -> float:
    return sum(float(haversine_km(*a, *b)) for a, b in zip(coords, coords[1:])) * CFG["network"]["road_detour"]


def allocate_fleet(routes: list[Route], fleet: int, by_demand: bool) -> None:
    """Share buses (equally, or by demand x round-trip time), at least 1 each; headway = round trip / buses."""
    if not routes:
        return
    n = CFG["network"]
    rts = np.array([2 * _road_km(r.coords) / n["bus_speed_kmh"] * 60 + 2 * len(r.stops) * n["bus_stop_dwell_min"]
                    for r in routes])
    w = np.array([max(r.weight, 1e-6) for r in routes]) * rts if by_demand else np.ones(len(routes))
    alloc = np.maximum(1, np.floor(fleet * w / w.sum())).astype(int)
    while alloc.sum() < fleet:
        alloc[np.argmax(w / alloc)] += 1
    for r, b, rt in zip(routes, alloc, rts):
        r.buses = int(b)
        r.headway_min = max(3.0, rt / b)


def apply_routes(g: Graph, routes: list[Route]) -> None:
    """Add each shuttle as bus edges between every pair of its stops (ride along the chain, one wait)."""
    for r in routes:
        for i in range(len(r.stops)):
            for j in range(i + 1, len(r.stops)):
                ride = _road_km(r.coords[i:j + 1]) / CFG["network"]["bus_speed_kmh"] * 60
                ride += (j - i - 1) * CFG["network"]["bus_stop_dwell_min"]
                g.add_edge(r.stops[i], r.stops[j], r.headway_min / 2 + ride, "bus", route=r.kind)


def bridge_route(chain: list[str], pos, weight: float) -> Route:
    return Route("bridge", [street(s) for s in chain], [pos[s] for s in chain], weight, names=list(chain))


def _relief(plan: PolicyPlan, node: str, name: str, lat: float, lon: float, kind: str) -> None:
    if node not in plan.relief_nodes:
        plan.relief_nodes.append(node)
        plan.relief_points.append({"node": node, "name": name, "lat": lat, "lon": lon, "kind": kind})


def dedupe_breaks(breaks: list[Break]) -> list[Break]:
    """An interchange closure creates a break on each line; keep each (line, closed run) once."""
    seen, out = set(), []
    for b in breaks:
        key = (b.line, tuple(b.closed))
        if key not in seen and (b.end_a or b.end_b):
            seen.add(key)
            out.append(b)
    return out


def baseline_plan(breaks: list[Break], pos, demand: dict[str, float]) -> PolicyPlan:
    plan = PolicyPlan("baseline")
    stop_closed = CFG["policy"].get("baseline_stops_at_closed", True)
    for br in dedupe_breaks(breaks):
        ends = [e for e in (br.end_a, br.end_b) if e]
        if stop_closed or len(ends) == 1:
            chain = ([br.end_a] if br.end_a else []) + br.closed + ([br.end_b] if br.end_b else [])
        else:
            chain = ends
        plan.routes.append(bridge_route(chain, pos, sum(demand[s] for s in br.closed)))
        for s in ends:
            _relief(plan, street(s), s, *pos[s], "station")
    allocate_fleet(plan.routes, CFG["policy"]["bus_fleet"], by_demand=False)
    return plan


def ai_bridges(breaks: list[Break], pos, demand: dict[str, float], terminals: dict[int, tuple],
               extras: dict[int, str | None] | None = None) -> list[Route]:
    """Bridge per break using the chosen terminals (default: adjacent open stations).

    Optional split bridge: a second shuttle from the closed stations to `extras[i]`, an open station
    beyond the main terminals, so not every displaced passenger has to board at the same (crowded)
    terminal. Both share the same fleet."""
    routes = []
    extras = extras or {}
    for i, br in enumerate(dedupe_breaks(breaks)):
        a, b = terminals.get(i, (br.end_a, br.end_b))
        chain = ([a] if a else []) + br.closed + ([b] if b else [])
        w = sum(demand[s] for s in br.closed)
        routes.append(bridge_route(chain, pos, w))
        x = extras.get(i)
        if x:
            # x lies before the break (side_a) or after it (side_b): attach it at that end, so the bus
            # never drives through the whole closed section the wrong way first
            chain = [x] + br.closed if x in br.side_a else br.closed + [x]
            routes.append(Route("split", [street(s) for s in chain], [pos[s] for s in chain], 0.5 * w, names=chain))
    allocate_fleet(routes, CFG["policy"]["bus_fleet"], by_demand=True)
    return routes


def ai_plan(routes: list[Route], hubs: list[dict]) -> PolicyPlan:
    plan = PolicyPlan("ai", routes=routes)
    for h in hubs:
        _relief(plan, h["node"], h["name"], h["lat"], h["lon"], h["kind"])
    return plan
