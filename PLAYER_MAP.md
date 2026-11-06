# Z-Route Player Locator — Exact World Coordinates

The GitHub Pages site at repository root (index.html) now uses **real Z-Route world X/Y** from passively decoded WorldMapViewS2C player records. It does **not** load or draw the legacy vision scanner swipe-grid CSV. Every position uses a stable (server, player_id) identity; same-name players stay distinct. Game-world **Y increases upward**, matching the game map.

Features: username search, alliance/guild filter, slider to select a **base level range**, shield status filter (with stale/unknown states), X/Y world grid lines, exact coordinates in tooltip and details, map zoom/pan and guild colors. The map automatically frames the **observed coordinate extent**; its edges are not claimed to be the whole server's boundaries. A coordinate from an old scan remains a **last recorded** position, not a real-time location guarantee.

## Data source and deploying your complete roster

The committed data/world-players.csv is a **starter set of 25 network-verified S125 world-coordinate records** from the previously supplied shield investigation. Several of those do not have base levels or alliance names; those values are intentionally left blank, not guessed. To replace it with the full exact-coordinate roster from your local scans, from the repo root in PowerShell run:

~~~powershell
git switch dev
git pull origin dev

python network_scan/compare_player_sessions.py --write-merged network_scans/combined_players.csv
python network_scan/export_world_map.py
python -m unittest discover -s network_scan -p test_export_world_map.py
~~~

export_world_map.py reads network_scans/combined_players.csv (or a custom --roster), preserves exact server,x,y,player_id,username,alliance_tag,base_level and merges recent shield-status observations by stable player ID. Missing or outdated shield status becomes unknown. The exported CSV is saved at data/world-players.csv. It does not copy or calculate the old row,col,view swipe-grid coordinates.

Review the CSV before committing; publishing a GitHub Pages site can expose player coordinates. To publish the full dataset to the dev branch:

~~~powershell
git add data/world-players.csv
git commit -m "Refresh exact S125 world map coordinates"
git push origin dev
~~~

In GitHub **Settings → Pages**, select **Deploy from a branch**, then select the branch the website should use and **/(root)**. If Pages is set to dev, the refreshed CSV/site should deploy from that branch. If Pages serves another branch, merge the relevant changes there first.

For a local preview, start python -m http.server 8000 at the repository root and open http://localhost:8000 in a browser.

## Username history and rename search

**Names can change; player IDs cannot be substituted with usernames as database keys.**
The world-map CSV exporter on dev joins the private append-only
`network_scans/player_history.sqlite3` database by stable
`(server, player_id)`. It publishes these optional fields alongside each player:

- `known_aliases_json`: every username previously observed for this player ID
- `observed_name_changes`: count of observed transitions (including changes back to an older name)
- `name_history_json`: the old and new names and when each transition was first observed
- `name_observed_at_utc`: most recent name observation, which can be newer than the roster's saved coordinates

The map's search input matches **current and past usernames**. Select
**Renamed only** to highlight people with at least one observed change,
then click a player to view their known aliases and chronological
old-name → new-name observations. The approximate observed timestamps
are NOT the exact time of a rename.

**Privacy:** publishing `data/world-players.csv` to GitHub Pages can
make this full alias history public, along with player coordinates.
Review the CSV before committing it. The persistent SQLite file remains
local under git-ignored `network_scans/`. The 25-row starter
sample has no collected rename history; the alias filter becomes meaningful
after you run the full local export and publish the refreshed CSV.

## Level and shield filters

The two-handle **Base level** control reads the exact network roster's base_level column and works alongside username and guild filters. The range starts at Lv 1 to at least Lv 30 (or the highest observed level). Players with missing levels stay visible with the full range, but are hidden if you narrow either bound. **Clear filters** restores the full range.

The shield selector uses the project's accepted decoded player-detail **field 9** mapping (1 = shielded; absent = unshielded; other values = unknown) for **complete player records**. Historical observations older than the export's 60-minute default threshold display **Unknown / stale**; a missing record never implies unshielded.

## Watchers, Trucks and SpecOps

These categories are visible on another game's World Map UI, but they are **not yet identified** in our passive S125 `WorldMapViewS2C` data. Our decoder already records non-player objects, raw type codes, subtypes, last-observed in-game X/Y, and client-visual matching evidence. Do not label type `3`, `5`, `6`, or negative codes as a Watcher, Truck or SpecOps solely because they occur near one.

**Coordinate alignment:** the GitHub Pages map now uses exact passive-network world X/Y, so a Watcher, Truck or SpecOps object can share the same coordinate system once its type and identity are verified. We have **not** confirmed the required non-player type/subtype codes, so those layers are not yet published. Don't infer type identity by proximity alone.

For the next capture, keep the passive network watcher running while visually locating an object, then use `network_scan/live_entity_watch.py near --server 125 --x X --y Y --radius 5`. If there is exactly one object at its verified coordinate, use `match --server 125 --x X --y Y --radius 0 --label Watcher` (or Truck/SpecOps). Multiple independent examples will establish the kind/type/subtype schema before we publish those tabs. See `network_scan/LIVE_ENTITY_WATCH.md` and `network_scan/MAP_ENTITY_DISCOVERY.md`.

