# Assumptions

Every value the RTA data does not give us is listed here with its value, where it lives, and why we
chose it. Values tagged `ASSUMPTION` in `experiments/config.yaml` come first. Other modelling choices
follow, so nothing is hidden. Change any value in the config and rerun the scripts; nothing is
hardcoded in the results.

The two assumptions with the biggest effect on the headline numbers (the give-up rate and the
capacity proxy) are tested in a sensitivity analysis: `scripts/run_sensitivity.py` →
`results/sensitivity.csv`.

## Tagged `ASSUMPTION` in config.yaml

| Parameter (config key) | Value | Justification |
|---|---|---|
| Metro average speed `network.metro_speed_kmh` | 37 km/h | Typical average for Dubai Metro including station stops. Gives realistic end-to-end Red Line times. Checked against our KML track lengths (Green 22.2 km vs official 22 km). |
| Street ↔ platform time `network.entry_exit_min` | 2 min | Walking from street to platform. A line change = exit + entry = 4 min, a common transfer penalty. |
| Walking speed `network.walk_speed_kmh` | 5 km/h | Standard pedestrian speed. |
| Walking detour `network.walk_detour` | 1.3 | Street distance ÷ straight-line distance. Streets are not straight; 1.2–1.4 is a common urban range. |
| Shuttle bus speed `network.bus_speed_kmh` | 25 km/h | Below normal bus speed, for storm traffic and flooded roads. |
| Road detour `network.road_detour` | 1.4 | Road distance ÷ straight-line distance for shuttles. Higher than walking because buses follow major roads. |
| Hourly demand profile `time.hourly_profile` | 05:00–23:00 shares, peaks 0.095 at 08:00 and 0.088 at 18:00 | RTA publishes only daily and monthly totals. The two peaks follow RTA's stated peak hours (7:00–9:30 and 17:00–20:30) when it asked the public to avoid the metro in April 2024. The shares sum to 1. |
| Station capacity proxy `capacity.station_capacity_factor` | 1.3 × the station's busiest normal 15 minutes | RTA has no per-station capacity, only per train (643 passengers, 5 cars). A station normally copes with its own peak with some headroom, so 30% headroom. **Sensitivity-tested at 1.2, 1.3 and 1.5.** |
| Give-up rate `crowd.abandon_per_step` | 30% of queued people per 15 min | People don't queue forever; some take a taxi, walk or cancel. Turns crowding into a count of people lost. No public data. **Sensitivity-tested at 0.2, 0.3 and 0.4.** |
| Shuttle fleet `policy.bus_fleet` | 30 buses | The same fleet for both responses, so only the decisions differ. The absolute number is not public. |
| Staff teams `policy.staff_teams` | 6 per step | The same for both responses: the 2024-style response sends them in line order, the AI by fuzzy priority. |
| Station display names (`src/core/data.py`) | Noor Bank = Onpassive, First Abu Dhabi Bank = Equiti, Nakheel = Al Khail, … | Renames reported in 2024 news, matched to our data by location. Only affects labels. |

## Other modelling choices (not tagged, but still choices)

| Choice | Value | Justification |
|---|---|---|
| Walking edges only below `network.walk_max_km` | 1.5 km | Longer walks are unrealistic in a storm. |
| Shuttle dwell per stop `network.bus_stop_dwell_min` | 1 min | Boarding time at each intermediate stop. |
| Rain falling everywhere `flood.background_share` | 0.25 | The 2024 storm was widespread, not one cell. |
| Rain noise `flood.rain_noise_sd` | lognormal σ = 0.15 | Station-to-station variation. Seeded, so reproducible. |
| Susceptibility floor `flood.susceptibility_floor` | 0.35 | Every station gets some water. Vulnerability adds the rest. |
| Vulnerability scale (`src/core/data.py`) | (1 − relative April drop) ÷ 0.6, clipped 0..1 | A 60% relative drop maps to full vulnerability (Equiti dropped about 52% relative to the network). |
| Flood threshold and drainage `flood.threshold_mm`, `flood.base_drainage_mmh` | 45 mm, 3 mm/h | **Calibrated, not chosen.** Grid search (`flood.calibrate`) so the flood model alone best reproduces the 2024 closures. See `results/calibration.csv`. |
| April 2024 replay closures `presets.april_2024_replay.force_closed` | exactly the 4 real stations | The replay uses the real closures. The storm only decides the timing: the first crossing of the threshold, or peak water for Energy, which never crosses. |
| Demand origin | median 2025 daily trips per station | A typical recent day. The 2025 data is daily, so the median is robust. |
| Planning moment | the busiest remaining 15 minutes after each closure | Routing and hub placement plan for the worst case of the rest of the day. |
| Destinations of stranded trips `crowd.displaced_dests_per_station` | 40 sampled trips per stranded station, proportional to daily demand | No origin-destination data is published. |
| Unserved threshold `crowd.unserved_max_min` | 150 min | A trip that takes longer counts as not served. |
| Queue wait charged to each trip | 15 min × (load ratio − 1) at the boarding station | Each full capacity's worth of people ahead of you is one more 15-minute slot. Charged to both responses. |
| Crowd-aware rounds `crowd.increments` | 5 | Incremental traffic assignment: loads are updated after each fifth of the trips. |
| Relief reach `policy.relief_radius_min` | 10 min | "Covered" = a relief hub within 10 minutes. |
| Bus terminal search reach `policy.terminal_reach` | 3 stops | Bounded search: at most 3 × 3 end pairs + 6 split options per break. |
| 2024-style shuttle stops at closed stations `policy.baseline_stops_at_closed` | true | The stronger, fairer baseline. Without it, almost everyone at closed stations would be unserved and the AI would look better than it is. |
| Number of relief hubs `ga.k` | 5 | |
| GA settings `ga.*` | population 100, 150 generations, tournament 3, crossover 0.9, mutation 0.2, elitism 2 | Population and generations raised from 60/80 after `scripts/tune_ga.py` showed the smaller budget sometimes fell short of greedy (`results/ga_tuning.csv`, confirmed on held-out seeds). |
| GA fitness weights `ga.w_priority`, `ga.w_overload`, `ga.w_time` | 0.5, 0.3, 0.5 | Coverage of stranded people is the main goal (weight 1). The other terms refine it. See `docs/ALGORITHMS.md` for why both the priority and overload terms are kept. |
| Fuzzy membership functions and 17 rules (`src/ai/fuzzy.py`) | see `docs/ALGORITHMS.md` | Hand-designed. Checked by range and monotonicity tests. |
