# Private server intelligence: coverage heatmap + player name history

The private local dashboard combines observed map coverage with a searchable
player directory and historical names tied to each stable player ID.

**No roster is uploaded to the GitHub Pages website.** HTML, SQLite and CSV
outputs are stored under Git-ignored network_scans/. The dashboard is a
standalone file and does not make web requests.

## What it shows

- Density heatmap of observed player bases across S125 X/Y coordinates
- Sampled map-view centers from live captures and automatic minimap jumps
- Source filters: original scan only / both scans / automated scan only
- Suggested cells to verify, ranked by distance to *recorded view centers*
- Failed minimap targets needing a retry
- Search by current player name, **past observed names**, guild tag, or stable ID
- Player details: latest recorded name, ID, guild, level and X/Y
- **Observed name history:** timestamped scan snapshots for each distinct name
- "Renamed only" filter and map highlight for the selected player

View-center positions are only **sampling evidence**. An empty or remote cell is
not proof that the game loaded the entire region or that bases are missing.
The decoder does not establish exact viewport bounds.

## Generate the private dashboard

From the Z-Route repository root:

~~~powershell
git switch dev
git pull origin dev
python network_scan/coverage_report.py
start .\network_scans\coverage\coverage.html
~~~

The tool automatically reads:
- network_scans/combined_players.csv (merged 9,777-base snapshot)
- the largest network_scans/live/<session>/players.csv and its views.csv
- network_scans/full_map/players.csv and checkpoint.json
- all available live sessions and full-map CSVs, imported as historical snapshots

The report writes:
- network_scans/coverage/coverage.html — interactive private dashboard
- network_scans/coverage/coverage_cells.csv — aggregate cells
- network_scans/coverage/review_candidates.csv — sampling-priority suggestions
- network_scans/coverage/failed_minimap_targets.csv — failed clicks
- network_scans/coverage/summary.json — counts and evidence limitations
- network_scans/player_history.sqlite3 — persistent name/identity observations

Optional flags: --grid 30 (finer map), --top 40 (more review suggestions),
--bounds XMIN YMIN XMAX YMAX, --server 125.

## Stable IDs and name changes

The identity key is **server + player_id**, e.g. "125:137434890365".
A player named "OldName" and later "NewName" with the same ID is a single
player. We retain BOTH names, plus the source snapshot and approximate
observation time. Search results match former names and show the current
record from the merged roster.

This is *observation history*, **not** game-provided name-change events.
We can say "we observed name A in a saved capture, then name B later", not
"the user changed names at this exact instant". Earlier names already
overwritten before any capture or import are not recoverable from the
current roster alone. We do not use names as unique identifiers.

Current and future scan inputs:

- The coverage report imports source CSV snapshots automatically when run.
- Recurring scan folders under `network_scans/map_refresh/*/players.csv` are now included in automatic history discovery.
- All repeated full-map runs write to the **same** `network_scans/player_history.sqlite3`, no matter the session output folder. Each click saves its player names **before** the checkpoint is advanced; a history write failure stops the scan instead of proceeding silently.
- The `scan_changes.py` utility treats renames as the **priority result**, producing `renames.csv` for the two compared snapshots and `all_name_changes.csv` for every recorded alias transition.
- live_watch.py records identity observations from each new decoded capture.
- full_map_scan.py records identity observations after each map-jump capture.
- Repeating sync/import of an unchanged capture is idempotent.
- Existing per-capture history remains in SQLite even if later roster CSVs
  overwrite the latest name.

Inspect a specific player:

~~~powershell
python network_scan/player_history.py sync
python network_scan/player_history.py show --id 125:137434890365
~~~

Add a manually saved older roster snapshot before it disappears:

~~~powershell
python network_scan/player_history.py sync --file "C:\path\to\older_players.csv"
~~~

Export machine-readable histories:

~~~powershell
python network_scan/player_history.py export
python network_scan/player_history.py renames
~~~

You can back up network_scans/player_history.sqlite3 to keep older aliases
even after original PCAPNGs or CSVs are removed.

## Troubleshooting

- **"Missing combined_players.csv":** run
  python network_scan/compare_player_sessions.py --write-merged network_scans/combined_players.csv
- **"0 observed renames":** no differently named snapshots were yet observed
  for the same stable player ID. Two scans can both have identical names.
- **Missing view centers:** ensure the selected live session has views.csv,
  or pass --views "path/to/views.csv".
- **Player names change in game but not dashboard:** run another live scan
  while the player appears in map responses, then regenerate the report.
  Scanner data and local HTML are not continuously synchronized.
- **Slow report generation:** start with default --grid 24; reduce for
  coarser cells. Keep the history DB private.
- **No older names available:** the merged CSV is only a latest snapshot,
  not a time machine; saved older captures or CSV snapshots are required.

## Offline regression checks

~~~powershell
python -m unittest discover -s network_scan -p test_player_history.py
~~~
