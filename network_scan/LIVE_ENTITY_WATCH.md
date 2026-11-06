# Live Z-Route world entities — visually confirm Walkers and changing map objects

This is a **passive local experiment**, not a live connection to the game
server. It runs Wireshark's dumpcap against normal BlueStacks game traffic
(TCP port 9929), decodes the recorded map responses and prints new world
object positions approximately every five seconds.

It does **not** drive the game or send game-protocol messages. Navigate
with the mouse yourself. Player roster and capture files stay under the
private Git-ignored network_scans folder.

## Why this is needed

Non-player map objects have numeric type/subtype codes and X/Y positions.
The same raw outer ID can occur at **multiple positions in the same map
response**. In 33 of 59 views in one saved test capture, at least one
candidate ID had several coordinates simultaneously. Therefore this field
is **not a verified unique moving-object ID**.

The watcher maintains:
- observed **type/subtype + coordinate** sightings and their approximate times
- candidate group IDs, with warnings when they are shared by multiple objects
- per-capture observations of raw player-status fields (shield not identified)
- a human-in-the-loop **visual match** connecting one observed coordinate
  and type to an in-game Walker screenshot

It does NOT automatically infer movement, despawns or shield expiration
from a lack of sightings. Old observations may be stale.

The decoder supports WorldMapViewS2C and identifiable
WorldMapViewUpdateS2C records. Some small updates have ambiguous encryption;
if only one candidate matches the known S125 server, that decode is
accepted. Otherwise it is rejected and not counted.

## 1. Start a live watcher

Make sure BlueStacks has Z-Route open on the world map. Stop any other
scanner using the same capture directory so the output is easy to
interpret. From the repository root in **PowerShell window 1**:

~~~powershell
git switch dev
git pull origin dev

python network_scan/live_entity_watch.py watch --interface "Wi-Fi" --dumpcap "C:\Program Files\Wireshark\dumpcap.exe" --segment-seconds 5 --server 125
~~~

Keep this terminal open. A new session folder is created at
network_scans/entity_live/YYYYMMDD_HHMMSS/. You can manually jump near a
visible Walker, boss, resource site or shielded player.

The console displays the number of decoded map views and updates, new
entity coordinates, raw type/subtype and sample candidate IDs. The initial
results are **unclassified**; do not assume type 3 means Walker.

A five-second rotation is not instantaneous and may take a little longer
if the map response is split between capture files or no new traffic
arrives. The tool processes **closed** windows to avoid corrupt reads.

## 2. Check a live coordinate from another PowerShell window

Read the object coordinates S:125 X:... Y:... from the in-game map.
In **PowerShell window 2** run (replace X/Y with real values):

~~~powershell
python network_scan/live_entity_watch.py near --server 125 --x 500 --y 450 --radius 8 --within-minutes 3
~~~

Results show type/subtype, candidate group ID, distance, and **minutes
since the last saved sighting**. This is a short-lived observation, not
a guaranteed current location.

To show only candidate types 3, 5 and 6:

~~~powershell
python network_scan/live_entity_watch.py near --x 500 --y 450 --radius 8 --types 3,5,6
~~~

No prior data means no match; keep the watcher running and navigate
to a nearby region to trigger a fresh map response.

## 3. Save visual evidence and mark a confirmed sighting

While you see a Walker at exact S125 X:500 Y:450, save a BlueStacks PNG:

~~~powershell
python network_scan/pattern_benchmark.py screenshot --out network_scans/walker_evidence_500_450.png
~~~

Then check the candidate type using near with a small radius and inspect
the game's actual coordinate label. Once only one object matches EXACTLY:

~~~powershell
python network_scan/live_entity_watch.py match --server 125 --x 500 --y 450 --radius 0 --label "Walker" --screenshot network_scans/walker_evidence_500_450.png
~~~

The output is appended to visual_matches.csv in the newest entity-live
session. It stores a label **for that one object sighting only**, plus
its source, type/subtype, last-sighting time and PNG path.

If there are several map objects at the same X/Y, the program refuses
to guess. Narrow with --code after examining the near output:

~~~powershell
python network_scan/live_entity_watch.py match --server 125 --x 500 --y 450 --radius 0 --code 3 --label "Walker" --screenshot network_scans/walker_evidence_500_450.png
~~~

Code 3 above is ONLY an illustration of syntax. We have not yet
confirmed any numeric type means Walker. One positive example is not
enough to label the entire type family: different subtypes may be
unrelated. Capture several visual examples.

## 4. Check repeated sightings for a candidate group

