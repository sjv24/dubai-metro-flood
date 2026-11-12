"""Load, clean and join the raw RTA files into one network description.

Output (cached to data/processed/network.json):
  stations: id, name, display name, lat, lon, lines, interchange, daily demand, 2024 vulnerability
  lines:    ordered station ids per line + KML geometry for drawing
  edges:    consecutive-station track distances (km)
  report:   cleaning log (renames, dropped rows, unmatched names)
"""
from __future__ import annotations

import glob
import json
import math
import os
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.config import CFG, ROOT

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Names used by the routes/stops file (2021 snapshot) -> name used in the stations file.
# Each pair was matched by coordinates (0 m apart); see insights/02_data_cleaning.
ROUTE_FILE_ALIASES = {
    "Centrepoint": "Rashidiya", "max": "Al Jafiliya", "Al Safa": "Noor Bank",
    "Umm Al Sheif": "First Abu Dhabi Bank", "Al Khail": "Nakheel", "Sobha Realty": "DAMAC Properties",
    "Sharaf DG": "Al Fahidi", "EXPO 2020": "EXPO", "IBN Battuta": "Ibn Battuta", "mashreq": "Mashreq",
    "Burj Khalifa / Dubai Mall": "Burj Khalifa/ Dubai Mall",
    "Union - Red Line": "Union", "Union - Green Line": "Union",
    "BurJuman - Red Line": "BurJuman", "BurJuman - Green Line": "BurJuman",
}
# Names used in 2024 news reports (ASSUMPTION: renames, shown alongside the dataset name).
DISPLAY_NAMES = {"Noor Bank": "Onpassive", "First Abu Dhabi Bank": "Equiti", "Nakheel": "Al Khail",
                 "DAMAC Properties": "Sobha Realty", "Rashidiya": "Centrepoint", "Al Jafiliya": "Max"}
# Ridership names that no longer exist in the stations file (pre-2021 names, no later data).
LEGACY_RIDERSHIP = {"Jumeirah Lakes Towers", "Nakheel Harbour & Tower", "Palm Deira", "Sharaf DG"}


def _f(prefix: str) -> str:
    hits = glob.glob(os.path.join(ROOT, CFG["data"]["raw_dir"], prefix + "*"))
    if len(hits) != 1:
        raise FileNotFoundError(f"expected exactly one file for {prefix}*, got {hits}")
    return hits[0]


def clean_name(name: str) -> str:
    """'Union  (Green Line ) Metro Station' -> 'Union'."""
    n = re.sub(r"\(.*?\)", "", str(name)).replace("Metro Station", "")
    return re.sub(r"\s+", " ", n).strip()


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km (works on scalars or numpy arrays)."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * np.arcsin(np.sqrt(a))


@dataclass
class CleanLog:
    entries: list[str] = field(default_factory=list)

    def add(self, msg: str) -> None:
        self.entries.append(msg)


def load_stations(log: CleanLog) -> pd.DataFrame:
    raw = pd.read_csv(_f("metro_stations_"))
    log.add(f"stations file: {len(raw)} rows")
    raw["name"] = raw.location_name_english.map(clean_name)
    raw["line"] = raw.line_name.str.split().str[0]  # Red / Green
    lines = raw.groupby("name").line.apply(lambda s: sorted(set(s))).to_dict()
    st = raw.drop_duplicates("name").copy()
    log.add(f"stations: {len(raw) - len(st)} duplicate rows merged (station listed once per line): "
            + ", ".join(sorted(raw[raw.duplicated('name', keep=False)].name.unique())))
    st["lines"] = st.name.map(lines)
    st["interchange"] = st.lines.map(len) > 1
    st = st.rename(columns={"station_location_latitude": "lat", "station_location_longitude": "lon",
                            "location_id": "location_id"})
    st["display"] = st.name.map(lambda n: f"{DISPLAY_NAMES[n]} ({n})" if n in DISPLAY_NAMES else n)
    return st[["name", "display", "location_id", "lat", "lon", "lines", "interchange", "zone_id"]].reset_index(drop=True)


