# Z-Route — Map Scanner & Alliance Analytics

Experimental Z-Route tools for scanning the game through BlueStacks, publishing a searchable player map, and analyzing alliance donation and ranking history.

**Live dashboards:** [Player Locator](https://tannerr12.github.io/Z-Route/) · [Donation Analytics](https://tannerr12.github.io/Z-Route/donations.html) · [VS Comparison](https://tannerr12.github.io/Z-Route/vs.html)

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

The dashboard shows recorded guild totals and weekly change, daily guild scores, daily player participation, and historical guild trends. Its main table lists **each player's daily VS points**, weekly total, previous-week score, week-over-week change, four-week trend, low-score flag, and contribution share. Filter by name, adjust the low-score threshold, and select a player for a historical chart.

**Caveats:** The sums are captured leaderboard points rather than verified official guild scores. Missing records are not zero, partial scans can understate scores, and current-week low-score flags are provisional. The initial D3AD and NOVA fixtures are synthetic DEMO data. Publishing the miner's local VS output to per-guild CSVs is not yet automated.
