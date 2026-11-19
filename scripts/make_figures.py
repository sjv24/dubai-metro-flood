"""Figures and summary tables from the CSVs in results/ (run the experiment scripts first).

Usage:  python scripts/make_figures.py
Writes: results/ga_summary.csv and results/figures/*.png
"""
from __future__ import annotations

import os

from _common import FIGURES, METRICS, RESULTS, ensure_dirs

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

BASE_C, AI_C = "#d9534f", "#7c5cd6"
plt.rcParams.update({"figure.dpi": 140, "font.size": 9.5, "axes.spines.top": False, "axes.spines.right": False})


def load(name: str) -> pd.DataFrame | None:
    p = os.path.join(RESULTS, name)
    return pd.read_csv(p) if os.path.exists(p) else None


def ga_figures() -> None:
    ga, curves = load("ga_runs.csv"), load("ga_curves.csv")
    if ga is None:
        return
    rows = []
    for sc, g in ga.groupby("scenario"):
        for m in ("ga", "greedy", "random"):
            rows.append({"scenario": sc, "method": m, "fitness_mean": g[m].mean(), "fitness_std": g[m].std(),
                         "covered_mean": g[f"covered_{m}"].mean(), "covered_std": g[f"covered_{m}"].std(),
                         "minutes_to_hub_mean": g[f"mean_min_to_hub_{m}"].mean(),
                         "minutes_to_hub_std": g[f"mean_min_to_hub_{m}"].std(), "n": len(g)})
        rows.append({"scenario": sc, "method": "GA >= greedy (seeds)", "fitness_mean": int((g.ga >= g.greedy - 1e-9).sum()), "n": len(g)})
        rows.append({"scenario": sc, "method": "GA > greedy (seeds)", "fitness_mean": int((g.ga > g.greedy + 1e-9).sum()), "n": len(g)})
    pd.DataFrame(rows).round(4).to_csv(os.path.join(RESULTS, "ga_summary.csv"), index=False)

    # convergence: best fitness per generation, mean +/- 1 std band over seeds, per scenario
    scen = [s for s in ("april_2024_replay", "extreme_storm") if s in set(curves.scenario)] or sorted(set(curves.scenario))
    fig, axes = plt.subplots(1, len(scen), figsize=(5.2 * len(scen), 3.6), squeeze=False)
    for ax, sc in zip(axes[0], scen):
        c = curves[curves.scenario == sc]
        for col, color, lab in (("best", AI_C, "GA best"), ("mean", "#b9a8ef", "GA population mean")):
            agg = c.groupby("generation")[col].agg(["mean", "std"])
            ax.plot(agg.index, agg["mean"], color=color, lw=2 if col == "best" else 1.4, label=lab)
            ax.fill_between(agg.index, agg["mean"] - agg["std"], agg["mean"] + agg["std"], color=color, alpha=0.18)
        g = ga[ga.scenario == sc]
        for m, color in (("greedy", "#e0a030"), ("random", "#8a96a8")):
            ax.axhline(g[m].mean(), color=color, ls="--", lw=1.3, label=f"{m} (mean)")
        ax.set_title(f"{sc.replace('_', ' ')}  (n = {c.seed.nunique()} seeds, band = ±1 std)")
        ax.set_xlabel("generation"); ax.set_ylabel("fitness F(H)")
        ax.legend(frameon=False, fontsize=8, loc="lower right")
    fig.tight_layout(); fig.savefig(os.path.join(FIGURES, "ga_convergence.png")); plt.close(fig)

    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    scs = sorted(set(ga.scenario)); x = np.arange(len(scs)); w = 0.26
    for k, (m, color) in enumerate((("ga", AI_C), ("greedy", "#e0a030"), ("random", "#8a96a8"))):
        means = [ga[ga.scenario == s][m].mean() for s in scs]
        stds = [ga[ga.scenario == s][m].std() for s in scs]
        ax.bar(x + (k - 1) * w, means, w, yerr=stds, color=color, label=m.upper() if m == "ga" else m, capsize=3)
    ax.set_xticks(x, [s.replace("_", "\n") for s in scs], fontsize=8); ax.set_ylabel("fitness (mean ± std)")
    ax.legend(frameon=False); ax.set_title("Hub placement: GA vs greedy vs random")
    fig.tight_layout(); fig.savefig(os.path.join(FIGURES, "ga_vs_baselines.png")); plt.close(fig)