def load_line_order(st: pd.DataFrame, log: CleanLog) -> dict[str, list[str]]:
    """Ordered stations per line from the routes file's Metro rows (stop_order_number)."""
    b = pd.read_csv(_f("public_transportation_routes_stops_"), low_memory=False)
    m = b[b.transport_mode == "Metro"].drop_duplicates(["route_name", "stop_name"])
    m = m.assign(name=m.stop_name.map(lambda n: ROUTE_FILE_ALIASES.get(n, n)))
    unknown = set(m.name) - set(st.name)
    if unknown:
        raise ValueError(f"metro stop names not matched to stations file: {unknown}")
    log.add(f"line order: {len(m)} metro stop rows from routes file, all matched "
            f"({sum(m.stop_name != m.name)} via alias table)")
    order = {}
    for line, g in m.sort_values("stop_order_number").groupby("route_name"):
        order[line] = list(g.name)
    # Red line: orders 11-42 are the main line, 70-76 the Route 2020 branch starting at Jabal Ali.
    red = m[m.route_name == "Red"].sort_values("stop_order_number")
    order["Red"] = list(red[red.stop_order_number < 70].name)
    order["Route 2020"] = ["Jabal Ali"] + list(red[red.stop_order_number >= 70].name)
    return order


def load_kml() -> list[np.ndarray]:
    """Every LineString in the KML as an (n, 2) array of lon, lat."""
    k = open(_f("rail_routes_"), encoding="utf-8").read()
    parts = []
    for c in re.findall(r"<coordinates>(.*?)</coordinates>", k, re.S):
        pts = [[float(v) for v in p.split(",")[:2]] for p in c.split()]
        if len(pts) > 2:
            parts.append(np.array(pts))
    return parts


def _chainage(part: np.ndarray, lat: float, lon: float) -> tuple[float, float]:
    """Distance along `part` (km) of the vertex closest to the point, and the snap distance (m)."""
    seg = haversine_km(part[:-1, 1], part[:-1, 0], part[1:, 1], part[1:, 0])
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    d = haversine_km(part[:, 1], part[:, 0], lat, lon)
    i = int(np.argmin(d))
    return float(cum[i]), float(d[i] * 1000)


def track_distances(st: pd.DataFrame, order: dict[str, list[str]], parts, log: CleanLog) -> list[dict]:
    """Distance between consecutive stations along KML track; falls back to straight line x1.05."""
    pos = st.set_index("name")[["lat", "lon"]]
    snap = CFG["network"]["track_snap_m"]
    edges, fallback = [], 0
    for line, names in order.items():
        for a, b in zip(names, names[1:]):
            (la, oa), (lb, ob) = pos.loc[a], pos.loc[b]
            straight = float(haversine_km(la, oa, lb, ob))
            best = None
            for p in parts:
                ca, da = _chainage(p, la, oa)
                cb, db = _chainage(p, lb, ob)
                if da < snap and db < snap:
                    d = abs(cb - ca)
                    if d >= straight * 0.98 and (best is None or d < best):
                        best = d
            if best is None:
                best, fallback = straight * 1.05, fallback + 1
            # never shorter than the straight line (snapping noise), which keeps the A* heuristic admissible
            best = math.ceil(max(best, straight) * 1e4) / 1e4  # round UP so rounding never breaks the bound
            edges.append({"line": line, "a": a, "b": b, "km": best, "straight_km": round(straight, 4)})
    log.add(f"track distances: {len(edges)} consecutive pairs, {fallback} used straight-line x1.05 fallback")
    return edges


