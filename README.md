# Z-Route — Map Scanner & Alliance Analytics

Experimental Z-Route tools for scanning the game through BlueStacks, publishing a searchable player map, and analyzing alliance donation and ranking history.

**Live dashboards:** [Player Locator](https://tannerr12.github.io/Z-Route/) · [Donation Analytics](https://tannerr12.github.io/Z-Route/donations.html) · [VS Comparison](https://tannerr12.github.io/Z-Route/vs.html) · [Player Activity](https://tannerr12.github.io/Z-Route/activity.html)

> The website is publicly accessible through GitHub Pages. The BlueStacks scanner and AI Data Miner are experimental and have not been fully validated end-to-end. Donation records currently include **synthetic demo data** marked `DEMO`; do not interpret them as real guild results.

## Features

| Component | What it does | Entry point |
| --- | --- | --- |
| Player Locator | Search a swipe-grid map of players; hover for names and distinguish guilds by color | `index.html` |
| Map scanner | Capture BlueStacks screenshots and collect player observations using ADB and OCR | `scanner.py` |
| Data Miner | Navigate game ranking screens and extract VS rankings and alliance donation rows with a local vision model | `data_miner/mine_rankings.py` |
| VS Comparison | Analyze one guild’s individual member VS contributions, daily scores, weekly totals, low-score flags and trends | `vs.html` |\n| Donation Analytics | Load guild-specific CSV histories automatically; compare weeks, search players, inspect donation trends and contribution shares | `donations.html` |

## Repository data layout

```text
index.html
donations.html
data/
  players.csv
  donations/
    guilds.json                 # Guild dropdown directory
    D3AD/
      donations.csv             # Weekly donation history for D3AD
data_miner/
  mine_rankings.py
  mine_donations.py
  publish_donations.py
  output/
    donations.csv               # Local mining output (not automatically published)
    rankings.csv
```

Each guild has its own `data/donations/<GUILD>/donations.csv` containing multiple weeks. `guilds.json` supplies the dropdown choices; adding a new guild requires an entry in that manifest (the publisher adds it automatically).

### Donation CSV format

```csv
week_start,rank,username,role,points,captured_at,evidence
2026-11-02,1,ExamplePlayer,R3,42000,2026-11-03T12:00:00Z,DEMO
```

- `week_start`: Monday date in `YYYY-MM-DD` format; reporting weeks run Monday 00:00 UTC through the next Monday (exclusive).
- `rank`: positive leaderboard rank.
- `username`: game-visible name; currently used as the identity key within each week.
- `role`: optional alliance role (for example `R3`).
- `points`: nonnegative donation total for that week.
- `captured_at`: capture timestamp; `evidence`: screenshot reference or `DEMO` marker.

The dashboard loads the guild manifest and CSV using browser `fetch`; visitors **do not need to upload files**. A missing player record is not treated as zero. Names changing over time may appear as separate players until an identity-mapping feature is implemented.

## Donation Analytics

Select a guild and reporting week to see:

- Total donations, weekly change, number of recorded players, and low-donor count.
- Guild-wide donation history and a selectable 4-week, 8-week, or all-history chart period.
- Completed-week rolling average and momentum (latest two completed weeks versus the preceding two).
- Top donor and the percentage of total donations contributed by the top three.
- Individual player history, recorded completed weeks, personal best, and trend label.
- Member table with weekly changes, low-donor indicator, four-week trend, and share of total donations.
- Searchable player names and adjustable low-donor threshold (default: 20,000).

Trend labels are **Improving**, **Declining**, **Stable**, or **Insufficient**, based on available completed-week records. At least three recorded completed weeks are required; the current unfinished week is excluded from that classification. Guild totals and weekly comparisons reflect the rows available in the CSV, so incomplete leaderboard captures may understate totals. A missing prior-week record is shown as missing rather than zero.

## Local setup

Requirements: Python 3.10+, Android Platform Tools (ADB), Tesseract OCR, and BlueStacks with Android Debug Bridge enabled. The Data Miner additionally uses a locally running Ollama vision model (configured for `qwen2.5vl:3b`).

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item config.example.json config.json
python scanner.py test
```

Check ADB connectivity, game UI resolution, OCR/model setup, and configuration before running automated scans. Start with conservative interaction rates. The map scanner's calibration and coordinate assumptions must be checked manually against known bases.

### Mine weekly rankings and donations

From the repository root:

```powershell
python -m data_miner.mine_rankings --week-start 2026-11-02 --guild D3AD
```

This attempts to extract Monday–Saturday VS rankings, weekly VS rankings, and alliance donation rankings from BlueStacks. It writes local CSV/screenshot evidence and calls `publish_guild` to prepare `data/donations/D3AD/donations.csv` and update `guilds.json`. The guild tag is supplied explicitly; the miner does not independently verify that the game is showing the requested guild.

**Important:** preparing CSV files locally does **not** push them to GitHub. Review the extracted data and commit/push the updated `data/donations/` files to `main` for GitHub Pages to publish them:

```powershell
git add data/donations
git commit -m "Update guild donation history"
git push origin main
```

For a new guild, run the miner with a new `--guild` tag; the publisher creates its directory and manifest entry. Do not mix results from different guilds in the same local `data_miner/output/donations.csv`: that intermediate CSV has no guild column. Archive or clear it when changing guilds after preserving any records you need.

### GitHub Pages

This repository is published from **`main` → `/ (root)`** under **Settings → Pages → Build and deployment**. The dashboards are static HTML and fetch CSV files committed to the repository; they do not write to GitHub or require a server-side database. After pushing data, allow Pages to deploy and refresh the dashboard.

## Scanner data and limitations

The original map scanner uses a local SQLite database with `guilds`, `players`, `observations`, and `guild_membership_history` tables. Local databases, screenshots, private configuration, and scan progress are excluded from Git. Public CSV exports are a separate, intentionally published data surface.

The scanner and miner depend on visible game screens, OCR/vision accuracy, scrolling, and BlueStacks/ADB state. Validate sampled records, ranks, and coordinates manually. Keep interaction rates conservative and follow the game's rules.

## Next improvements

- Validate the Data Miner on a full live BlueStacks session, including leaderboard scrolling and guild identification.
- Automate reviewed CSV publication to GitHub while preventing demo records from mixing with real data.
- Track stable player identities across renames and guild transfers.
- Add extraction completeness and data-quality indicators for each weekly leaderboard.

## VS Member Analytics dashboard

Open [VS Member Analytics](https://tannerr12.github.io/Z-Route/vs.html) to inspect a single guild's player contributions. The page loads `data/vs/guilds.json` and `data/vs/<GUILD>/rankings.csv`, using columns `week_start,day,rank,username,alliance,points,captured_at,evidence`. Days are MON through SAT.

The dashboard shows recorded guild totals and weekly change, daily guild scores, daily player participation, and historical guild trends. Its main table lists **each player's daily VS points**, weekly total, previous-week score, week-over-week change, four-week trend, low-score flag, and contribution share. Filter by name, low score, declining trend, or incomplete daily records; sort by score, decline, or name. Member overview metrics include median score, mean score, number of declining players, and top-five contribution share. Select a player to view their history, personal best, four-week average, days recorded, and weekly rank. Adjust the low-score threshold to fit guild expectations.

**Caveats:** The sums are captured leaderboard points rather than verified official guild scores. Missing records are not zero, partial scans can understate scores, and current-week low-score flags are provisional. The initial D3AD and NOVA fixtures are synthetic DEMO data. Publishing the miner's local VS output to per-guild CSVs is not yet automated.


## Player Activity dashboard

Open [Player Activity](https://tannerr12.github.io/Z-Route/activity.html) for two CSV-backed views: attacks and alliance Join/Leave events. Source files are `data/player_activity/attacks.csv` and `data/player_activity/guild_changes.csv`. The page automatically loads committed CSVs, provides player/guild/date filtering, rankings, daily event counts, a searchable table, and filtered CSV export. The starting CSVs contain headers only; the ADB log-scanning bot has not yet been implemented and the site does not capture events itself.

Attack CSV columns: `timestamp,attacker,attacker_guild,attacker_server,attacked,attacked_guild,destination_server,destination_x,destination_y,outcome,scanned_at`. The future bot should record only attacks where the victim has a guild tag, the victim name does not start with `Commander2`, and the destination server is `#125`. Multiple distinct attacks between the same players must be kept; deduplicate on an event identifier when available, or on event time and participants/coordinates, noting identical-time collisions are possible.

Membership CSV columns: `timestamp,player,guild,event,scanned_at`, with event values such as `joined`, `left`, and `removed`. Entries represent activity in the scanned alliance; they do not prove a player transferred directly between two named guilds. Event times should retain the in-game clock as displayed unless the scanner verifies its timezone.


## Experimental network-based map scanner

The separate [network_scan/](network_scan/) prototype analyzes Z-Route's naturally observed WorldMapViewS2C network responses to recover game coordinates, player IDs, names, alliances, and levels without OCR. Its read-only decoder was validated on five captures; the guided/ADB navigation runner still needs in-game calibration. It provides a 3×3 coverage pilot, serpentine coordinate plans, local PCAPNG capture and resumable checkpoint CSVs. It does not send/replay game-server requests or automatically publish captured player data. See [network_scan/README.md](network_scan/README.md) before using it.

For the saved level-120 Watcher reference at S125 X:160 Y:687, the
flat candidate-field probe found no numeric field equal to 120. Use
[recursive raw-object inspection](network_scan/raw_object_inspect.py) to
inspect ALL nearby object fields, including unknown nested protobuf
fields, in the saved PCAPNG capture session:

~~~powershell
python network_scan/raw_object_inspect.py --session network_scans/entity_live/20261106_122600 --server 125 --x 160 --y 687 --radius 20 --visible-level 120
~~~

This offline tool produces a private `raw_object_probe.json` report;
numeric matches remain unverified until correlated with another known
creature level.

## Visually calibrated base shield detection (experimental)

Shield status is **not yet decoded**. A [local shield probe](network_scan/shield_probe.py)
allows a controlled comparison of the same player base while visibly
shielded versus unshielded, using stable (server, player_id) identity.
It compares **all** raw player-detail fields in passive map captures,
but never assumes unknown status bits indicate shield state.

Start the [live map watcher](network_scan/LIVE_ENTITY_WATCH.md) and use:

~~~powershell
python network_scan/shield_probe.py inspect --session network_scans/entity_live/SESSION --server 125 --x 500 --y 450
python network_scan/shield_probe.py mark --session network_scans/entity_live/SESSION --server 125 --x 500 --y 450 --state shielded
# Trigger fresh map responses while the shield stays ON.
python network_scan/shield_probe.py mark --session network_scans/entity_live/SESSION --server 125 --player-id YOUR_STABLE_ID --state unshielded
# Trigger fresh map responses while the shield stays OFF, then stop capture.
python network_scan/shield_probe.py compare --session network_scans/entity_live/SESSION --server 125 --player-id YOUR_STABLE_ID
~~~

Results are saved privately under network_scans/entity_live/SESSION/shield_probe/.
Read [full A/B workflow and caveats](network_scan/LIVE_ENTITY_WATCH.md).
Differences are hypotheses, not automatic unshielded labels, until
replicated across several state changes.

## Live Walker and moving-world-object investigation

For creature identification, the **game-provided rule is: verified
creature level >=100 implies Watcher**. A new `level-probe` command
compares a known on-screen Watcher level to raw map entity fields, without
assuming numeric subtypes are actual levels. A separate
[manual event audit](network_scan/entity_event_audit.py) records when you see
and defeat a Watcher, then checks **positive map sightings before and after**
the event; missing messages do not confirm despawns.

The [passive live entity watcher](network_scan/LIVE_ENTITY_WATCH.md)
captures normal BlueStacks network traffic in short 5-second PCAPNG windows
while you **manually navigate the map**. It records latest-seen X/Y,
numeric world-object type/subtype, raw candidate IDs and repeated
sightings, including the supported parts of incremental map updates.

In one PowerShell window:

~~~powershell
python network_scan/live_entity_watch.py watch --interface "Wi-Fi" --dumpcap "C:\Program Files\Wireshark\dumpcap.exe" --segment-seconds 5 --server 125
~~~

In another, inspect raw objects near an in-game Walker:

~~~powershell
python network_scan/live_entity_watch.py near --server 125 --x 500 --y 450 --radius 8 --within-minutes 3
~~~

After checking a specific in-game location and screenshot, use the
match command to save that one **visually confirmed** type/subtype. The
candidate object ID is not always unique: a single ID can appear at
multiple coordinates in one map response, so these sightings are
**not** guaranteed paths for moving Walkers. Shield interpretation
remains unverified. Data stays under Git-ignored network_scans/.

## Passive world-map entity inventory

The experimental [world-map entity explorer](network_scan/MAP_ENTITY_DISCOVERY.md)
inspects existing PCAPNG captures and exports all recognized world-object
type codes and X/Y positions, not only player-base type 1. It also records
uninterpreted player-status fields for later in-game confirmation of shield
state. Other types are intentionally marked **unclassified** until their
map coordinates are matched against visible Walkers, bosses, resources or
event structures; the scanner does not guess these labels.

Run a small offline pilot:

~~~powershell
python network_scan/map_entity_probe.py --max-files 12
~~~

Review network_scans/map_entities/type_inventory.csv and
network_scans/map_entities/world_objects.csv. The outputs and captures
remain private and Git-ignored. No direct game-server requests occur.

## Private player intelligence and name-change history

The [offline coverage and identity dashboard](network_scan/COVERAGE_AND_PLAYER_HISTORY.md)
combines the merged player roster with sampled map centers and persistent
player-name history. It supports lookup by player ID, current name or
historical alias; clicking a player highlights their last recorded X/Y
location. A private SQLite database retains every saved alias tied to
(server, player_id), rather than replacing the old name when roster CSVs
change.

Run from the repository root:

~~~powershell
python network_scan/coverage_report.py
start .\network_scans\coverage\coverage.html
~~~

New live-watch and automated minimap captures now record player observations
in network_scans/player_history.sqlite3. The HTML report and SQLite DB stay
under Git-ignored network_scans/. Existing scans can only establish past
name changes if the older name is present in a saved snapshot or capture.
Map-cell suggestions rank **sparse sampling evidence**, not proven
unscanned or empty regions.

## Progressive wide-zoom full-map scanner

The experimental [progressive minimap scanner](network_scan/FULL_MAP_SCAN.md) reuses the verified 1080x1920 minimap ROI and the passive packet decoder to search for roughly **9,500 unique bases**. It tests four-second captures first, retries missed responses with seven seconds, and visits 4x4, 7x7, then 10x10 center-first grids. A saved checkpoint prevents repeating completed targets after an interruption. If needed, append a 13x13 stage without clearing previous records.

From the repository root, preview with: python network_scan/full_map_scan.py run

Then test the first four clicks: python network_scan/full_map_scan.py run --execute --max-clicks 4 --interface "Wi-Fi" --dumpcap "C:\Program Files\Wireshark\dumpcap.exe"

This is separate from the original screenshot scanner and benchmark. Reaching a count of 9,500 is not proof of complete server coverage; check map-center coverage and review failed responses. Keep PCAPNGs private.

## Minimap click-pattern benchmark

The experimental [minimap benchmark](network_scan/PATTERN_BENCHMARK.md) uses a native BlueStacks screenshot to calibrate the clickable minimap region, generates snake/checkerboard/spiral/spread-out routes, and optionally taps a bounded grid through ADB while passively capturing map responses. It records unique player IDs for each clicked location, then replays the same observed sets in multiple orders so caching does not unfairly penalize later trials. An offline greedy-oracle result gives a hindsight upper bound on early discovery.

Start with a **preview**, test **one actual click** only after confirming the ROI, then collect a small 4x4 pilot and run the offline comparison. The program is separate from both scanner.py and live_watch.py. No game-server requests are generated. Keep raw PCAPNG files and player output private.

## Live network map base counter (experimental)

To see **cumulative unique player-base counts while manually jumping** around Z-Route, use the standalone read-only watcher. It captures the BlueStacks TCP traffic on port 9929 via Wireshark's `dumpcap`, rotates captures every 8 seconds, decodes received `WorldMapViewS2C` messages, and deduplicates by server + player ID.

```powershell
git switch dev
git pull origin dev
& "C:\\Program Files\\Wireshark\\dumpcap.exe" -D
python network_scan/live_watch.py --interface "Wi-Fi" --dumpcap "C:\\Program Files\\Wireshark\\dumpcap.exe" --segment-seconds 15
```

Replace `1` with your active Wi-Fi/Ethernet interface number from `dumpcap -D`. **Start the watcher before entering the world map**, then navigate normally. It prints progress as `+N NEW | N UNIQUE TOTAL | N map centers`. Press **Ctrl+C** to stop and finalize the last capture.

The run creates `network_scans/live/<timestamp>/players.csv`, `views.csv`, `segments.csv`, and `captures/`. Progress also shows **incoming TCP packets/bytes** and a status: `NO_INCOMING_GAME_TRAFFIC` (wrong interface or no game traffic), `NO_MAP_RESPONSE_DECODED` (traffic but no complete map response), `OVERLAPPING_OR_REPEATED_VIEWS`, `NO_NEW_PLAYER_IDS`, or `NEW_BASES`. The counter decodes adjacent capture files together so responses spanning a rotation are not silently lost. To resume and add to a previous session's total, use `--out network_scans/live/<timestamp>`. To report less frequently, use `--segment-seconds 15`.

To repair counts from an earlier run that showed zero, **stop the watcher** and reprocess its saved PCAPNG files offline: `python network_scan/live_watch.py --recount --out network_scans/live/<timestamp>`. This does not start a new capture; it rebuilds the CSV summaries from existing capture files using the improved decoder. Inspect `segments.csv` statuses if the counter stays at zero. Counts represent **distinct bases observed in captured map responses**, not percentage of the entire map scanned. A quiet interval may show zero even when bases are visible due to caching, and captures split across boundaries can omit responses. Use the saved view locations to audit geographic coverage; never treat the observed count alone as proof that all players were found. PCAPNG captures can contain sensitive session data: keep the entire `network_scans/` directory private and out of Git.