Copy type code and candidate-group ID from the near output:

~~~powershell
python network_scan/live_entity_watch.py trail --server 125 --code 3 --group-id 1793928700943
~~~

This lists positions observed in successive map responses, but a
shared candidate ID can refer to multiple simultaneous objects. If the
same group has >1 position in a view, the tool explicitly warns that it
cannot be considered an individual Walker's movement path.

## 5. Calibrate the Watcher level field

**User-supplied game rule:** only creatures of level 100 or higher can be
Watchers. That is a strong classification rule **once we identify an actual
creature-level field in the network data**. A random numeric field, subtype,
or object ID >=100 does NOT qualify.

Use the stationary level-120 example at S125 X:160 Y:687 and its saved
live session to compare known UI level against raw scalar fields:

~~~powershell
python network_scan/live_entity_watch.py level-probe --session network_scans/entity_live/20261106_122600 --server 125 --x 160 --y 687 --visible-level 120 --radius 12 --save
~~~

The output ranks nearby candidates with nested scalar fields equal to
120, if any. It saves **candidate evidence only** to level_probes.csv.
This does NOT automatically identify or label a Watcher: proximity does
not prove which object field belongs to the visible creature.

Repeat with a verified stationary level-100 or level-130 Watcher at its
actual in-game coordinates and compare the **same type code and field
number** across examples. If none of the raw fields matches the visible
level, the level may be encoded indirectly or not sent by map-view
responses. Only after validation should the decoder apply the
creature-level >=100 ⇒ Watcher rule.

## 6. Controlled before/after kill experiment

For the earlier level-100 kill test, no decoded map messages after the
kill means we cannot infer the enemy's deletion from the missing records.
The new event audit tool allows **user-observed** timestamps and checks
whether positive nearby sightings occurred on both sides.

1. Start the live watcher **before navigating to the target**.
2. Once the level-100 Watcher is visible, open another terminal and
   record a "visible" marker at its actual world X and Y:

~~~powershell
python network_scan/entity_event_audit.py mark --session network_scans/entity_live/SESSION --label visible --x X --y Y --visible-level 100
~~~

3. Defeat the Watcher while the watcher continues capturing, then mark it:

~~~powershell
python network_scan/entity_event_audit.py mark --session network_scans/entity_live/SESSION --label defeated --x X --y Y --visible-level 100
~~~

4. Navigate away and back to request fresh map responses (only normal
   in-game navigation), then audit:

~~~powershell
python network_scan/entity_event_audit.py report --session network_scans/entity_live/SESSION --x X --y Y --radius 15
~~~

The report explicitly shows decoded before/after view and update counts.
No messages after the kill = **inconclusive**, not proof of disappearance.
Even with post-kill views, the exact view footprint and delete-event
semantics are not verified, so absence is not a confirmed despawn.

## 7. What gets saved and how to stop

Ctrl+C in window 1 closes capture, processes the last segment and
preserves all CSVs and PCAPNGs.

- latest_entities.csv: most recent coordinate sighting for each observed
  position/type/subtype/group candidate
- entity_sightings.csv: repeated sightings, timestamped by saved
  capture-file close time (approximate)
- type_summary.csv: counts by unclassified numeric type
- player_status_sightings.csv: raw player-status flags for investigating
  shield state; no fabricated shield yes/no
- visual_matches.csv: exact manually verified object coordinates/labels
- segments.csv: incoming traffic, decoded full views/updates, errors
- captures/: unmodified traffic evidence
- dumpcap.log: any Wireshark adapter errors

To analyze saved capture files without running another live capture:

~~~powershell
python network_scan/live_entity_watch.py replay --captures "C:\path\to\capture1.pcapng" "C:\path\to\capture2.pcapng" --server 125
~~~

For a separate session, use --out when starting watch and --session
with near/match/trail.

## Limits and safety

- WorldMapViewUpdateS2C contains delta messages; not every form is
  understood and some may lack full world-object data.
- A coordinate can be stale if the Walker moves after observation.
  Last seen is **not** proof it remains there now.
- A candidate ID shared between multiple positions cannot identify
  one moving object; do not infer paths without stronger evidence.
- We have not yet decoded shield state confidently. A raw status flag
  or timestamp is not enough to claim shielded/unshielded.
- The watcher's timestamp is approximate (capture-file modification
  time), not the precise in-game event time.
- Keep screenshots and packet captures private and review game rules
  before using automation.

## Offline regression tests

~~~powershell
python -m unittest discover -s network_scan -p "test_live_entity_watch.py"
~~~
