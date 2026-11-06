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

### Deeper offline inspection when flat level-probe finds nothing

The current level-120 sample at **S125 X:160 Y:687** had 20 nearby
object anchors but no **flat** decoded scalar equal to 120. That does not
prove the Watcher has no level field. The parser deliberately ignored
unknown object fields and deeper nested byte strings.

Use the new **read-only, recursive raw protobuf inspector** to inspect
saved full-map and update messages from the known session:

~~~powershell
git switch dev
git pull origin dev
python network_scan/raw_object_inspect.py --session network_scans/entity_live/20261106_122600 --server 125 --x 160 --y 687 --radius 20 --visible-level 120
~~~

This does NOT need an active Walker or BlueStacks. It reads the saved
PCAPNG captures (including messages completed across two rotating
capture files), and prints every raw field for each nearby map object,
including unknown negative-type objects and parseable nested fields.

The private output is written to:

`network_scans/entity_live/20261106_122600/raw_object_probe.json`

If it finds field paths with literal numeric value 120, that is a
**candidate** only. The correct field must correlate with another known
Watcher level in a separate capture before it can be trusted. If the
inspector finds no `120` anywhere, investigate a different game
message or a derived game level rather than inventing a type mapping.

The PCAPNG and JSON can include game-session data. Keep both private.

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

## Shielded vs unshielded bases: controlled A/B test

The existing player-base (`type=1`) decoder provides stable
`(server, player_id)` identities, coordinates and some raw status
fields (`9,13,15,18,23`). **None of those fields is yet proven
to mean shield enabled or disabled.** The new `shield_probe.py`
records visually observed shield status and compares *all* direct player
detail protobuf fields, including missing/present values.

**Best experiment:** use your own base or a willing ally's base, and
observe the **same player ID** in both shielded and unshielded states.
Using two different players is weak evidence because their levels,
skins, movement/activity, titles and other attributes differ.

Start the live capture in PowerShell window 1:

~~~powershell
python network_scan/live_entity_watch.py watch --interface "Wi-Fi" --dumpcap "C:\Program Files\Wireshark\dumpcap.exe" --segment-seconds 5 --server 125
~~~

**Do not type `SESSION` literally.** Replace it with the timestamped directory (for example `20261106_132600`) printed by the watcher. You can also omit `--session` to use the newest completed session, but an explicit path is safer when multiple scans are running.

Copy the session path printed as `Private session:`. For example,
`network_scans/entity_live/20261106_180000`.

In window 2, navigate to a visible shielded base at its real coordinates
and identify its **stable player ID**:

~~~powershell
python network_scan/shield_probe.py inspect --session network_scans/entity_live/SESSION --server 125 --x 500 --y 450
~~~

When that base is **visibly shielded**, record a visual state marker:

~~~powershell
python network_scan/shield_probe.py mark --session network_scans/entity_live/SESSION --server 125 --x 500 --y 450 --state shielded
~~~

**Keep the shield on and navigate away/back** to trigger fresh
WorldMapViewS2C or WorldMapViewUpdateS2C messages. Ideally capture more
than one response. Do not change the shield until this is complete.

After the same base is visibly **unshielded**, mark it using the **same
player ID** from the first inspect, then navigate away/back again while
that state remains unchanged:

~~~powershell
python network_scan/shield_probe.py mark --session network_scans/entity_live/SESSION --server 125 --player-id YOUR_STABLE_ID --state unshielded
~~~

Finally, stop the watcher with Ctrl+C and compare:

~~~powershell
python network_scan/shield_probe.py compare --session network_scans/entity_live/SESSION --server 125 --player-id YOUR_STABLE_ID
~~~

The local results are:
- `shield_marks.csv`: user-observed state, time, stable player ID, and optional screenshot evidence path.
- `shield_probe/sampled_observations.json`: raw detail fields for matching packet sightings after the user marks.
- `shield_probe/field_differences.csv`: field values that differed between observed shielded and unshielded samples.

### Fast named-player lookup for additional shielded examples

