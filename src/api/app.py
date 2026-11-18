"""FastAPI backend: serves the network and simulation runs as JSON, plus the static frontend.

Run:  .venv/Scripts/python -m uvicorn src.api.app:app --port 8000
Then open http://localhost:8000
"""
from __future__ import annotations

import json
import math
import os
import threading
from functools import lru_cache

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.config import CFG, ROOT
from src.sim.engine import load_net, run

app = FastAPI(title="Dubai Metro Flood Response AI")
FRONTEND = os.path.join(ROOT, "frontend")


def _clean(o):
    """Make numpy / inf values JSON-safe."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, np.ndarray):
        return _clean(o.tolist())
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if not math.isfinite(f) else f
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


class SimRequest(BaseModel):
    scenario: str = "april_2024_replay"
    seed: int = 42
    total_mm: float | None = None
    peak_mmh: float | None = None
    duration_h: float | None = None
    drainage: float | None = None
    start_hour: float | None = None
    radius_km: float | None = None
    path: list[list[float]] | None = None


@lru_cache(maxsize=64)
def _cached(key: str) -> str:
    req = SimRequest(**json.loads(key))
    override = {k: v for k, v in req.model_dump().items() if k not in ("scenario", "seed") and v is not None}
    return json.dumps(_clean(run(req.scenario, req.seed, override)))


def _track_parts(net) -> list[dict]:
    """Label each KML LineString with the line whose stations lie along it (the KML has no line names)."""
    from src.core.data import haversine_km
    out = []
    for path in net.raw["track_geometry"]:
        a = np.array(path)
        votes = {}
        for st in net.raw["stations"]:
            d = haversine_km(a[:, 1], a[:, 0], st["lat"], st["lon"]).min()
            if d < 0.2 and not st["interchange"]:
                for ln in st["lines"]:
                    votes[ln] = votes.get(ln, 0) + 1
        out.append({"line": max(votes, key=votes.get) if votes else "Red", "path": path})
    return out


@app.get("/api/network")
def network():
    net = load_net()
    return JSONResponse(_clean({
        "stations": net.raw["stations"], "lines": net.raw["lines"], "track_parts": _track_parts(net),
        "presets": CFG["presets"], "report": net.raw["report"],
        "threshold_mm": CFG["flood"]["threshold_mm"], "closures_2024": CFG["closures_2024"],
        "edges": net.raw["edges"], "graph_size": {"nodes": len(net.g0.adj), "edges": net.g0.n_edges()},
        "n_bus_stops": len(net.raw["bus_stops"]),
        "flood_params": CFG["flood"], "network_params": CFG["network"], "crowd_params": CFG["crowd"],
        "policy_params": CFG["policy"],
    }))


@app.get("/api/fuzzy")
def fuzzy_explain(load: float, flood: float, hub: float, dist: float):
    """Every step of the Mamdani inference for one station's inputs."""
    from src.ai.fuzzy import explain
    return JSONResponse(_clean(explain(load, flood, hub, dist)))


class SearchRequest(BaseModel):
    origin: str
    dest: str
    closed: list[str] = []


@app.post("/api/search")
def search_explain(req: SearchRequest):
    """A* and Dijkstra on the disrupted network (closed stations removed, 2024-style bus bridge added),
    with the full expansion trace (g, h, f per expanded node)."""
    from src.ai.search import astar, dijkstra
    from src.core.graph import build_graph, max_speed_kmh, street
    from src.sim.policies import apply_routes, baseline_plan, find_breaks
    net = load_net()
    closed = set(req.closed)
    g = build_graph(net.raw, closed)
    displaced = closed | __import__("src.core.crowd", fromlist=["x"]).stranded_stations(g, net.names, closed)
    plan = baseline_plan(find_breaks(net.raw["lines"], displaced), net.pos, {n: 1.0 for n in net.names})
    apply_routes(g, plan.routes)

    def label(n):
        parts = n.split(":")
        return parts[1] + (" (street)" if parts[0] == "S" else f" ({parts[2]} platform)" if parts[0] == "P" else "")

    out = {"origin": req.origin, "dest": req.dest, "vmax_kmh": max_speed_kmh(),
           "nodes": len(g.adj), "edges": g.n_edges(),
           "graph": [{"a": [g.pos[u][1], g.pos[u][0]], "b": [g.pos[e.to][1], g.pos[e.to][0]], "mode": e.mode}
                     for u, es in g.adj.items() for e in es if u < e.to and e.mode in ("metro", "walk", "bus")]}
    for name, fn in (("astar", astar), ("dijkstra", dijkstra)):
        r = fn(g, street(req.origin), street(req.dest), record=True)
        out[name] = {"cost": r.cost, "expanded": r.expanded, "pushes": r.pushes, "runtime_ms": r.runtime_ms,
                     "path": [{"node": label(n), "lon": g.pos[n][1], "lat": g.pos[n][0]} for n in r.path],
                     "modes": r.modes,
                     "trace": [{"node": label(t["node"]), "station": t["node"].split(":")[1],
                                "lon": g.pos[t["node"]][1], "lat": g.pos[t["node"]][0],
                                "g": round(t["g"], 2), "h": round(t["h"], 2), "f": round(t["f"], 2),
                                "frontier": t["frontier"], "via": t["via"]} for t in r.trace]}
    return JSONResponse(_clean(out))


@app.post("/api/simulate")
def simulate(req: SimRequest):
    if req.scenario not in CFG["presets"]:
        raise HTTPException(400, f"unknown scenario {req.scenario}")
    key = json.dumps(req.model_dump(), sort_keys=True)
    return JSONResponse(content=json.loads(_cached(key)))


@app.get("/api/results")
def results():
    """Multi-seed experiment tables produced by scripts/run_all.py (read from results/*.csv)."""
    import pandas as pd

    rdir = os.path.join(ROOT, "results")

    def table(name: str):
        p = os.path.join(rdir, name)
        return pd.read_csv(p).to_dict("records") if os.path.exists(p) else None

    cal = table("calibration_seeds.csv")
    cal_summary = None
    if cal:
        df = pd.DataFrame(cal)
        cal_summary = {"seeds": len(df), "precision_mean": df.precision.mean(), "precision_std": df.precision.std(),
                       "recall_mean": df.recall.mean(), "recall_std": df.recall.std(),
                       "most_common": df.closed.value_counts().head(1).to_dict()}
    return JSONResponse(_clean({
        "available": os.path.exists(os.path.join(rdir, "comparison.csv")),
        "comparison": table("comparison.csv"), "search": table("search_summary.csv"),
        "ga": table("ga_summary.csv"), "sensitivity": table("sensitivity.csv"),
        "calibration": cal_summary, "ga_overload_ablation": table("ga_overload_ablation.csv"),
    }))


@app.on_event("startup")
def _warm():
    """Precompute every preset at the default seed in the background so the demo is instant."""
    def work():
        load_net()
        for sc in CFG["presets"]:
            _cached(json.dumps(SimRequest(scenario=sc).model_dump(), sort_keys=True))
    threading.Thread(target=work, daemon=True).start()


@app.get("/")
def story():
    """Guided story: 2024 replay -> four AI decisions -> rerun with AI -> comparison."""
    return FileResponse(os.path.join(FRONTEND, "story.html"))


@app.get("/explorer")
def explorer():
    """Algorithm explorer: one tab per algorithm with its maths and live numbers."""
    return FileResponse(os.path.join(FRONTEND, "index.html"))


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
