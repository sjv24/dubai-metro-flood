# Dubai Metro Flood Response AI

AI decision support for Dubai Metro station closures in heavy rain. Real RTA open data drives the
simulated scenario. CSCI218 Foundations of AI (UOWD).

> **Simulated scenario on real RTA open data.** The crowd numbers are modelled, not measured. The
> "2024-style response" (the baseline) is a *model* of the April 2024 response, not the measured 2024 outcome.

## Setup and run

Developed and tested with **Python 3.11.9** (any 3.11.x should work). All package versions are
pinned in `requirements.txt`. Run every command from the project root.

**Windows (PowerShell or cmd):**
```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn src.api.app:app --port 8000
```

**macOS / Linux:**
```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn src.api.app:app --port 8000
```

Then open **http://localhost:8000** for the guided story ("16 April 2024, Replayed": the 2024-style
response → the AI's decisions → rerun with AI → comparison), or **http://localhost:8000/explorer**
for the algorithm explorer (one tab per technique, with its maths and live numbers). The server
precomputes every preset in the background.

In the commands below, `python` means the virtual environment's interpreter: `.venv\Scripts\python`
on Windows, `.venv/bin/python` on macOS/Linux.

| What | Command | Output |
|---|---|---|
| Tests (43) | `python -m pytest -q tests` | |
| **All experiments, tables and figures** (30 seeds) | `python scripts/run_all.py` | `results/`, `results/figures/` |
| Multi-seed experiments only | `python scripts/run_experiments.py --seeds 30` | `results/runs.csv`, `summary.csv`, `comparison.csv`, `ga_runs.csv`, `ga_curves.csv` |
| Flood-model validation vs the real closures | `python scripts/validate_calibration.py` | `results/calibration*.csv` |
| A* vs Dijkstra, 200 random trips | `python scripts/benchmark_search.py` | `results/search_benchmark.csv`, `search_summary.csv` |
| GA tuning check / overload ablation | `python scripts/tune_ga.py` · `python scripts/ablate_ga_overload.py` | `results/ga_tuning.csv`, `ga_overload_ablation.csv` |
| Sensitivity (give-up rate, capacity) | `python scripts/run_sensitivity.py` | `results/sensitivity.csv` |
| Figures | `python scripts/make_figures.py` | `results/figures/*.png`, `results/ga_summary.csv` |

Every parameter and assumption is in `experiments/config.yaml` (justified in `docs/assumptions.md`).
Seeds are 0–29, and a run with the same seed and config gives identical results.

## How it works

Three AI techniques: **fuzzy logic**, **A\* search** and a **genetic algorithm**. The flood model,
the queue model and the bus-bridge design are parts of the simulation and of the response design;
the bus design is evaluated with A\*.

```
data/ (8 RTA files) ─► src/core/data.py ─► network.json (53 stations, track km, ridership, bus stops)
                                       │
storm preset ─► src/core/flood.py ─► src/sim/closures.py   (replay: the 4 real closures, flood-timed)
                                       ▼
          src/sim/state.py: everything per closure state (cached), for both policies
   ┌──────────── 2024-style response (model) ────────────┬──────────────────── AI response ─────────────────────┐
   │ one shuttle per break, fleet split equally          │ bus design scored with crowd-aware A* (terminals.py) │
   │ help only at the shuttle ends                       │ 5 relief hubs placed by the GA (hubs.py, ga.py)      │
   │ plain shortest-path routing (assignment.py)         │ crowd-aware A*, incremental assignment               │
   │ staff in line order                                 │ staff by fuzzy priority (fuzzy.py)                   │
   └─────────────────────────────────────────────────────┴──────────────────────────────────────────────────────┘
                                       ▼
   src/sim/metrics.py: every 15 min, loads, queues and give-ups, fuzzy priority, metrics
                                       ▼
   src/sim/engine.py (run) ─► src/api/app.py ─► frontend: story (/) and explorer (/explorer)
```

| Module | What it does |
|---|---|
| `src/ai/fuzzy.py` | **Fuzzy logic:** Mamdani, 4 inputs (crowding ratio, flood level, interchange, stops to closure), 17 rules, min/max inference, centroid defuzzification, giving a priority of 0–100. Drives staff dispatch and the GA's urgency term. |
| `src/ai/search.py` | **A\* and Dijkstra**, written from scratch. h(n) = straight-line km to the goal ÷ the fastest mode's speed. **Admissible:** every edge costs at least its straight-line length ÷ v_max (track is never shorter than the straight line; walking and buses are slower and add waits). Crowd-aware variant: + expected queue wait when boarding. |
| `src/ai/ga.py` | **Genetic algorithm:** choose 5 relief hubs from about 225 open stations and real bus stops. Set chromosome, tournament selection, set-preserving crossover, swap mutation with repair, elitism. Compared with greedy and random placement. |
| `src/sim/terminals.py` | Bus-bridge design (end stations + optional split shuttle), with every candidate scored by routing all passengers with crowd-aware A\*. |
| `src/core/flood.py` | Moving storm cell, water = rain × susceptibility − drainage. Susceptibility from the observed April 2024 ridership drop. Threshold and drainage calibrated by grid search. |

## Results (30 runs, mean ± std)

Every number below comes from `results/comparison.csv` (seeds 0–29, both policies simulated under
identical storm, closures, demand and bus fleet). "AI better" = runs where the AI beat the
2024-style response. Figures are in `results/figures/`.

**16 April 2024 replay** (the four real closures):

