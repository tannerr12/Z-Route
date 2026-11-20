# Private incident service

The GitHub Pages site can display `incidents.html`, but cannot enforce authentication or store shared private reports. Deploy this WSGI service on a private writable host behind HTTPS before using that page. Until a host is configured the page accepts no reports. No deployment, domain, key or incident database is included in Git.

Configuration via host environment only:
- INCIDENT_DB: absolute path outside the public web root on persistent private storage (restrict OS access to the service account).
- INCIDENT_REPORT_KEY and INCIDENT_REVIEW_KEY: distinct cryptographically random keys, at least 32 characters; generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Share the reporting key with members, keep the review key with leadership. Rotate either by changing the environment and restarting. Existing SQLite data survives rotation.
- INCIDENT_ORIGIN: exact HTTPS origin of the dashboard, currently `https://tannerr12.github.io`.
- PORT: local reverse-proxy upstream port, default 8080.

Run `python services/incidents/app.py` for a local upstream. Terminate TLS and enforce rate/request limits at the reverse proxy; do not expose the development WSGI server directly. Use a production WSGI process supervisor and persistent disk/backups for deployment. The application binds loopback by default. Hosting access and TLS configuration are required; this repository does not provision them. Never upload database files or keys to Pages, artifacts or Git. Add an OS retention/backup policy appropriate to alliance needs.

GET /incidents and POST /incidents require a bearer reporting or review key. PATCH /incidents/{id} requires the review key. CORS is restricted to the configured origin; authorization is checked even for clients without Origin. Reports start as `reported`, never confirmed. Review transitions are stored in a private audit table. Submitted status/penalty from reporters are ignored. Leadership may assign 0–100 private review penalty points when confirming a report; dismissal/reopening resets them to zero and the audit table retains each transition. All members sharing a key can read the private log; names are self-reported, not authenticated individual identities. Shared keys cannot offer per-player attribution/revocation. No automatic public ranking penalty is applied.

Clients keep keys in memory, send no credentials in URLs, reject redirects, and render report strings as text. Evidence is an HTTPS link only; the service never fetches it. No files are uploaded. Both server responses and requests disable caching. Locking clears the page's session and visible records. Browser extensions, clipboard sharing and someone with the reporting key can still access the log; distribute keys accordingly.

Test: `python -m unittest discover -s services/incidents -p 'test_*.py'`.