For a new visually confirmed shielded base such as `BigDaddyKane`,
you can use the exact in-game username (case-insensitive) instead of
finding the coordinates or copying its player ID:

~~~powershell
python network_scan/shield_probe.py inspect --username BigDaddyKane --server 125
python network_scan/shield_probe.py mark --username BigDaddyKane --state shielded --server 125
~~~

Run while `live_entity_watch.py watch` is capturing a real session.
Omitting `--session` uses the most recently recorded session.
If that base is not present in decoded observations, navigate near it,
move away/back, and inspect again after a new completed capture window.
The `mark` command rejects ambiguous usernames shared by several
stable player IDs, rather than marking the wrong player.

The first visual shield observation is a ground-truth candidate only;
new decoded map sightings **after** the mark are required for `cohort`.
Repeat for visually confirmed unshielded controls, without treating an
absent protobuf field as proof a base has no shield.

### Troubleshooting 0 samples after marking shield states

A `mark` command records your visual observation and timestamp,
but **does not start a packet capture**. If `cohort` reports 0 samples,
check whether new map responses were decoded after the marker. As of
the sample discussed on Nov 6, Appsie213 (marked at 18:36:22 and
18:36:52 UTC) and DrDs (18:37:43 and 18:38:03 UTC) had **no
post-mark decoded sightings** in session `20261106_132830`.

After pulling latest `dev`, `cohort` prints the last
completed capture time, last decoded base sighting, and the last observation
of each visually marked player. If the last capture occurred BEFORE
the markers, the watcher probably stopped; restarting it creates a
NEW timestamped session. **Record NEW marks in that new session**
instead of expecting new observations in an old closed one.

Use two PowerShell windows. In one, run the `watch` command
and leave it running, making sure map views continue to decode. In
the other, `inspect` the base, `mark` the visual shield
state, navigate the map away and back while the state is unchanged,
and run `cohort` after the watcher has decoded a completed capture
window. Repeat for a visually confirmed unshielded base.

Do not repeatedly mark the same state hoping to make data appear.
The comparison can only use **new network observations** after marks.

### Cross-player control when the same shield cannot be toggled yet

A strong initial observation from session `20261106_132830`:
Appsie213 at S125 X:502 Y:423, stable ID `139194294397`,
was visibly under a blue dome and was the **only base among 24 nearby**
with raw protobuf player-detail field `9 = 1`. All other 23
had field 9 absent. **This is a candidate shield flag, not yet verified**:
other causes of a field being populated remain possible.

While the same live watcher runs, mark Appsie213:

~~~powershell
python network_scan/shield_probe.py mark --session network_scans/entity_live/20261106_132830 --server 125 --player-id 139194294397 --state shielded
~~~

Choose a base you can **visually verify is unshielded** and mark its
player ID with `--state unshielded`. Don't assume every
other base is unshielded merely because field 9 is absent.

After each mark, navigate the BlueStacks map away/back and wait for
a new 5-second capture window. Then compare visual controls from
multiple different bases:

~~~powershell
python network_scan/shield_probe.py cohort --session network_scans/entity_live/20261106_132830 --server 125
~~~

This prints the distribution of raw `status_9` in the visually
verified shielded versus unshielded groups and saves
`shield_probe/cohort_evidence.csv`. Only samples with an observed
map response **after** the visual marker are included. With a single
shielded sample and no unshielded controls, the command appropriately
reports inconclusive. Cross-player correlation is weaker than
same-player shield-on/shield-off comparisons. Repeat several examples,
preferably including a state change on one base.

**Important constraints:** packet timestamps are approximated using
capture-file modification times (Windows UTC). A snapshot immediately
around a marker can mix before/after state; only capture after the
mark while the state remains unchanged, and consider repeated trials.
A missing field in an update is not proof of shield absence.
Differences are **unverified candidates** until reproduced across
multiple transitions and preferably multiple player bases. Do NOT
automatically mark other bases as unshielded because a candidate bit
or timer is absent.

Run offline tests:

~~~powershell
python -m unittest discover -s network_scan -p test_shield_probe.py
~~~

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
