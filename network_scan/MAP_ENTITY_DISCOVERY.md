# Z-Route map entity discovery: shields, Walkers and world objects

The current player decoder captures WorldMapViewS2C object type 1
(player bases). The same packets include other object types with game
coordinates, numeric subtypes and additional nested fields. This
offline tool inventories everything it can parse **without guessing labels**.

There are no direct server requests, ADB clicks or writes to the game.

## Evidence from the previously supplied captures

Our sample contained 26,136 *repeated object observations*, not unique
objects. Type 1 (player bases) appeared 15,014 times; unclassified
type 3 appeared 5,448 times, type 5 appeared 1,987 times, type 6
appeared 555 times, type 9916 appeared 1,090 times and type 9917
appeared 760 times. Other negative-valued types also exist.

Some type-3 subcodes observed: 310, 110, 210, 309, 307 and 109.
Type-5 subcodes include 220103, 220101 and 220102.
Type-6 subcodes include 30, 25, 19 and 11. We need a visible game
example and matching X/Y coordinates before identifying which are
Walkers, resource sites, bosses, event buildings or something else.

**Shield status is still unverified.** Player-base objects contain optional
fields 9, 13, 15, 18 and 23, sometimes with time-like numbers, but the
meaning is not yet confirmed. Absence of a field does not mean unshielded.

## Run against your saved scan captures

From the repository root:

~~~powershell
git switch dev
git pull origin dev
python network_scan/map_entity_probe.py --max-files 12
~~~

This performs a small offline pilot over 12 PCAPNG captures from the
saved live-watch and full-map scan folders. For a complete read:

~~~powershell
python network_scan/map_entity_probe.py
~~~

To inspect a particular PCAPNG directly, use:

~~~powershell
python network_scan/map_entity_probe.py --captures "network_scans/full_map/captures/001_4x4_r01c01_try1.pcapng"
~~~

Outputs are private files under network_scans/map_entities:

- type_inventory.csv: object type code, observations, coordinate examples,
  nested field signatures and top subtype codes.
- world_objects.csv: latest distinct non-player map positions, raw detail
  values, and approximate first/last capture.
- object_observations.csv: each raw map-object occurrence, including repeats.
- player_status.csv: player IDs and raw optional status flags; all shield
  states explicitly marked unverified.
- type_samples.json: sampled nested fields for reverse-engineering.
- entity_summary.json: observation counts and decoder limitations.

Inspect the discovered types:

~~~powershell
Import-Csv .\network_scans\map_entities\type_inventory.csv |
  Format-Table type_code,observations,unique_positions,subtype_examples -AutoSize
~~~

To find unknown objects near a visible Walker on the map, replace X/Y
with the coordinates you read from Z-Route (example 123,456):

~~~powershell
Import-Csv .\network_scans\map_entities\world_objects.csv |
  Where-Object { [math]::Abs([int]$_.x-123) -le 5 -and [math]::Abs([int]$_.y-456) -le 5 } |
  Format-Table type_code,subtype,x,y,type_label
~~~

## Calibrating names against actual gameplay

We need a screenshot showing a Walker's exact server, X and Y, plus
nearby passive map traffic. Similarly, compare one visibly shielded base
and one visibly unshielded base with the captured raw player-status fields.
Only then can we label a given numeric code/field reliably.

You can optionally create a private JSON mapping of visually validated
object codes to human labels. Example file shape (illustrative only;
type 3 is NOT confirmed to mean Walker):

~~~json
{
  "3": {"name": "Example label after in-game verification", "verified": true}
}
~~~

Run:

~~~powershell
python network_scan/map_entity_probe.py --labels network_scans/map_entities/labels.json
~~~

A type code may describe a whole object family containing several
subtypes, so confirm subtype behavior before generalizing.

## Limits and privacy

- Numeric type IDs and raw coordinates are directly present in map views.
- Detailed player shield state may not be provided in ordinary map-view
  responses, or it may be encoded in fields not yet identified.
- File modification times approximate when the capture was saved; they
  are not exact spawn or shield-expiration timestamps.
- A map response may be cached or incomplete and does not prove every
  nearby entity was included.
- Keep captures and exports private. The repository ignores the
  network_scans directory by default.

Run offline regression tests:

~~~powershell
python -m unittest discover -s network_scan -p test_map_entity_probe.py
~~~
