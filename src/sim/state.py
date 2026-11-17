"""Everything that depends only on the set of closed stations: both policies' plans, routing and the GA."""
from __future__ import annotations

import numpy as np

from src.ai import fuzzy
from src.ai.ga import greedy, random_placement, run_ga
from src.ai.search import dijkstra_all
from src.config import CFG
from src.core import crowd
from src.core.graph import build_graph, street
from src.sim.assignment import evaluate_policy
from src.sim.hubs import add_hub_nodes, build_hub_problem, relief_coverage
from src.sim.network import Net, stops_to_closure
from src.sim.policies import PolicyPlan, ai_bridges, ai_plan, apply_routes, baseline_plan, dedupe_breaks, find_breaks
from src.sim.terminals import optimise_terminals

def plan_json(plan: PolicyPlan) -> dict:
    return {"routes": [{"kind": r.kind, "stops": r.names, "coords": [[c[1], c[0]] for c in r.coords],
                        "buses": r.buses, "headway_min": round(r.headway_min, 1)} for r in plan.routes],
            "relief": plan.relief_points}


def solve_state(net: Net, closed: frozenset, peak_t: int, base: np.ndarray, cap: np.ndarray, water_pk: np.ndarray,
                seed: int) -> dict:
    """Everything that depends only on the set of closed stations."""
    rng = np.random.default_rng(seed + 7919 * len(closed))
    g_closed = build_graph(net.raw, set(closed))
    stranded = crowd.stranded_stations(g_closed, net.names, set(closed))
    displaced = set(closed) | stranded
    peak_dem = base[peak_t]
    dem = {n: float(peak_dem[i]) for i, n in enumerate(net.names)}
    if not displaced:
        return {"displaced": [], "stranded": [], "empty": True}

    # OD sample: destinations proportional to daily demand among non-displaced stations
    dests = [n for n in net.names if n not in displaced]
    p = np.array([net.daily[net.idx[n]] for n in dests])
    p /= p.sum()
    M = CFG["crowd"]["displaced_dests_per_station"]
    trips = [(s, str(d), 1.0 / M) for s in sorted(displaced) for d in rng.choice(dests, size=M, p=p)]
    normal = {}
    for s in sorted(displaced):
        dist0 = dijkstra_all(net.g0, street(s))
        for _, d, _ in (t for t in trips if t[0] == s):
            normal[(s, d)] = dist0[street(d)]
    breaks = find_breaks(net.raw["lines"], displaced)

    # --- baseline ---
    bplan = baseline_plan(breaks, net.pos, dem)
    gb = g_closed.copy()
    apply_routes(gb, bplan.routes)
    bev = evaluate_policy(net, gb, trips, normal, displaced, peak_dem, cap, crowd_aware=False)

    # --- AI: bus-bridge design evaluated with crowd-aware A*, then crowd-aware A* routing, then GA relief hubs ---
    terms, extras, designs = optimise_terminals(net, g_closed, breaks, dem, trips, normal, displaced, peak_dem, cap)
    routes = ai_bridges(breaks, net.pos, dem, terms, extras)
    ga_graph = g_closed.copy()
    apply_routes(ga_graph, routes)
    aev = evaluate_policy(net, ga_graph, trips, normal, displaced, peak_dem, cap, crowd_aware=True)

    dclos = stops_to_closure(net, set(closed))
    prio_pk = fuzzy.priority(aev["ratio"], water_pk / CFG["flood"]["threshold_mm"], net.hub, dclos)
    prob, cands = build_hub_problem(net, ga_graph, displaced, peak_dem, prio_pk, aev["ratio"], rng)
    gc = CFG["ga"]
    ga = run_ga(prob, rng, gc["population"], gc["generations"], gc["tournament_size"], gc["crossover_rate"],
                gc["mutation_rate"], gc["elitism"], gc["selection"])
    gr = greedy(prob)
    rnd = random_placement(prob, rng)
    hubs = [cands[i] for i in ga.best]
    aplan = ai_plan(routes, hubs)
    add_hub_nodes(net, ga_graph, hubs)

    return {
        "empty": False, "displaced": sorted(displaced), "stranded": sorted(stranded),
        "breaks": [{"line": b.line, "closed": b.closed, "a": b.end_a, "b": b.end_b} for b in dedupe_breaks(breaks)],
        "terminals": {str(i): list(v) for i, v in terms.items()}, "terminal_designs": designs,
        "extras": {str(i): v for i, v in extras.items()},
        "dist": stops_to_closure(net, set(closed)).tolist(),
        "baseline": {**bev, "coverage": relief_coverage(gb, displaced, bplan.relief_nodes, dem),
                     "plan": plan_json(bplan), "graph": gb},
        "ai": {**aev, "coverage": relief_coverage(ga_graph, displaced, aplan.relief_nodes, dem),
               "plan": plan_json(aplan), "graph": ga_graph},
        "ga": {"fitness": ga.fitness, "curve_best": ga.curve_best, "curve_mean": ga.curve_mean,
               "greedy": gr.fitness, "random": rnd.fitness, "evaluations": ga.evaluations,
               "covered_ga": prob.covered_share(ga.best), "covered_greedy": prob.covered_share(gr.best),
               "covered_random": prob.covered_share(rnd.best), "n_candidates": prob.n_cand,
               # how many chosen hubs sit at an overcrowded station (independent of the fitness weight)
               "hubs_at_overloaded": {m: int((prob.cand_overload[list(sol.best)] > 0).sum())
                                      for m, sol in (("ga", ga), ("greedy", gr), ("random", rnd))},
               "n_overloaded_candidates": int((prob.cand_overload > 0).sum()),
               "hubs": hubs, "greedy_hubs": [cands[i] for i in gr.best],
               "curve_worst": ga.curve_worst, "diversity": ga.diversity,
               "first_gen_hubs": [cands[i]["name"] for i in ga.first_gen_best],
               "best_per_gen": [[{"name": cands[i]["name"], "lat": cands[i]["lat"], "lon": cands[i]["lon"],
                                  "kind": cands[i]["kind"]} for i in gen] for gen in ga.best_per_gen],
               "breakdown": {"ga": prob.breakdown(ga.best), "greedy": prob.breakdown(gr.best),
                             "random": prob.breakdown(rnd.best)},
               "greedy_steps": [{"name": cands[s["added"]]["name"], "fitness": s["fitness"]} for s in gr.steps],
               "candidates": [{"lat": c["lat"], "lon": c["lon"], "kind": c["kind"]} for c in cands],
               "nearest_hub": [{"station": n, "hub": cands[ga.best[int(np.argmin(prob.t[net.idx[n], ga.best]))]]["name"],
                                "minutes": round(float(np.min(prob.t[net.idx[n], ga.best])), 1)} for n in sorted(displaced)],
               "params": {"k": prob.k, "T": prob.T, "w_p": prob.w_p, "w_o": prob.w_o, "w_t": prob.w_t,
                          **{k: CFG["ga"][k] for k in ("population", "generations", "tournament_size",
                                                       "crossover_rate", "mutation_rate", "elitism", "selection")}}},
    }
