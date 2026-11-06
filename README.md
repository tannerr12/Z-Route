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

## Live network map base counter (experimental)

To see **cumulative unique player-base counts while manually jumping** around Z-Route, use the standalone read-only watcher. It captures the BlueStacks TCP traffic on port 9929 via Wireshark's `dumpcap`, rotates captures every 8 seconds, decodes received `WorldMapViewS2C` messages, and deduplicates by server + player ID.

```powershell
git switch dev
git pull origin dev
& "C:\\Program Files\\Wireshark\\dumpcap.exe" -D
python network_scan/live_watch.py --interface 1 --dumpcap "C:\\Program Files\\Wireshark\\dumpcap.exe" --segment-seconds 15
```

Replace `1` with your active Wi-Fi/Ethernet interface number from `dumpcap -D`. **Start the watcher before entering the world map**, then navigate normally. It prints progress as `+N NEW | N UNIQUE TOTAL | N map centers`. Press **Ctrl+C** to stop and finalize the last capture.

The run creates `network_scans/live/<timestamp>/players.csv`, `views.csv`, `segments.csv`, and `captures/`. Progress also shows **incoming TCP packets/bytes** and a status: `NO_INCOMING_GAME_TRAFFIC` (wrong interface or no game traffic), `NO_MAP_RESPONSE_DECODED` (traffic but no complete map response), `OVERLAPPING_OR_REPEATED_VIEWS`, `NO_NEW_PLAYER_IDS`, or `NEW_BASES`. The counter decodes adjacent capture files together so responses spanning a rotation are not silently lost. To resume and add to a previous session's total, use `--out network_scans/live/<timestamp>`. To report less frequently, use `--segment-seconds 15`.

Counts represent **distinct bases observed in captured map responses**, not percentage of the entire map scanned. A quiet interval may show zero even when bases are visible due to caching, and captures split across boundaries can omit responses. Use the saved view locations to audit geographic coverage; never treat the observed count alone as proof that all players were found. PCAPNG captures can contain sensitive session data: keep the entire `network_scans/` directory private and out of Git.
