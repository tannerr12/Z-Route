# Private NAP / NAPCont view backed by the team's sheet

This replaces the need to host SQLite for the existing team's records. Google hosts an Apps Script web app; the sheet stays private. The team's existing workflow and sheet are unchanged. No source rows are bundled in Git or published as CSV.

## One-time owner deployment

1. Open the team's Google Sheet and choose Extensions > Apps Script (or create a standalone Apps Script project under an account with access to it).
2. Add `Code.gs`. Copy `Normalizer.js` into an Apps Script file named `Normalizer.gs`. Add an HTML file named `Index` containing `Index.html`. Enable the manifest in project settings and use `appsscript.json` for read-only Sheets scope.
3. In Project Settings > Script Properties set `NAP_SHEET_ID` to the team's spreadsheet ID. Set `NAP_KEY_SHA256` to the lowercase SHA-256 hex digest of a randomly generated alliance access key of at least 32 characters. Keep the actual key outside the code, sheet and deployment URL. For example, locally generate and hash one using Python's `secrets.token_urlsafe(32)` and `hashlib.sha256(key.encode()).hexdigest()`. Share the actual key privately with intended readers; never share the project editor or hash-setting access with regular readers.
4. Deploy > New deployment > Web app. Execute as the owner. Choose the access audience appropriate for the alliance; anonymous access, when allowed by account policy, is protected by the custom key on every data read. The owner must authorize private-sheet access. Domain policy may restrict audiences. This deployment and OAuth authorization cannot be performed through the available Drive read/write connector.
5. Open the `/exec` deployment URL, verify a wrong key returns no records, verify the right key loads both tabs, then test locking. Update the published deployment version after changing script files. Give members that URL, or enter it in the Google Sheets section of the site's Private Incidents page. Do not publish the source sheet or put the access key in URLs.

To rotate access, replace `NAP_KEY_SHA256`. Every subsequent refresh checks the current hash. Readers may already have downloaded prior results. Keys remain in page memory only; locking clears data and invalidates pending callbacks. Shared-key readers can see all returned NAP/contact records; names are not verified identities. Google quotas apply; this is a small alliance dashboard, not a public high-volume API.

## Mapping and caveats

- `NAP` header is detected after the legend, accepting the current `Agressor` spelling. Aggressor/victim alliance columns are resolved beside those headings. Unexpected layouts stop with an error.
- `NAPCont` is a contact directory, accepting `Allaince`. Columns after Discord are retained as notes/extra contacts. Empty contact details remain blank, not invented.
- Dates with explicit years normalize as US month/day/year. Dates lacking a year stay raw and are flagged; the spreadsheet's Chicago timezone does not alter incident date strings. Source row order remains available.
- G has no heading; G values, H authorization text, I coordinator text, and J onward notes remain raw. These are not automatically treated as penalties, incident confirmation, authorization of the original attack, or completed retaliation.
- Victim `Total` rows are separated from incidents. Exactly identical rows are grouped with all original row references and a review warning; grouping is not proof they represent one event. No score deduction or destructive deduplication occurs.
- Row colours matching the red/yellow legend are shown as source flags, never evidence establishing a violation. Conditional formatting is not interpreted as case status.
- No fuzzy identity matching or public player-score changes. No source-sheet writes or form appends. The team continues entering and correcting incidents in Sheets.

Tests use invented fixtures, not the team's records: `node --test services/nap-sheets/normalizer.test.js`. A mocked Apps Script test verifies authorization precedes private-sheet access. A real owner-authorized deployment is still required to verify permissions, quotas and actual live rendering.
