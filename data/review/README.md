# Performance Review supplementary data

The public **review.html** page combines these existing public files automatically:

- `data/donations/<guild>/donations.csv` — `week_start,rank,username,role,points,captured_at,evidence`
- `data/vs/<guild>/rankings.csv` — `week_start,day,rank,username,alliance,points,captured_at,evidence`

The review applies configurable **per-week** donation minimum (default 25,200)
and **per-day** VS goal (default 1,000,000), showing missing entries separately
from observed below-target scores. It counts only players seen in either dataset.

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
feature. Frenzy participation and alliance join dates are not currently present
in the published donation/VS schema. Unknown values display as a dash.

Published D3AD donation and VS data currently contain rows tagged `DEMO`.
Replace those with actual captured records before using the review for
leadership decisions. The page labels demo data and exports the currently
displayed reporting week as CSV.
