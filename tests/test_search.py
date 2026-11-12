"""A* and Dijkstra (written from scratch): optimality against networkx, admissibility, closures."""
import networkx as nx
import numpy as np
import pytest

from src.ai.search import _haversine_scalar, astar, dijkstra, make_haversine_heuristic
from src.core.data import build, haversine_km
from src.core.graph import Graph, build_graph, max_speed_kmh, street


def random_geo_graph(seed: int, n: int = 40) -> Graph:
    """Random graph on Dubai-like coordinates whose edge costs respect the admissibility bound."""
    rng = np.random.default_rng(seed)
    g = Graph()
    lat = 25.0 + rng.random(n) * 0.3
    lon = 55.0 + rng.random(n) * 0.4
    for i in range(n):
        g.add_node(f"n{i}", lat[i], lon[i])
    vmax = max_speed_kmh()
    for i in range(n):
        for j in rng.choice(n, size=3, replace=False):
            if i != j:
                km = float(haversine_km(lat[i], lon[i], lat[j], lon[j]))
                cost = km / vmax * 60 * (1 + rng.random() * 2)  # never faster than vmax
                g.add_edge(f"n{i}", f"n{j}", cost, "test")
    return g


def to_nx(g: Graph) -> nx.DiGraph:
    G = nx.DiGraph()
    for u, es in g.adj.items():
        G.add_node(u)
        for e in es:
            if not G.has_edge(u, e.to) or G[u][e.to]["weight"] > e.cost:
                G.add_edge(u, e.to, weight=e.cost)
    return G


@pytest.mark.parametrize("seed", range(15))
def test_astar_and_dijkstra_match_networkx(seed):
    g = random_geo_graph(seed)
    G = to_nx(g)
    rng = np.random.default_rng(100 + seed)
    for _ in range(10):
        s, t = (f"n{i}" for i in rng.choice(40, 2, replace=False))
        a, d = astar(g, s, t), dijkstra(g, s, t)
        try:
            ref = nx.dijkstra_path_length(G, s, t)
        except nx.NetworkXNoPath:
            assert not a.found and not d.found
            continue
        assert a.cost == pytest.approx(ref) and d.cost == pytest.approx(ref)
        assert a.expanded <= d.expanded


def test_metro_graph_matches_networkx_and_heuristic_is_admissible():
    net = build()
    g = build_graph(net, {"Mashreq"})
    G = to_nx(g)
    h = make_haversine_heuristic(g)
    # admissible: h(n) <= true remaining cost for every node towards a few goals
    for goal in [street("Union"), street("Ibn Battuta"), street("Creek")]:
        true = nx.single_source_dijkstra_path_length(G.reverse(), goal)
        for n, c in true.items():
            assert h(n, goal) <= c + 1e-9
    # EXPO -> the north is cut off by the Mashreq closure (needs a bus), so test within each side
    for s, t in [("Business Bay", "Creek"), ("Mall of the Emirates", "BurJuman"), ("EXPO", "Ibn Battuta")]:
        ref = nx.dijkstra_path_length(G, street(s), street(t))
        assert astar(g, street(s), street(t)).cost == pytest.approx(ref)
        assert dijkstra(g, street(s), street(t)).cost == pytest.approx(ref)


def test_every_edge_respects_heuristic_bound():
    """Consistency: each edge costs at least straight-line distance / vmax (implies admissibility)."""
    g = build_graph(build())
    h = make_haversine_heuristic(g)
    for u, es in g.adj.items():
        for e in es:
            assert e.cost + 1e-9 >= h(u, e.to)


def test_fast_haversine_matches_numpy_version():
    rng = np.random.default_rng(0)
    for _ in range(100):
        a, b, c, d = 24.9 + rng.random() * 0.5, 55 + rng.random() * 0.5, 24.9 + rng.random() * 0.5, 55 + rng.random() * 0.5
        assert _haversine_scalar(a, b, c, d) == pytest.approx(float(haversine_km(a, b, c, d)), rel=1e-12)


def test_closed_station_cannot_be_passed_by_train():
    g = build_graph(build(), {"Mashreq"})
    assert "P:Mashreq:Red" not in g.adj
    r = astar(g, street("Mall of the Emirates"), street("Dubai Internet City"))
    assert "metro" not in r.modes or all(not n.startswith("P:Mashreq") for n in r.path)
