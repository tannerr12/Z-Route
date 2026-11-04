# Z Route bot execution schedules

The intended times are **UTC**, not the Windows machine's local timezone.

| Bot | UTC time | Cadence | Status |
|---|---|---|---|
| Donations | Sunday 23:00 | Weekly | Configured; command not yet wired |
| VS | Saturday 23:00 | Weekly | Configured; command not yet wired |
| Player Activity | 04:00 | Daily | Configured; scanner not yet implemented |
| Map Scanner | — | Manual | Disabled |

The source of truth is [bot_schedule.json](bot_schedule.json). These settings are **not active Windows scheduled tasks**. GitHub Pages cannot execute BlueStacks/ADB automation. Install a local Windows Task Scheduler runner once each bot has an independently runnable command. Use UTC conversion at execution time, not a fixed Eastern offset, to avoid DST drift.

For the existing Data Miner, `python -m data_miner.mine_rankings --week-start YYYY-MM-DD --guild D3AD` currently performs **both VS and donation extraction in one run**. It should be split into separately callable workflows before enabling the Saturday and Sunday tasks, otherwise the scheduled jobs will unintentionally run both scanners. The new Player Activity bot also needs to be implemented before its daily task can run.

A future local runner should:
- Read `bot_schedule.json` and evaluate due runs in UTC.
- Use a single-process lock to prevent concurrent ADB/BlueStacks use.
- Write start, completion, failure, and extracted-row counts to a local execution log.
- Retry transient UI failures conservatively and never mark an incomplete scan as successful.
- Publish only validated CSV changes to GitHub after a successful run.
- Catch up on missed scheduled runs only after checking whether the underlying game data remains available.
