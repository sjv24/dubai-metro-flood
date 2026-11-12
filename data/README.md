# Raw data

All eight files are **open data published by Dubai's Roads and Transport Authority (RTA)** on the
Dubai open-data portal (Dubai Pulse / data.dubai). They are kept exactly as downloaded: the code
never modifies this folder. Cleaned and joined outputs are written to `data/processed/` (generated,
not tracked) by `src/core/data.py`.

The date and time in each filename are the export timestamp of the file as downloaded
(`YYYY-MM-DD_HH-MM-SS`). The code finds files by their prefix, so a newer export with the same
columns can replace an old one.

| File | Exported | Contents | Size |
|---|---|---|---|
| `metro_stations_2026-09-21_17-40-59_0001.csv` | 21 Sep 2026 | One row per station per line: English/Arabic name, location ID, latitude, longitude, opening date, fare zone | 55 rows × 10 cols |
| `metro_lines_2026-11-09_14-59-43_0001.csv` | 9 Nov 2026 | The two line names (Red, Green) | 2 rows |
| `rail_routes_2025-05-04_00-00-00.kml` | 4 May 2025 | Track geometry: 5 placemarks, 6 line strings, 16,372 GPS points | 613 KB |
| `metro_passengers_trips_by_station_monthly_2026-09-28_15-39-35_0001.csv` | 28 Sep 2026 | Trips per station, 2018 to Aug 2026 | 33,988 rows × 5 cols |
| `public_transportation_routes_stops_2025-11-04_16-14-30_0001.csv` | 4 Nov 2025 | Bus (and some marine, metro, tram) routes with ordered stops and stop coordinates; 2020, 2021 and 2022 snapshots | 18,448 rows × 27 cols |
| `dubai_metro_and_tram_capacity_2025-11-05_19-05-52_0001.csv` | 5 Nov 2025 | Cars per train and passengers per train, by year | 16 rows |
| `dubai_metro_network_length_red_line_2025-11-05_18-12-37_0001.csv` | 5 Nov 2025 | Red Line length by year | 15 rows |
| `dubai_metro_network_length_green_line_2025-11-05_18-09-55_0001.csv` | 5 Nov 2025 | Green Line length by year (also contains other rows) | 17 rows |

## What each file is used for

- **Stations:** station positions, which line(s) they're on, and which are interchanges (Union, BurJuman).
- **Rail routes (KML):** drawing the real track, and the **track distance** between neighbouring stations.
  Each station is snapped onto the track (within 300 m) and the distance is measured along it.
- **Ridership:** a typical day per station (median of the 2025 daily rows), and each station's flood
  vulnerability from its April-vs-March 2024 drop.
- **Routes and stops:** the **order of stations along each line** (from the 64 "Metro" rows), and real
  bus stops as candidate relief-hub sites.
- **Capacity and line lengths:** train capacity (643 passengers per 5-car train) and a sanity check
  of our track lengths (Green 22.2 km from the KML vs 22 km official).

## Data quality issues we found (and how the code handles them)

| File | Issue | Handling |
|---|---|---|
| Stations | BurJuman and Union are listed twice (once per line); 55 rows = 53 stations | Merged by cleaned name and marked as interchanges |
| Stations | Several old names (Noor Bank = Onpassive, First Abu Dhabi Bank = Equiti, Nakheel = Al Khail) | Kept as the data key; 2024 names shown alongside in the UI |
| Lines | No station order | Order taken from the routes file's metro rows |
| KML | Line pieces carry no line name; no tram geometry | Each piece is labelled Red or Green by which stations lie along it |
| KML | 1 of the 53 neighbouring station pairs can't be measured along the track | Straight line × 1.05 fallback (logged) |
| Ridership | **Format changes in 2024:** monthly totals up to April 2024, then about one row per day (labelled only by month) from mid-May 2024 | Detected from the load timestamps; monthly rows used for the March/April 2024 comparison, daily rows (median) for a typical day |
| Ridership | 1,794 exact duplicate rows | Dropped |
| Ridership | 4 legacy station names only before 2021 (Jumeirah Lakes Towers, Nakheel Harbour & Tower, Palm Deira, Sharaf DG) | Kept out of the network (logged) |
| Routes and stops | Metro rows use yet another naming (Al Safa, Umm Al Sheif, Sobha Realty, Centrepoint, "max", …) | Alias table; every alias matched to the stations file by coordinates (0 m apart) |
| Routes and stops | **`stop_id` is not a unique stop:** 728 IDs map to several different stop names, often far apart | Stops keyed by stop name, which always has one consistent location (2,682 named stops) |
| Routes and stops | Some metro rows have wrong coordinates (e.g. Discovery Gardens placed at Energy) | Station positions always taken from the stations file |
| Capacity | **Columns swapped** in rows from 2022 onward (643 cars and 5 passengers) | Read as 643 passengers per 5-car train |
| Line lengths | The "green line" file also contains Red, Tram and empty rows; Red is 52 km before 2021 and 67 km after (Route 2020) | Used for sanity checks only |

What the data does **not** contain (no elevation, per-station capacity, hourly ridership or
origin-destination flows) is covered by the assumptions in `docs/assumptions.md`.
