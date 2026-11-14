"""Mamdani fuzzy inference for station priority (0-100), written from scratch with numpy.

Inputs
  load      load ratio = current load / capacity           universe 0 .. 2
  flood     flood risk = accumulated water / threshold     universe 0 .. 1.5 (>= 1 means closed)
  hub       interchange status                             0 or 1 (crisp, fuzzified as singleton-like sets)
  dist      stops to the nearest closed station            universe 0 .. 10
Output
  priority  0 .. 100, labelled Low / Medium / High / Critical

Inference: min for AND, max aggregation, clipped (min) implication, centroid defuzzification.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def trimf(x: np.ndarray | float, a: float, b: float, c: float):
    x = np.asarray(x, dtype=float)
    left = np.where(b > a, (x - a) / max(b - a, 1e-12), (x >= b).astype(float))
    right = np.where(c > b, (c - x) / max(c - b, 1e-12), (x <= b).astype(float))
    return np.clip(np.minimum(left, right), 0, 1)


def trapmf(x: np.ndarray | float, a: float, b: float, c: float, d: float):
    x = np.asarray(x, dtype=float)
    left = (x - a) / (b - a) if b > a else np.where(x >= b, 1.0, 0.0)
    right = (d - x) / (d - c) if d > c else np.where(x <= c, 1.0, 0.0)
    return np.clip(np.minimum(np.minimum(left, right), 1.0), 0, 1)


# Membership functions: name -> (kind, params)
MF = {
    "load": {"low": ("trap", (0, 0, 0.5, 0.8)), "normal": ("tri", (0.6, 0.9, 1.1)),
             "high": ("tri", (0.95, 1.25, 1.55)), "overload": ("trap", (1.3, 1.6, 2.0, 2.0))},
    "flood": {"dry": ("trap", (0, 0, 0.15, 0.35)), "wet": ("tri", (0.2, 0.5, 0.8)),
              "severe": ("trap", (0.65, 0.95, 1.5, 1.5))},
    "hub": {"no": ("trap", (0, 0, 0.3, 0.7)), "yes": ("trap", (0.3, 0.7, 1, 1))},
    "dist": {"near": ("trap", (0, 0, 1, 2.5)), "mid": ("tri", (1.5, 3.5, 5.5)), "far": ("trap", (4.5, 7, 10, 10))},
}
OUT = {"low": ("trap", (0, 0, 15, 35)), "medium": ("tri", (25, 45, 65)),
       "high": ("tri", (55, 72, 88)), "critical": ("trap", (80, 92, 100, 100))}
OUT_U = np.linspace(0, 100, 201)

# (antecedents {input: term}, consequent). 16 rules.
RULES: list[tuple[dict[str, str], str]] = [
    ({"load": "overload"}, "critical"),
    ({"load": "high", "hub": "yes"}, "critical"),
    ({"load": "high", "dist": "near"}, "critical"),
    ({"load": "high", "dist": "mid"}, "high"),
    ({"load": "high", "dist": "far", "hub": "no"}, "medium"),
    ({"flood": "severe"}, "high"),
    ({"flood": "severe", "hub": "yes"}, "critical"),
    ({"flood": "wet", "dist": "near"}, "high"),
    ({"flood": "wet", "dist": "far"}, "medium"),
    ({"load": "normal", "dist": "near"}, "high"),
    ({"load": "normal", "dist": "mid"}, "medium"),
    ({"load": "normal", "dist": "far", "flood": "dry"}, "low"),
    ({"hub": "yes", "dist": "near"}, "critical"),   # an interchange next to a closure is a critical node
    ({"hub": "yes", "dist": "mid", "load": "low"}, "medium"),
    ({"load": "low", "flood": "dry", "dist": "far"}, "low"),
    ({"load": "low", "dist": "near", "flood": "dry"}, "medium"),
    ({"load": "low", "dist": "mid"}, "low"),
]

LABELS = [(80, "Critical"), (55, "High"), (30, "Medium"), (0, "Low")]


def _mu(spec, x):
    kind, p = spec
    return trimf(x, *p) if kind == "tri" else trapmf(x, *p)


def _clip_inputs(load, flood, hub, dist):
    return (np.clip(load, 0, 2), np.clip(flood, 0, 1.5), np.clip(hub, 0, 1), np.clip(dist, 0, 10))


OUT_MU = {k: _mu(v, OUT_U) for k, v in OUT.items()}


def priority(load, flood, hub, dist) -> np.ndarray:
    """Vectorised Mamdani inference. Each argument is a scalar or array of equal length."""
    load, flood, hub, dist = (np.atleast_1d(np.asarray(v, dtype=float)) for v in (load, flood, hub, dist))
    load, flood, hub, dist = _clip_inputs(load, flood, hub, dist)
    x = {"load": load, "flood": flood, "hub": hub, "dist": dist}
    fz = {var: {term: _mu(spec, x[var]) for term, spec in terms.items()} for var, terms in MF.items()}
    n = len(load)
    agg = np.zeros((n, OUT_U.size))
    for ante, cons in RULES:
        strength = np.ones(n)
        for var, term in ante.items():
            strength = np.minimum(strength, fz[var][term])
        agg = np.maximum(agg, np.minimum(strength[:, None], OUT_MU[cons][None, :]))
    area = agg.sum(axis=1)
    cent = np.where(area > 0, (agg * OUT_U).sum(axis=1) / np.maximum(area, 1e-12), 0.0)
    return cent


RANGES = {"load": (0, 2), "flood": (0, 1.5), "hub": (0, 1), "dist": (0, 10)}


def explain(load: float, flood: float, hub: float, dist: float) -> dict:
    """Every intermediate value of one Mamdani inference, for teaching and the demo.

    fuzzify -> rule strength = min of its antecedent degrees -> clip each consequent set at its
    rule's strength -> aggregate with max -> centroid of the aggregate."""
    raw = {"load": load, "flood": flood, "hub": hub, "dist": dist}
    x = dict(zip(("load", "flood", "hub", "dist"), (float(v) for v in _clip_inputs(load, flood, hub, dist))))
    mf_curves, degrees = {}, {}
    for var, terms in MF.items():
        lo, hi = RANGES[var]
        xs = np.linspace(lo, hi, 61)
        mf_curves[var] = {"x": xs.round(3).tolist(),
                          "terms": {t: np.round(_mu(spec, xs), 4).tolist() for t, spec in terms.items()},
                          "params": {t: [spec[0], list(spec[1])] for t, spec in terms.items()}}
        degrees[var] = {t: round(float(_mu(spec, x[var])), 4) for t, spec in terms.items()}
    rules, agg = [], np.zeros(OUT_U.size)
    for i, (ante, cons) in enumerate(RULES):
        parts = [{"var": v, "term": t, "degree": degrees[v][t]} for v, t in ante.items()]
        strength = min(p["degree"] for p in parts)
        rules.append({"id": i + 1, "if": parts, "then": cons, "strength": round(strength, 4)})
        agg = np.maximum(agg, np.minimum(strength, OUT_MU[cons]))
    area = agg.sum()
    cent = float((agg * OUT_U).sum() / area) if area > 0 else 0.0
    return {
        "inputs": {k: round(float(v), 4) for k, v in raw.items()}, "clipped": x, "degrees": degrees,
        "mf": mf_curves, "rules": rules,
        "output": {"x": OUT_U[::2].round(2).tolist(), "terms": {k: v[::2].round(4).tolist() for k, v in OUT_MU.items()},
                   "aggregate": agg[::2].round(4).tolist(), "params": {t: [s[0], list(s[1])] for t, s in OUT.items()}},
        "centroid": round(cent, 2), "label": label(cent),
    }


def label(p: float) -> str:
    for cut, name in LABELS:
        if p >= cut:
            return name
    return "Low"


@dataclass
class StationPriority:
    name: str
    priority: float
    label: str
