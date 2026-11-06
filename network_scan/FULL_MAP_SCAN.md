# Progressive minimap scan — goal of ~9,500 bases

This experimental command is independent of the original screenshot scanner and benchmark. It navigates using the calibrated BlueStacks minimap and **passively captures** TCP port 9929 via Wireshark dumpcap. It does not forge or send direct game-server messages.

The 16-click pilot produced 1,109 unique player IDs. A retrospective comparison showed that a center-out spiral found more IDs in its early clicks than other tested routes. That result does not establish the best full-map route, but justifies a larger pilot.

The scanner uses progressive center-out grids of **4x4, 7x7, then 10x10** points, with duplicate/nearby click coordinates omitted. Its goal is roughly 9,500 unique bases. Reaching that number is **not proof of geographic completeness**; the program keeps scanning by default rather than stopping at the threshold.

## End-to-end pipeline from login to radar

The world-scan pipeline reuses the same `data_miner.startup.run_ai_startup(cfg)`
function that the proven player-activity script uses for login confirmation
and promotional popups. There is no duplicate ad handler.

**The city-to-world button is labeled "Leave City"** (not "View Map").
We locate that exact labeled control from a verified city screenshot,
tap it once, and check that the actual world map is visible before any
zoom-out action. Then we zoom out until the top-right radar is verified
and begin the existing passive network scan.

Run from the repository root:

~~~powershell
git switch dev
git pull origin dev

# First: verify ONLY login confirmation and ads, no map clicks
python network_scan/world_scan_pipeline.py run --execute --startup-only

# Optional: inspect the present screen, no taps
python network_scan/world_scan_pipeline.py inspect

# Next: test login + ads + Leave City + zoom-to-radar only
python network_scan/world_scan_pipeline.py run --execute --prepare-only

# Once that passes: collect four minimap captures
python network_scan/world_scan_pipeline.py run --execute --max-clicks 4

# Full scan, each invocation in its own timestamped folder
python network_scan/world_scan_pipeline.py run --execute
~~~

The initial login modal is handled by Player Activity **before the slow Ollama world-map classifier**. If `initial.png` shows the login warning, the pipeline logs `login_warning_detected` and delegates immediately to the existing Confirm/promotion handler. Use `--startup-only` to debug this stage without clicking Leave City or beginning a scan.

The pipeline stores screenshot evidence and state in
`network_scans/map_refresh/TIMESTAMP/`, writes captures and players.csv,
and uses the permanent `network_scans/player_history.sqlite3` for all
observed usernames. It writes rename comparisons when an older scan
is available.

**Not fully calibrated yet:** the exact position of "Leave City" is
obtained with the existing vision-based label locator, not a guessed
hardcoded coordinate. The world-map zoom-out control and top-right radar
must be visually verified on this BlueStacks instance. If the locator
cannot verify the control or the radar, the pipeline stops and saves
screenshots, rather than tapping unknown UI. Once their emulator-pixel
centers are visually calibrated, `--map-tap X Y` and
`--zoom-tap X Y` can be used as explicit overrides.

The following command executes offline safety tests:

~~~powershell
python -m unittest discover -s network_scan -p test_world_scan_pipeline.py
~~~

## Setup and four-click speed pilot

Make sure BlueStacks is on the minimap at the same zoom as the earlier successful test. config.json must contain the configured ADB executable and emulator serial. The current calibrated minimap ROI is **800,25,1060,270** for the 1080x1920 emulator screenshot.

Run from the repository root (commands shown on single lines for easy PowerShell use):

~~~powershell
git switch dev
git pull origin dev
python network_scan/full_map_scan.py run
python network_scan/full_map_scan.py run --execute --max-clicks 4 --interface "Wi-Fi" --dumpcap "C:\Program Files\Wireshark\dumpcap.exe"
~~~

The first command is preview-only. The second performs **four minimap clicks**, capturing for four seconds each. Unsuccessful map captures are retried once at **seven seconds**.

Watch the first four clicks to verify the game navigates correctly and at least some map responses return bases. After the first pilot, run:

~~~powershell
python network_scan/full_map_scan.py run --execute --interface "Wi-Fi" --dumpcap "C:\Program Files\Wireshark\dumpcap.exe"
~~~

It continues at the saved position, never requiring the earlier steps to be repeated. Ctrl+C stops, saving all completed click results.

## Local files

The default session directory is network_scans/full_map, excluded by .gitignore.

- players.csv: deduplicated base records, including usernames, alliance, levels and world coordinates
- steps.csv: per-click newly discovered IDs, cumulative IDs, decoded views, duration and response status
- route.csv and route.json: the planned minimap positions
- checkpoint.json: resumable progress
- captures/: per-click PCAPNG files
- dumpcap.log: capture errors and diagnostics

Review progress without touching BlueStacks:

~~~powershell
python network_scan/full_map_scan.py report
~~~

## Compare against the earlier 9,502-base live session first

Your earlier live watcher displayed approximately 9,502 distinct player IDs.
Before adding hundreds of minimap clicks, compare the current full-map roster
with that existing capture using the new **offline, read-only** comparator:

~~~powershell
python network_scan/compare_player_sessions.py
~~~

The comparator selects the live session containing the largest number of
unique valid base IDs, then reports the overlap, previous-only IDs,
new-only IDs, and union. This verifies whether we have already met the
approximate 9,500-base roster target.

If your baseline is in a different folder, select it explicitly:

~~~powershell
python network_scan/compare_player_sessions.py --old "network_scans/live/SESSION/players.csv"
~~~

Optionally generate a deduplicated combined roster without modifying the
input files:

~~~powershell
python network_scan/compare_player_sessions.py --write-merged network_scans/combined_players.csv
~~~

Even when the union exceeds 9,500 IDs, that does not prove every geographic
map region was scanned.

## Recurring scans: preserve player name history first

Every decoded base is keyed by the stable **(server, player_id)** identity.
**Usernames are mutable**. Name changes are the highest-priority output of
each refresh, even if a player stays in exactly the same location.

- The automatic minimap scanner records each decoded capture's usernames
  into the **shared** `network_scans/player_history.sqlite3` before its
  checkpoint advances. If saving history fails, the scan stops and leaves
  the point pending so names are not silently lost.
- Each refresh gets its own `network_scans/map_refresh/TIMESTAMP/players.csv`.
  The shared history database retains all previously observed names even
  when that file is replaced or a player moves.
- `scan_changes.py` reports **name changes before movement** and writes
  `renames.csv` (this pair of snapshots) and `all_name_changes.csv`
  (all previously observed transitions in the persistent database).
- Old and new names in a report are supported by actual observations, not
  game-supplied rename-event times. A player not seen in a newer scan is
  merely unobserved, not deleted.

## Recurring scans for player movement

The default network_scans/full_map folder is a **resumable discovery pass**:
a second invocation skips already completed minimap clicks. Therefore it
does NOT constitute a new full-world scan when players move.

For each periodic refresh, use a **new timestamped session folder** in
PowerShell and keep the same calibrated minimap zoom/ROI:

~~~powershell
$run = Get-Date -Format "yyyyMMdd_HHmmss"
$previous = "network_scans/full_map/players.csv"
$current = "network_scans/map_refresh/$run"
python network_scan/full_map_scan.py run --execute --pattern spread --out $current --interface "Wi-Fi" --dumpcap "C:\Program Files\Wireshark\dumpcap.exe"
python network_scan/scan_changes.py --before $previous --after "$current/players.csv"
~~~

**Only execute when the radar is visible and zoom is verified.** This
command does not get the app through login or dismiss overlays.
The existing data_miner/startup.py can verify/dismiss the known login
warning and ads, but the subsequent **View Map button** and **zoom-out
until radar appears** must still be calibrated in BlueStacks before
unattended launch can safely be implemented. Do not hardcode unknown
screen coordinates.

Review **"$current/changes_from_previous/renames.csv" first** to see name
changes during the refresh. The file `all_name_changes.csv` records the
full history of known name transitions. Then inspect `changes.csv` for
movement, alliance changes, levels, and missing observations.


This compares stable (server, player_id) across the two captures and
reports moved coordinates, newly observed IDs, renames and alliances.
Players not seen in a later sample are labeled **not_seen_in_after**,
never "gone", because missing observations can reflect coverage/cache.

Use `--pattern spiral` for the original best-early-discovery sequence or `--pattern spread` for a candidate geographically distributed early refresh. Other supported experimental routes are `snake` and `checkerboard`. A fresh `--out` folder is required for each independent scan; do not switch patterns inside an existing checkpoint.

For repeated full sweeps, we have **not yet proved an optimal route**.
The earlier 16-click spiral pilot yielded 1,109 IDs and was a good
discovery-first order. It is not evidence for the best *recapture* order.
Use the same route for controlled comparisons, and measure:
- % of previous IDs seen again during the newest sweep
- count of player IDs with changed X/Y
- decoded view success per minimap target
- geographic gaps and map-view centers
- time to sweep all targets and age of the oldest scanned region

For frequent updates, a quicker coarse 4x4 pass could supply a partial
refresh, but don't treat it as a complete refresh. Deeper 7x7 and 10x10
passes sample the remaining regions and should be revisited even once
the unique-player count reaches ~9,500.

Compare any two scan sessions without a live connection:

~~~powershell
python network_scan/scan_changes.py --before network_scans/map_refresh/OLDER/players.csv --after network_scans/map_refresh/NEWER/players.csv
python -m unittest discover -s network_scan -p test_scan_changes.py
python -m unittest discover -s network_scan -p test_player_history.py
~~~

## Additional coverage and retries

If the default stage sequence finishes below the target, **append** a finer 13x13 stage to the same session:

~~~powershell
python network_scan/full_map_scan.py run --execute --stages 4,7,10,13 --interface "Wi-Fi" --dumpcap "C:\Program Files\Wireshark\dumpcap.exe"
~~~

This extends the existing route without redoing previously completed points.

To retry any earlier targets that failed to provide a decodable map response:

~~~powershell
python network_scan/full_map_scan.py run --execute --retry-review --interface "Wi-Fi" --dumpcap "C:\Program Files\Wireshark\dumpcap.exe"
~~~

If you want to stop as soon as 9,500 unique IDs are observed, add --stop-at-goal. It is intentionally opt-in, because stopping at a count cannot establish full geographic coverage.

## Caveats

- The first long run still needs validation on your computer.
- Keep the zoom fixed; changing zoom changes per-click coverage.
- Screen coordinates are emulator coordinates, not Windows desktop coordinates.
- No decoded map response does not mean the area is empty.
- World-map view centers are observed positions, not proven viewport boundaries.
- Keep raw PCAPNGs and extracted data private, and review game rules before use.

## Offline checks

~~~powershell
python -m unittest discover -s network_scan -p test_full_map_scan.py
~~~