def policy_figure() -> None:
    cmp = load("comparison.csv")
    if cmp is None:
        return
    keys = ["gave_up", "waiting_person_hours", "worst_station_waiting", "avg_extra_min", "covered_pct", "unserved_pct"]
    scs = [s for s in ("april_2024_replay", "extreme_storm", "interchange_failure", "random_closures") if s in set(cmp.scenario)]
    fig, axes = plt.subplots(len(scs), len(keys), figsize=(2.3 * len(keys), 2.1 * len(scs)), squeeze=False)
    for r, sc in enumerate(scs):
        for c, m in enumerate(keys):
            ax = axes[r][c]
            row = cmp[(cmp.scenario == sc) & (cmp.metric == m)]
            if row.empty:
                ax.axis("off"); continue
            row = row.iloc[0]
            ax.bar([0, 1], [row.baseline_mean, row.ai_mean], yerr=[row.baseline_std or 0, row.ai_std or 0],
                   color=[BASE_C, AI_C], capsize=3, width=0.6)
            ax.set_xticks([0, 1], ["2024", "AI"], fontsize=8)
            if r == 0:
                ax.set_title(METRICS[m][0].replace(" (", "\n("), fontsize=8)
            if c == 0:
                ax.set_ylabel(sc.replace("_", "\n"), fontsize=8)
            ax.tick_params(axis="y", labelsize=7)
    fig.suptitle("2024-style response vs AI (mean ± std over seeds)", fontsize=10)
    fig.tight_layout(); fig.savefig(os.path.join(FIGURES, "policy_comparison.png")); plt.close(fig)


def search_figure() -> None:
    df = load("search_benchmark.csv")
    if df is None:
        return
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.4))
    ax = axes[0]
    ax.scatter(df.expanded_dijkstra, df.expanded_astar, s=12, alpha=0.6, color="#22a6c7")
    lim = max(df.expanded_dijkstra.max(), df.expanded_astar.max()) + 5
    ax.plot([0, lim], [0, lim], color="#999", ls="--", lw=1); ax.set_xlim(0, lim); ax.set_ylim(0, lim)
    ax.set_xlabel("Dijkstra: nodes expanded"); ax.set_ylabel("A*: nodes expanded")
    ax.set_title(f"{len(df)} random trips (all below the line = A* never worse)", fontsize=9)
    ax = axes[1]
    ax.boxplot([df.ms_dijkstra, df.ms_astar], tick_labels=["Dijkstra", "A*"], showfliers=False)
    ax.set_ylabel("runtime per search (ms, best of 5)"); ax.set_title("Wall-clock time on this 105-node graph", fontsize=9)
    fig.tight_layout(); fig.savefig(os.path.join(FIGURES, "search_benchmark.png")); plt.close(fig)


def sensitivity_figure() -> None:
    df = load("sensitivity_runs.csv")
    if df is None:
        return
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.4))
    for ax, (param, label) in zip(axes, (("crowd.abandon_per_step", "give-up rate per 15 min"),
                                         ("capacity.station_capacity_factor", "capacity factor"))):
        d = df[df.param == param]
        for pol, color in (("baseline", BASE_C), ("ai", AI_C)):
            g = d[d.policy == pol].groupby("value").gave_up.agg(["mean", "std"])
            ax.errorbar(g.index, g["mean"], yerr=g["std"], marker="o", color=color, capsize=3,
                        label="2024-style" if pol == "baseline" else "AI")
        ax.set_xlabel(label); ax.set_ylabel("people who gave up (mean ± std)"); ax.legend(frameon=False)
    fig.suptitle("Sensitivity of the April 2024 replay to two assumptions", fontsize=10)
    fig.tight_layout(); fig.savefig(os.path.join(FIGURES, "sensitivity.png")); plt.close(fig)


def main() -> None:
    ensure_dirs()
    ga_figures(); policy_figure(); search_figure(); sensitivity_figure()
    print("figures:", sorted(os.listdir(FIGURES)))


if __name__ == "__main__":
    main()
