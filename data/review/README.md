# Performance Review supplementary data

The public **review.html** page combines these existing public files automatically:

- `data/donations/<guild>/donations.csv` — `week_start,rank,username,role,points,captured_at,evidence`
- `data/vs/<guild>/rankings.csv` — `week_start,day,rank,username,alliance,points,captured_at,evidence`

The review applies a configurable **per-week** donation minimum (default 25,200)
and **per-day** VS goal (default 1,000,000). D3AD also uses the current server-125
network roster and Join/Leave history, so a member absent from a captured score
list receives zero. An uncaptured list remains unknown. Shared aliases are
marked ambiguous rather than used for automatic bad-standings flags.

The donation minimum is prorated to the days covered by the selected data.
For example, a Wednesday weekly snapshot covers three days, even when reviewing
that week later. A snapshot captured after the week ends covers all seven days.
Excluding today (UTC) prefers a verified pre-day cumulative baseline when
available, otherwise daily donation records, to avoid including today's
cumulative points. Completed-day differences in `derived_daily.csv` replace
partial raw daily captures; `baselines.csv` supplies verified pre-day totals.
Explicit unknown differences remain unknown. Scanner donation dates use the
game UTC−2 clock, so boundary hours can differ from the UTC exclude-today cutoff.

Join and departure exclusion switches use the published membership log.
Records marked `player_id_source=conflicting_identity` are not used for
automatic membership exclusions, chopping-block join exemptions, or recruitment
removal filtering. The original records and IDs are retained for investigation.

Optional additional management fields can be published as
`data/review/D3AD/members.csv`, with this CSV header:

```csv
username,joined_at,no_shield,frenzy
```

- `joined_at`: ISO date (`YYYY-MM-DD`), or blank if unknown.
- `no_shield`: `true`, `false`, or blank if not checked.
- `frenzy`: `true`, `false`, or blank if not checked.

Do **not** automatically populate `no_shield` from an expired world-map
bubble observation; the management No Shield list may be a distinct game
feature. Frenzy participation is not present in the published donation/VS schema.
Join dates come from available membership history or this optional metadata.
Unknown values display as a dash.

If input rows are tagged `DEMO`, the page labels them. CSV export uses the
currently displayed reporting week; Copy Bad Standings uses only visible,
flagged members and respects the search and category filters.

Run all offline checks with:

```sh
node scripts/check_javascript.js
node --test
python -m unittest discover -v -s scripts -p 'test_*.py'
```
