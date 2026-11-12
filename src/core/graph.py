"""Multimodal transit graph.

Node ids:
  "S:<station>"         street node (passengers start / end here; walk and bus edges attach here)
  "P:<station>:<line>"  platform node (one per line serving the station)

Edge types and cost (minutes):
  metro    platform <-> next platform on the same line   track_km / metro_speed
  entry    street   <-> platform                         entry_exit_min (a transfer = exit + entry)
  walk     street   <-> street (stations < walk_max_km)  straight_km * walk_detour / walk_speed
  bus      street   <-> street (added by a policy)       wait + straight_km * road_detour / bus_speed

Closing a station removes its platform nodes, so trains cannot stop at or run through it.
Its street node stays: displaced passengers start there.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.config import CFG
from src.core.data import haversine_km


@dataclass
class Edge:
    to: str
    cost: float
    mode: str
    meta: dict = field(default_factory=dict)


@dataclass
class Graph:
    pos: dict[str, tuple[float, float]] = field(default_factory=dict)   # node -> (lat, lon)
    adj: dict[str, list[Edge]] = field(default_factory=dict)

    def add_node(self, n: str, lat: float, lon: float) -> None:
        self.pos[n] = (lat, lon)
        self.adj.setdefault(n, [])

    def add_edge(self, a: str, b: str, cost: float, mode: str, both: bool = True, **meta) -> None:
        self.adj[a].append(Edge(b, cost, mode, meta))
        if both:
            self.adj[b].append(Edge(a, cost, mode, meta))

    def remove_node(self, n: str) -> None:
        self.adj.pop(n, None)
        self.pos.pop(n, None)
        for edges in self.adj.values():
            edges[:] = [e for e in edges if e.to != n]

    def copy(self) -> "Graph":
        return Graph(dict(self.pos), {k: [Edge(e.to, e.cost, e.mode, e.meta) for e in v] for k, v in self.adj.items()})

    def n_edges(self) -> int:
        return sum(len(v) for v in self.adj.values())


def max_speed_kmh() -> float:
    """Fastest straight-line speed any edge can achieve; used by the A* heuristic."""
    n = CFG["network"]
    return max(n["metro_speed_kmh"], n["walk_speed_kmh"], n["bus_speed_kmh"])


def street(name: str) -> str:
    return f"S:{name}"


def platform(name: str, line: str) -> str:
    return f"P:{name}:{line}"


def station_of(node: str) -> str:
    return node.split(":")[1]


def build_graph(net: dict, closed: set[str] = frozenset()) -> Graph:
    """Graph for the network with `closed` stations' platforms removed."""
    n = CFG["network"]
    g = Graph()
    pos = {s["name"]: (s["lat"], s["lon"]) for s in net["stations"]}
    line_of_platform = {}
    for line, names in net["lines"].items():
        for name in names:
            line_of_platform.setdefault(name, set()).add(line)

    for name, (lat, lon) in pos.items():
        g.add_node(street(name), lat, lon)
        if name in closed:
            continue
        for line in line_of_platform[name]:
            p = platform(name, line)
            g.add_node(p, lat, lon)
            g.add_edge(street(name), p, n["entry_exit_min"], "entry")

    # Jabal Ali is shared by Red and Route 2020: through-running trains, so connect those platforms freely.
    if "Jabal Ali" not in closed:
        g.add_edge(platform("Jabal Ali", "Red"), platform("Jabal Ali", "Route 2020"), 0.0, "metro")

    for e in net["edges"]:
        if e["a"] in closed or e["b"] in closed:
            continue
        t = e["km"] / n["metro_speed_kmh"] * 60
        g.add_edge(platform(e["a"], e["line"]), platform(e["b"], e["line"]), t, "metro", line=e["line"], km=e["km"])

    names = list(pos)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            d = float(haversine_km(*pos[a], *pos[b]))
            if d <= n["walk_max_km"]:
                g.add_edge(street(a), street(b), d * n["walk_detour"] / n["walk_speed_kmh"] * 60, "walk", km=d)
    return g


def bus_time_min(a: tuple[float, float], b: tuple[float, float], wait_min: float) -> float:
    n = CFG["network"]
    d = float(haversine_km(*a, *b))
    return wait_min + d * n["road_detour"] / n["bus_speed_kmh"] * 60


def rail_neighbours(net: dict) -> dict[str, set[str]]:
    """Station-level adjacency along the rail lines (for 'stops to nearest closure')."""
    nb: dict[str, set[str]] = {s["name"]: set() for s in net["stations"]}
    for e in net["edges"]:
        nb[e["a"]].add(e["b"])
        nb[e["b"]].add(e["a"])
    nb["Jabal Ali"] |= set()
    return nb
