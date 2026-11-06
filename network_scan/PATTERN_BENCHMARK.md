# Minimap Click Pattern Benchmark (experimental)

This is an isolated BlueStacks experiment. It **does not send direct game-server requests**. It clicks the visible minimap through ADB and passively records TCP port 9929 using Wireshark's dumpcap. The existing screenshot scanner and network live counter are unchanged.

## Goal

Find the minimap visiting order that discovers the most **unique players early** at the widest zoom level that still returns player-base records.

- **snake:** horizontal serpentine sweep
- **checkerboard:** alternating locations first to reduce overlap
- **spiral:** center-out search
- **spread:** visits points farthest from previously visited grid positions first
- **greedy_oracle:** offline best-next point based on IDs already observed in the capture; a hindsight upper bound, not a live algorithm

All four real patterns visit the same set of grid positions and should ultimately collect the same players if responses are consistent. Their main difference is the yield in the first 25%, 50%, and 75% of clicks.

Instead of running one route, then unfairly benchmarking subsequent patterns against warm game caches, the tool collects each position ONCE and replays those identical results in all four orders.

## ADB setup and reconnection

The benchmark now reads `adb_path` and `adb_serial` from the repository's private `config.json`, just like `scanner.py`. For the configured local serial (such as `127.0.0.1:5555`), it checks `adb devices -l` and automatically runs `adb connect` if the device is missing. No ADB tap is issued until the device is confirmed connected.

If the screen capture reports `device not found`, first ensure BlueStacks is running, with Android Debug Bridge enabled in Settings → Advanced. To diagnose:

~~~powershell
$adbPath = (Get-Content .\\config.json | ConvertFrom-Json).adb_path
& $adbPath devices -l
& $adbPath connect 127.0.0.1:5555
& $adbPath devices -l
~~~

If another local port is shown, change `adb_serial` in `config.json` to that exact serial or pass `--serial`. ADB ports can change between emulator instances. Do not try random remote addresses or run clicks until the correct BlueStacks device is visible.

## Step 1: Save an emulator screenshot

From your repository root, with BlueStacks and the game's minimap open:

~~~powershell
git switch dev
git pull origin dev
python network_scan/pattern_benchmark.py screenshot
~~~

Open network_scans/minimap_reference.png in Paint. Record the **emulator screenshot's pixel coordinates**, not desktop coordinates, for the clickable inner minimap rectangle. Exclude Details, minimap controls, sidebar buttons, and other UI overlays. The ROI is LEFT,TOP,RIGHT,BOTTOM in emulator pixels.

## Step 2: Preview (no game clicks)

~~~powershell
python network_scan/pattern_benchmark.py plan --roi LEFT,TOP,RIGHT,BOTTOM --rows 4 --cols 4
python network_scan/pattern_benchmark.py run --plan network_scans/minimap_grid.json --pattern spread --max-clicks 4
~~~

Replace the ROI placeholder with your measured integers. The plan writes one route CSV per pattern and a JSON plan in the Git-ignored network_scans folder. These commands do not click anything.

## Step 3: First real minimap click

Stop live_watch.py before testing and leave the minimap open at a fixed zoom.

~~~powershell
python network_scan/pattern_benchmark.py run --plan network_scans/minimap_grid.json --pattern spread --max-clicks 1 --interface "Wi-Fi" --dumpcap "C:\Program Files\Wireshark\dumpcap.exe" --execute
~~~

The script verifies the ROI fits the emulator screenshot, starts dumpcap, taps one minimap point through ADB, waits for the map response and prints decoded base counts. **Observe whether the game moves to the intended region.** Saved observations include decoded world-map centers. If the first click fails to decode new bases, it stops rather than blindly continuing.

## Step 4: Collect the rest of the grid

Use the same plan and pattern to resume remaining clicks:

~~~powershell
python network_scan/pattern_benchmark.py run --plan network_scans/minimap_grid.json --pattern spread --interface "Wi-Fi" --dumpcap "C:\Program Files\Wireshark\dumpcap.exe" --capture-seconds 6 --execute
~~~

Each click is recorded separately and reports newly observed unique player IDs. Stop with Ctrl+C and resume using the same command. The tool writes captures and checkpoint files under network_scans/pattern_benchmark/spread/.

Six seconds per click is a conservative benchmark interval, not the optimized production pace. After validating the response rate, a subsequent small experiment can try 3–4 seconds per click.

## Step 5: Compare patterns fairly (offline)

~~~powershell
python network_scan/pattern_benchmark.py compare --session network_scans/pattern_benchmark/spread --plan network_scans/minimap_grid.json
~~~

Outputs:
- comparison.csv: bases discovered by 25/50/75% of clicks, clicks to reach 50% and 90% of observed bases, pixel travel distance, approximate measured click time
- comparison_progress.csv: cumulative discoveries after every click for each replayed pattern

The greedy_oracle result is a **retrospective ideal**, not a viable untrained live navigator.

## Limitations

1. A minimap click may not trigger a fresh WorldMapViewS2C response (cache, unchanged view, wrong UI target, or zoom). Zero data does not prove an empty area.
2. The minimap click-to-world-coordinate mapping is not calibrated. Compare decoded map centers with clicked positions before automating longer runs.
3. These measurements are **discovery within sampled regions**, not complete proof of server coverage.
4. Game data may change between tests. Replay of the same per-point observations avoids some cache bias, but a true live policy still needs validation.
5. Keep PCAPNG captures and extracted player IDs private. They can include account/session information and are not meant to be pushed to public GitHub Pages.
