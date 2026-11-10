# Player Activity: network-only baseline

The canonical CSV files under this directory were reset on **2026-11-10** using the user's captured `UnionOplogListS2C` response from `open_log.pcapng` (capture session `20261110_174812`). **The previous OCR-generated 7 attack and 21 membership rows were replaced**, not appended. Older values are recoverable from Git history.

## Master datasets

- `attacks.csv`: 16 network-derived type-11 attacks to Server #125 where the victim has a nonempty alliance tag and the victim name does not start with `Commander2`.
- `guild_changes.csv`: 200 network-derived entries — 100 type-1 joins, 57 type-2 departures, and 43 type-3 removal-type actions. For type 3, `actor` and affected `player` are separate. Type-3 semantics are inferred from the packet and still merit screenshot confirmation.

## Event-time and duplicate rules

`event_epoch_ms` is the source-provided Unix millisecond event time; `game_event_time_utc` is its exact UTC representation. `timestamp` is a display-friendly UTC time rounded up to a whole second, consistent with known observed War entries. `scanned_at` is when the source capture was made, **not** the event time. No scan time is substituted for missing event time.

`event_id` is a stable SHA-256-derived identity from event type, exact millisecond time and participants (and destination for attacks). Repeated network scans append only unseen event IDs, retaining old records even if the server's current history response no longer includes them.

The website activity dashboard reads these two master CSVs; it does not ingest raw PCAPNG files or generate gameplay events. The local scanner's `network_player_activity` command performs the ingestion and network-only publication. The original capture can be inspected via `network_scan/union_oplog_events.py` in the scanner repository.

## Reproducibility and limits

The captured response contained 825 operation records across many types. Only the specified attack and membership types were exported. Field interpretations are based on observed packet layout and sample comparisons; this is not an official API schema. The game's history-retention limit is unknown.