| Metric | 2024-style (modelled) | AI | Change | AI better |
|---|---|---|---|---|
| People who gave up on the metro | 20,020 ± 1,449 | **8,239 ± 3,021** | −59% | 30/30 |
| Hours spent queuing | 16,683 ± 1,208 | **6,866 ± 2,517** | −59% | 30/30 |
| Peak queue at the worst station (Business Bay) | 4,413 ± 227 | **2,181 ± 608** | −51% | 29/30 |
| Peak crowding ratio | 4.13 ± 0.16 | **2.55 ± 0.43** | −38% | 29/30 |
| Stranded passengers within 10 min of relief | 2.4 ± 0.7% | **98.8 ± 0.1%** | +96 pts | 30/30 |
| Critical stations staffed | 80.8 ± 2.2% | **100.0 ± 0.0%** | +19 pts | 30/30 |
| Average extra trip time | **36.1 ± 0.8 min** | 38.6 ± 0.8 min | +7% (worse) | 0/30 |
| 95th percentile extra trip time | **51.5 ± 0.1 min** | 69.4 ± 3.0 min | +35% (worse) | 0/30 |
| Unserved trips | **0.0%** | 1.0 ± 0.6% | worse | 0/30 |

**Other scenarios, people who gave up (30 runs each):**
- Extreme storm: 90,999 ± 29,467 → **46,894 ± 13,631** (−48%, 30/30). Unserved trips 1.3% → 4.1% (worse).
- Interchange failure (BurJuman): 16,693 ± 1,785 → **11,366 ± 2,529** (−32%, 30/30).
- Random closures: 35,381 ± 28,040 → **12,399 ± 11,933** (−65%, 30/30).
- Moderate storm: no station closes, so the two policies are identical.

**Where the AI is worse, and why:** the AI shares the same 30 buses by demand × route length, so the quiet
Energy branch (Energy, Danube, UAE Exchange) gets very few buses (one every 29–37 min at seed 42). Its
bus-design objective also trades trip time for less crowding. So people who *do* travel take a little
longer, and a small share of trips exceed 150 minutes. See `docs/REPORT_OUTLINE.md` (Limitations).

**Baselines and checks:**
- **A\* vs Dijkstra**, 200 random trips on the disrupted network (`results/search_summary.csv`):
  - A\* expands 39.9 ± 28.0 nodes vs 54.6 ± 28.0 (30% ± 20% fewer).
  - The optimal cost was identical on 200/200 trips (also equal to networkx).
  - Wall-clock time is similar (0.12 vs 0.08 ms) on this 105-node graph.
- **GA vs greedy vs random**, 30 runs (`results/ga_summary.csv`, `results/figures/ga_convergence.png`):
  - Replay: GA 1.410 ± 0.014, greedy 1.409 ± 0.012, random 0.595 ± 0.232.
  - GA ≥ greedy in 27/30 runs (random closures 28/30, strictly better in 24).
  - Population and generations were chosen by `scripts/tune_ga.py` and confirmed on held-out seeds.
- **Flood-model validation** (the replay forces the real closures; this checks the model on its own,
  `results/calibration_seeds.csv`):
  - Precision 0.958 ± 0.095, recall 0.742 ± 0.046 over 30 runs.
  - It finds Onpassive, Equiti and Mashreq, and misses Energy.
- **Sensitivity** (give-up rate 0.2/0.3/0.4, capacity factor 1.2/1.3/1.5): `results/sensitivity.csv`.
  Under all 6 settings, the AI still beats the 2024-style response on people who gave up (in 28–30 of
  30 runs per setting), hours queuing, peak queue, relief coverage and staffing. It is still worse on
  average and 95th-percentile trip time and on unserved trips in all 6. The conclusion does not hinge
  on these two assumptions.
- **GA overload-penalty ablation** (`results/ga_overload_ablation.csv`, extreme storm, 30 runs):
  without the penalty, 27 of 150 chosen hubs sit at overcrowded stations (in 21 runs), against 14 (in
  12 runs) with it, at the same coverage. So both fitness terms are kept.

## Key data facts found

- April vs March 2024 ridership: Equiti (First Abu Dhabi Bank) fell to 34%, Mashreq 36%, Onpassive
  (Noor Bank) 41%, Energy 55%, against 71% network-wide.
- Ridership is monthly up to April 2024 and about daily from mid-May 2024.
- The capacity file has swapped columns in its 2022+ rows. A Metro train carries 643 passengers (5 cars).
- Energy is **not** between Business Bay and Al Khail. 2024 had two separate breaks.
- Full data notes: `data/README.md`. Every assumption: `docs/assumptions.md`.

## Documentation

| File | Contents |
|---|---|
| `docs/ALGORITHMS.md` | The three AI techniques: maths, worked examples, results |
| `docs/DEMO_SCRIPT.md` | What to say in each story chapter |
| `docs/PITCH_GUIDE.md` | Plain-language walkthrough of the data, build steps and algorithms |
| `docs/REPORT_OUTLINE.md` | Report structure, mapped to files, tables and figures |
| `docs/assumptions.md` | Every assumption, its value and its justification |
| `data/README.md` | Data sources, contents and quality issues |

## Limitations (short)

- The flood-vulnerability signal is partly circular: those stations' ridership fell partly because they closed.
- The 2024-style response is our model, not measured 2024 data.
- The give-up rate, capacity proxy, speeds and fleet size are assumptions (`docs/assumptions.md`).
- The AI is worse on trip time for those who travel, and on unserved trips, in the replay.
- See `docs/REPORT_OUTLINE.md` §(g).
