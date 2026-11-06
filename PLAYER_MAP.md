# Z-Route Player Locator

Static GitHub Pages site at repository root (`index.html`). It loads `data/players.csv` using fetch and displays every player by default. Features: username search, guild dropdown, clickable guild legend sorted by count, consistent guild colors, hover tooltips, click-to-pin details, wheel zoom and drag pan.

## Base-level range filter

The GitHub Pages player map now has a two-handle **Base level** slider like the sample World Map screenshot. It reads the existing `level` column in `data/players.csv` and works alongside username search and guild filtering. The range starts at **Lv 1 to the greater of Lv 30 and the highest observed player level**; both ends can be adjusted independently, and **Clear filters** resets them. Moving the range immediately updates the displayed player count, map markers, guild selection, and selected player details.

Players with empty/unparseable levels remain visible with the full default range and are hidden when any level bound is narrowed. This prevents a missing level from being treated as level 0 or a verified value. No scanner or CSV changes are required.

## Watchers, Trucks and SpecOps

These categories are visible on another game's World Map UI, but they are **not yet identified** in our passive S125 `WorldMapViewS2C` data. Our decoder already records non-player objects, raw type codes, subtypes, last-observed in-game X/Y, and client-visual matching evidence. Do not label type `3`, `5`, `6`, or negative codes as a Watcher, Truck or SpecOps solely because they occur near one.

**Coordinate warning:** this GitHub Pages base map uses **approximate scanner swipe-grid columns and rows**, while network-derived non-player objects use **actual game world X/Y**. They cannot safely be overlaid until the page uses a common, verified coordinate system. No Watcher/Truck/SpecOps layers have been invented or shown as confirmed.

For the next capture, keep the passive network watcher running while visually locating an object, then use `network_scan/live_entity_watch.py near --server 125 --x X --y Y --radius 5`. If there is exactly one object at its verified coordinate, use `match --server 125 --x X --y Y --radius 0 --label Watcher` (or Truck/SpecOps). Multiple independent examples will establish the kind/type/subtype schema before we publish those tabs. See `network_scan/LIVE_ENTITY_WATCH.md` and `network_scan/MAP_ENTITY_DISCOVERY.md`.

## Deploy

In GitHub **Settings → Pages**, select **Deploy from a branch**, choose the branch containing the site and **/(root)**. The site URL should be `https://tannerr12.github.io/Z-Route/` once Pages finishes publishing. If publishing from `dev`, select `dev`; otherwise merge these files to the publishing branch.

## Replace demo data

Copy your scanner's latest `exports/players/serpentine_players_*.csv` to `data/players.csv`, then commit and push. Expected columns: `username,guild,level,row,col,view,direction,observed_at,coordinate_type`. CSV quoting (including quoted commas in names) is supported. The website does not write to CSV. Never publish screenshots, configuration or private keys inadvertently.

**Important:** scanner columns are zero-based, and the downward row value is calculated using a 150-swipe maximum. The site maps columns to 1–150 and recomputes downward rows as `60 - view` to fit the **assumed** 60-row map. These positions are approximate, not validated game coordinates. Change the grid dimensions/normalization after calibrating actual map bounds; rows outside the display are clamped. A player may be duplicated in source CSV; the newest `observed_at` record wins.

To test locally, serve the repository root over HTTP (not `file://`), e.g. `python -m http.server 8000` and open `http://localhost:8000`.