def load_ridership(st: pd.DataFrame, log: CleanLog) -> pd.DataFrame:
    """Typical daily trips per station + April-2024 vulnerability signal."""
    r = pd.read_csv(_f("metro_passengers_trips_by_station_monthly_"))
    n0 = len(r)
    r["name"] = r.metro_station.map(clean_name)
    r = r.drop_duplicates(["name", "year", "month", "trips"])
    log.add(f"ridership: {n0} rows, {n0 - len(r)} exact duplicates (same station/month/trips) dropped")
    unmatched = set(r.name) - set(st.name)
    log.add(f"ridership names not in stations file (legacy, pre-2021, kept out of the network): {sorted(unmatched)}")
    assert unmatched <= LEGACY_RIDERSHIP, unmatched

    # From mid-May 2024 the file holds ~daily snapshots, so one row = one day's trips.
    y = CFG["data"]["ridership_baseline_year"]
    daily = r[r.year == y].groupby("name").trips.median().rename("daily_trips")

    # Vulnerability: how much more did a station's April-2024 ridership drop (vs March) than the network?
    m24 = r[(r.year == 2024) & r.month.isin(["Mar", "Apr"])].groupby(["name", "month"]).trips.max().unstack()
    ratio = m24.Apr / m24.Mar
    rel = ratio / (m24.Apr.sum() / m24.Mar.sum())
    vuln = ((1 - rel) / 0.6).clip(0, 1).rename("vulnerability")
    out = pd.concat([daily, vuln, ratio.rename("apr_mar_2024")], axis=1)
    log.add(f"network-wide April/March 2024 ridership ratio: {m24.Apr.sum() / m24.Mar.sum():.3f}")
    return out


def load_bus_stops(log: CleanLog) -> list[dict]:
    """Unique bus stops with coordinates (2020 + 2021 snapshots of the routes/stops file)."""
    b = pd.read_csv(_f("public_transportation_routes_stops_"), low_memory=False)
    b = b[(b.transport_mode == "Bus")].dropna(subset=["stop_location_latitude", "stop_id"])
    # Dubai bounding box: drops stray coordinates
    b = b[b.stop_location_latitude.between(24.7, 25.5) & b.stop_location_longitude.between(54.8, 55.7)]
    # stop_id is NOT a unique stop in this file (728 ids carry several names / far-apart coordinates);
    # stop_name always has one consistent coordinate, so it is the key.
    ids = b.groupby("stop_id").stop_name.nunique()
    log.add(f"bus stops: stop_id is not unique ({int((ids > 1).sum())} of {len(ids)} ids map to several "
            f"stop names), so stops are keyed by name")
    b = b.dropna(subset=["stop_name"])
    g = b.groupby("stop_name").agg(lat=("stop_location_latitude", "median"), lon=("stop_location_longitude", "median"),
                                   routes=("route_name", "nunique"))
    log.add(f"bus stops: {len(g)} unique named stops with coordinates from {b.route_name.nunique()} bus routes")
    g = g.reset_index().rename(columns={"stop_name": "name"})
    g["stop_id"] = [f"b{i}" for i in range(len(g))]
    return json.loads(g.round(6).to_json(orient="records"))


def build(force: bool = False) -> dict:
    """Build (or load cached) network description."""
    out_dir = os.path.join(ROOT, CFG["data"]["processed_dir"])
    path = os.path.join(out_dir, "network.json")
    if os.path.exists(path) and not force:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    log = CleanLog()
    st = load_stations(log)
    order = load_line_order(st, log)
    parts = load_kml()
    edges = track_distances(st, order, parts, log)
    rid = load_ridership(st, log)
    st = st.join(rid, on="name")
    missing = st[st.daily_trips.isna()].name.tolist()
    if missing:
        log.add(f"no {CFG['data']['ridership_baseline_year']} ridership for {missing}: using network median")
    st["daily_trips"] = st.daily_trips.fillna(st.daily_trips.median()).round()
    st["vulnerability"] = st.vulnerability.fillna(st.vulnerability.median())
    st["id"] = range(len(st))
    on_line = {n for names in order.values() for n in names}
    assert on_line == set(st.name), f"stations missing from line order: {set(st.name) - on_line}"

    geom = []
    for p in parts:  # simplify for drawing: keep every ~25th vertex
        keep = p[:: max(1, len(p) // 400)]
        keep = np.vstack([keep, p[-1:]])
        geom.append(np.round(keep, 6).tolist())

    net = {
        "stations": json.loads(st.to_json(orient="records")),
        "lines": order,
        "edges": edges,
        "track_geometry": geom,
        "bus_stops": load_bus_stops(log),
        "report": log.entries,
    }
    os.makedirs(out_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(net, fh)
    return net


if __name__ == "__main__":
    n = build(force=True)
    print("\n".join(n["report"]))
    print({k: len(v) for k, v in n["lines"].items()}, "stations:", len(n["stations"]))
