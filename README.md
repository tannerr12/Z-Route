# Z Route Scanner

Private, experimental Python tool for scanning Z Route through visible BlueStacks using ADB screenshots and OCR.

## Status

Calibration-first prototype; **not validated against a live BlueStacks session**. Do not assume full map coverage or correct base coordinates until two different bases have been checked manually.

## Setup

Install Python 3.10+, Tesseract OCR, and Android Platform Tools (ADB). Enable Android Debug Bridge in BlueStacks Advanced settings.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item config.example.json config.json
python scanner.py test
```

## Database

SQLite tables: guilds, players, observations, guild_membership_history. Usernames are provisional identities; guild transfers and potential renames require review. Local databases, screenshots, config and progress are gitignored.

## Roadmap

1. Confirm ADB connection and OCR screenshot
2. Calibrate base popup and selected-base coordinate semantics
3. Add reliable base detection and a checkpointed serpentine map sweep
4. Add name-change candidate review and scan progress dashboard

Respect game rules and keep automated interaction rates conservative.
