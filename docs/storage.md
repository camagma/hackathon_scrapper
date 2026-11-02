# SQLite storage

## Database lifecycle

`storage.py` uses the standard-library `sqlite3` module. The CLI creates the configured parent directory and initializes schema version 1 automatically. The version is stored in `PRAGMA user_version`; an unsupported future version is rejected.

The default location is `data/hackathons.sqlite3`, resolved relative to `config.toml`. `--db` overrides it with a path relative to the current working directory. Connections use a 30-second lock timeout and are explicitly closed after use, including on Windows.

## Hackathons table

| Column | Storage format / purpose |
| --- | --- |
| `id` | Integer primary key from Devpost |
| `title`, `url` | Display title and event URL |
| `start_date`, `deadline` | ISO calendar dates, `YYYY-MM-DD` |
| `submission_period` | Original Devpost date range |
| `themes` | JSON array of theme names, preserving Unicode |
| `prize` | Plain text with HTML removed |
| `open_state`, `location`, `organization_name` | Metadata for filtering and display |
| `is_current` | Boolean integer indicating membership in the latest complete fetched scope |
| `reminded_7d`, `reminded_1d` | Independent boolean integers, initially `0` |

An index on `(deadline, id)` supports stable deadline ordering. Boolean and date-order constraints guard stored state. The date parser validates calendar dates before they reach SQLite.

## Update semantics

Each batch uses `INSERT ... ON CONFLICT(id) DO UPDATE`, not row replacement. Reminder flags are omitted from updates: changing a title, deadline, themes, or status cannot clear them. A changed deadline therefore does not grant an event another reminder of a type already sent. Events that disappear and return retain their flags as well.

The batch is deduplicated by Devpost ID. An immediate transaction locks writes before counting existing events or updating snapshot membership. Metadata updates and membership changes either all commit or all roll back.

The CLI normalizes every fetched record before opening the database. Unknown date formats fail the entire sync rather than silently keeping a misleading partial result.

## Current events and history

The database stores all fetched events; local theme and keyword filters affect console output, not storage. A complete online fetch atomically clears `is_current` and sets it for returned IDs. Events outside the current server-side scope, including those that disappeared or no longer match configured status/location filters, remain stored with `is_current = 0`.

This flag does not mean that registration is open, or that an event matches local filters. Reminder selection also applies all configured filters and exact deadline thresholds. Future exports must apply their own selection rules as well.

## Reminder transactions

The dispatcher locks the database with `BEGIN IMMEDIATE`, reloads each candidate, and rechecks its eligibility before sending. It updates only the matching `reminded_7d` or `reminded_1d` flag after the sender confirms success, then commits that event independently. A later sender failure does not roll back previously sent reminders. `mark_reminded` requires an explicit transaction and does not commit on its own.

The write lock spans the send callback, serializing overlapping dispatchers that use the same database file. Callbacks should use bounded HTTP timeouts. This coordination does not cover independent copies of the SQLite file on different runners. Workflow-level coordination will be added with scheduling.

See [reminder behavior](reminders.md) for external-delivery failure limits.

Offline snapshots are incomplete and may be old. Importing one only inserts or refreshes its events and marks those events current; it does not deactivate events absent from that page. Use a separate database for offline experiments:

```sh
python main.py --offline inspection/upcoming.json --db data/demo.sqlite3
python main.py --offline inspection/upcoming.json --db data/demo.sqlite3
```

The second run reports zero new rows. `refreshed` counts existing IDs processed, even when their metadata did not change.

## Durable state

SQLite files and their journal files are ignored by Git. Copy or back up the database while the application is stopped. Removing or replacing it loses reminder history. GitHub Actions persistence will be implemented with the scheduled workflow; the current CLI stores state locally only.
