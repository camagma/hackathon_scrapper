# Devpost Hackathon Reminder

A Python project for tracking online Devpost hackathons and receiving submission deadline reminders in Telegram.

**Status: early development.** The repository currently provides a Devpost listing inspection tool and a saved response for offline exploration. Filtering, SQLite storage, reminders, Telegram delivery, scheduled runs, and CSV export are planned.

## Quick start

Requires Python 3.11 or newer.

```sh
git clone https://github.com/camagma/hackathon_scrapper.git
cd hackathon_scrapper
python -m venv .venv
```

Activate the virtual environment:

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
```

```sh
# macOS / Linux
source .venv/bin/activate
```

Install dependencies and inspect the saved response without making network requests:

```sh
python -m pip install -r requirements.txt
python inspect_endpoint.py --offline inspection/response.json
```

The command prints three unmodified hackathon records, response metadata, and all observed field names.

To inspect a fresh listing page:

```sh
python inspect_endpoint.py
```

This checks `robots.txt`, fetches one JSON page, and updates the snapshots in `inspection/`. Requests use an explicit User-Agent and timeouts. HTTP errors stop the command without retries.

## Deadline semantics

The inspected listing exposes a **submission period**, with no separate registration deadline. Planned reminders will refer to the end of that submission period.

Dates are human-readable ranges without a time or timezone. They represent calendar dates, not exact cutoff timestamps. See the [Devpost data reference](docs/devpost-data.md) for the observed schema and limitations.

## Roadmap

- Filter online hackathons by status, theme, and keyword.
- Store events in SQLite with idempotent updates.
- Send Telegram reminders 7 days and 1 day before the submission deadline.
- Run daily through GitHub Actions with persistent reminder state.
- Deliver deadline-sorted CSV exports through Telegram, weekly by default.

## License

[MIT](LICENSE)
