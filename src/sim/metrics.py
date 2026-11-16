"""Per-step simulation of a whole day for both policies, and the reported metrics."""
from __future__ import annotations

import numpy as np

from src.ai import fuzzy
from src.config import CFG
from src.sim.assignment import station_loads
from src.sim.network import Net, stops_to_closure

def simulate_day(net: Net, states: dict, step_state: list, base: np.ndarray, cap: np.ndarray,
                 water: np.ndarray, hours: np.ndarray) -> tuple[dict, dict]:
    """Step through the day for both policies: station loads, queue / give-ups, fuzzy priority,
    staff dispatch and every reported metric. Returns (per-step data, whole-day summary)."""
    thr = CFG["flood"]["threshold_mm"]
    steps = {"baseline": [], "ai": []}
    totals = {p: {"displaced": 0.0, "unserved": 0.0, "covered": 0.0, "overloaded_steps": 0, "peak_ratio": 0.0,
                  "staffed_critical": [], "max_overloaded": 0, "waiting_person_steps": 0.0, "peak_waiting": 0.0,
                  "peak_waiting_step": 0, "worst_station": None, "worst_station_waiting": 0.0} for p in steps}
    # Queue model: passengers who cannot board in a 15-minute step (arrivals > capacity) wait for the next one.
    #   queue_i(t) = max(0, queue_i(t-1) + arrivals_i(t) - capacity_i)
    # Crowding ratio = (arrivals + people already waiting) / capacity, so pile-ups feed the fuzzy priority.
    queue = {p: np.zeros(len(net.names)) for p in steps}
    stranded_cum = {p: 0.0 for p in steps}
    gave_up = {p: 0.0 for p in steps}
    abandon = CFG["crowd"]["abandon_per_step"]
    rank = {n: i for i, n in enumerate(net.order)}
    for t, key in enumerate(step_state):
        st = states[key]
        cl = set(key)
        dclos = stops_to_closure(net, cl)
        for pol in ("baseline", "ai"):
            if st["empty"]:
                load, disp, uns, cov, avg, p95 = base[t].copy(), set(), 0.0, 1.0, 0.0, 0.0
            else:
                ps = st[pol]
                disp = set(st["displaced"])
                load = station_loads(net, base[t], disp, ps["share"], ps["unserved"])
                uns = sum(base[t][net.idx[s]] * ps["unserved"][s] for s in sorted(disp))
                cov, avg, p95 = ps["coverage"], ps["avg_extra"], ps["p95_extra"]
            # a share of the people already waiting give up each step (taxi, walk, cancel the trip)
            gave_up[pol] += abandon * float(queue[pol].sum())
            waiting_before = (1 - abandon) * queue[pol]
            ratio = (load + waiting_before) / cap
            queue[pol] = np.maximum(0.0, waiting_before + load - cap)
            q = queue[pol]
            pr = fuzzy.priority(ratio, water[t] / thr, net.hub, dclos)
            dpx = float(sum(base[t][net.idx[s]] for s in sorted(disp)))
            stranded_cum[pol] += dpx
            # staff: baseline in network order among affected stations, AI by fuzzy priority
            affected = [n for n in net.names if dclos[net.idx[n]] <= 1] if cl else []
            if pol == "baseline":
                staffed = sorted(affected, key=lambda n: rank[n])[:CFG["policy"]["staff_teams"]]
            else:
                staffed = [net.names[i] for i in np.argsort(-pr)[:CFG["policy"]["staff_teams"]]]
            crit = [n for n in net.names if pr[net.idx[n]] >= 80]
            staffed_crit = (sum(n in staffed for n in crit) / len(crit)) if crit else None
            over = int((ratio > 1).sum())
            tt = totals[pol]
            tt["displaced"] += dpx
            tt["unserved"] += uns
            tt["covered"] += dpx * cov
            tt["overloaded_steps"] += over
            tt["max_overloaded"] = max(tt["max_overloaded"], over)
            tt["peak_ratio"] = max(tt["peak_ratio"], float(ratio.max()))
            if staffed_crit is not None:
                tt["staffed_critical"].append(staffed_crit)
            wsum = float(q.sum())
            tt["waiting_person_steps"] += wsum
            if wsum > tt["peak_waiting"]:
                tt["peak_waiting"], tt["peak_waiting_step"] = wsum, t
            wi = int(np.argmax(q))
            if q[wi] > tt["worst_station_waiting"]:
                tt["worst_station_waiting"], tt["worst_station"] = float(q[wi]), net.names[wi]
            steps[pol].append({
                "load": np.round(load).astype(int).tolist(), "ratio": np.round(ratio, 3).tolist(),
                "queue": np.round(q).astype(int).tolist(),
                "priority": np.round(pr, 1).tolist(), "staffed": staffed,
                "m": {"displaced": round(dpx), "covered_pct": round(100 * cov, 1), "overloaded": over,
                      "peak_ratio": round(float(ratio.max()), 3), "avg_extra": round(avg, 1),
                      "p95_extra": round(p95, 1), "unserved": round(uns),
                      "staffed_critical_pct": None if staffed_crit is None else round(100 * staffed_crit, 1),
                      "waiting": round(wsum), "stranded_so_far": round(stranded_cum[pol]),
                      "gave_up_so_far": round(gave_up[pol]),
                      "critical": int(sum(1 for n in crit if not (cl and n in cl))),
                      "closed": len(cl)},
            })

    summary = {}
    for pol, tt in totals.items():
        dsum = max(tt["displaced"], 1e-9)
        last = [states[k] for k in step_state if not states[k]["empty"]]
        fin = last[-1][pol] if last else None
        summary[pol] = {
            "displaced_total": round(tt["displaced"]), "unserved_total": round(tt["unserved"]),
            "unserved_pct": round(100 * tt["unserved"] / dsum, 2),
            "covered_pct": round(100 * tt["covered"] / dsum, 1),
            "avg_extra_min": round(fin["avg_extra"], 1) if fin else 0.0,
            "p95_extra_min": round(fin["p95_extra"], 1) if fin else 0.0,
            "overloaded_station_steps": tt["overloaded_steps"], "max_overloaded_stations": tt["max_overloaded"],
            "peak_ratio": round(tt["peak_ratio"], 3),
            "staffed_critical_pct": round(100 * float(np.mean(tt["staffed_critical"])), 1) if tt["staffed_critical"] else None,
            "peak_waiting": round(tt["peak_waiting"]), "peak_waiting_time": float(hours[tt["peak_waiting_step"]]),
            "waiting_person_hours": round(tt["waiting_person_steps"] * CFG["time"]["step_min"] / 60),
            "worst_station": tt["worst_station"], "worst_station_waiting": round(tt["worst_station_waiting"]),
            "gave_up": round(gave_up[pol]),
        }

    return steps, summary
