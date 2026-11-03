# Z-Route Player Locator

Static GitHub Pages site at repository root (`index.html`). It loads `data/players.csv` using fetch and displays every player by default. Features: username search, guild dropdown, clickable guild legend sorted by count, consistent guild colors, hover tooltips, click-to-pin details, wheel zoom and drag pan.

## Deploy

In GitHub **Settings → Pages**, select **Deploy from a branch**, choose the branch containing the site and **/(root)**. The site URL should be `https://tannerr12.github.io/Z-Route/` once Pages finishes publishing. If publishing from `dev`, select `dev`; otherwise merge these files to the publishing branch.

## Replace demo data

Copy your scanner's latest `exports/players/serpentine_players_*.csv` to `data/players.csv`, then commit and push. Expected columns: `username,guild,level,row,col,view,direction,observed_at,coordinate_type`. CSV quoting (including quoted commas in names) is supported. The website does not write to CSV. Never publish screenshots, configuration or private keys inadvertently.

**Important:** scanner columns are zero-based, and the downward row value is calculated using a 150-swipe maximum. The site maps columns to 1–150 and recomputes downward rows as `60 - view` to fit the **assumed** 60-row map. These positions are approximate, not validated game coordinates. Change the grid dimensions/normalization after calibrating actual map bounds; rows outside the display are clamped. A player may be duplicated in source CSV; the newest `observed_at` record wins.

To test locally, serve the repository root over HTTP (not `file://`), e.g. `python -m http.server 8000` and open `http://localhost:8000`.
