# Progressive minimap scan — goal of ~9,500 bases

This experimental command is independent of the original screenshot scanner and benchmark. It navigates using the calibrated BlueStacks minimap and **passively captures** TCP port 9929 via Wireshark dumpcap. It does not forge or send direct game-server messages.

The 16-click pilot produced 1,109 unique player IDs. A retrospective comparison showed that a center-out spiral found more IDs in its early clicks than other tested routes. That result does not establish the best full-map route, but justifies a larger pilot.

The scanner uses progressive center-out grids of **4x4, 7x7, then 10x10** points, with duplicate/nearby click coordinates omitted. Its goal is roughly 9,500 unique bases. Reaching that number is **not proof of geographic completeness**; the program keeps scanning by default rather than stopping at the threshold.

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
