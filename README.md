# Devpost Hackathon Reminder

A Python project for tracking online Devpost hackathons and receiving reminders before hackathons open for submissions in Telegram.

Fetch, filter, and store Devpost hackathons in SQLite. Preview or send 7-day and 1-day opening reminders and scheduled CSV exports through Telegram, locally or with GitHub Actions. Reminder and export history persist between runs.

## Quick start

Requires Python 3.11 or newer. Replace `OWNER/REPOSITORY` below with your repository path.

```sh
git clone https://github.com/OWNER/REPOSITORY.git devpost-reminder
cd devpost-reminder
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

Install dependencies and list events from a saved response without making network requests:

```sh
python -m pip install -r requirements.txt
python -m devpost_reminder --offline inspection/response.json --db data/demo.sqlite3
```

The command saves events to a demo database and prints matching titles, links, parsed submission dates, themes, prizes, locations, and statuses, sorted by submission deadline. An offline snapshot represents a single page; the command warns when it is incomplete.

To fetch and filter the current listing:

```sh
python -m devpost_reminder
```

This checks `robots.txt` and fetches bounded listing pages. It does not modify the snapshots in `inspection/`. Use `python scripts/inspect_endpoint.py` to refresh the original single-page inspection snapshot instead.

## Project structure

```text
devpost_reminder/       Application package
  __main__.py          python -m devpost_reminder entry point
  cli.py               Arguments, console output, and exit codes
  app.py               Fetch, store, and deliver workflow
  config.py            TOML configuration
  fetch.py             Devpost HTTP client
  filters.py           Shared filtering rules
  dates.py             Submission date parsing
  storage.py           SQLite persistence
  reminders.py         Reminder selection and delivery
  telegram.py          Telegram HTTP client and credentials
  export.py            CSV generation, schedules, and delivery
scripts/               Inspection and runner state tools
tests/                 Offline tests
docs/                  Data, storage, and reminder references
inspection/            Saved Devpost responses and robots.txt
config.toml            Runtime settings
```

Run commands from the repository root. No package installation is required.

## Configuration

Edit [config.toml](config.toml), or pass `--config path/to/config.toml`:

```toml
online_only = true
statuses = ["open", "upcoming"]
themes = ["Machine Learning/AI"]
keywords = ["agent", "Python"]
database_path = "data/hackathons.sqlite3"
timezone = "Region/City"

[export]
mode = "weekly"
weekday = 0
```

Replace `Region/City` with a valid IANA timezone name before using this example.

An empty `themes` or `keywords` array disables that filter. Theme names match exactly, ignoring case. Keywords match substrings in titles, organization names, or themes, ignoring case. Values within each list use OR; separate filters use AND. There is no description search because the listing does not provide descriptions.

Online and status filters are sent to Devpost and checked again locally. Theme and keyword filtering happens locally without additional requests. Setting `online_only = false` includes both online and in-person events.

The `[http]` section controls request limits. Defaults request 40 records per page, at most 10 pages, with a two-second pause between requests, a clear User-Agent, and connect/read timeouts. The client respects robots crawl delays and request rates. HTTP 429 and selected transient server errors receive at most two retries with backoff and `Retry-After` handling. If the required wait exceeds 120 seconds, the run stops rather than retrying early. Other HTTP errors and connection failures stop the run.

Incomplete pagination, an unexpected schema, or exhausted retries produce a nonzero exit status without printing a partial listing. Increase `http.max_pages` if the listing exceeds its configured limit. Individual project pages and participant profiles are never requested.

## Storage

The SQLite database is created automatically using Python's standard-library `sqlite3`. `database_path` is relative to the configuration file. Override it with `--db path/to/state.sqlite3`, relative to the current working directory.

Every fetched event is stored, including events excluded by the local theme or keyword filters. The console shows only matches from the current fetch. Devpost IDs are primary keys: repeated runs refresh existing rows without duplicates. The opening reminder flags default to false and remain unchanged on updates, including date changes. Legacy submission-deadline flags are retained separately and do not suppress opening reminders.

A successful full online fetch marks absent events as no longer current while retaining their history. Offline imports merge their page without deactivating missing events; use a separate demo database to avoid mixing old snapshots with live state. Parsing finishes before storage starts, and updates are transactional, so a failed fetch or invalid date does not partially replace the previous snapshot.

Database files are ignored by Git. Keep the database between runs to retain reminder flags. See the [storage reference](docs/storage.md) for schema and state semantics.

## Reminders

Bot-generated reminder text and CSV captions are in English. Event titles and other Devpost data retain their original language.

Reminders are due exactly 7 days or 1 day before submissions open (`start_date`), and only for current events with status `upcoming` that match all configured filters. Open events do not receive submission-deadline reminders. Keep `upcoming` in the configured statuses to enable reminders. Calendar days are calculated in the configured IANA `timezone`, independently of the machine's timezone. `tzdata` supplies portable timezone data, including on Windows.

Preview reminders using the current date:

```sh
python -m devpost_reminder --preview-reminders
```

Preview a saved response on a fixed date, without network access:

```sh
python -m devpost_reminder --offline inspection/upcoming.json --db data/demo.sqlite3 --preview-reminders --today 2026-11-02
```

Preview mode still imports events into SQLite, but does not send messages or change reminder flags. `--today` requires `--preview-reminders`. Previewing repeatedly shows the same unsent reminders.

To fetch current events and send due reminders after setting the Telegram environment variables:

```sh
python -m devpost_reminder --send-reminders
```

Sending requires a complete live fetch and cannot be combined with `--offline`, `--preview-reminders`, or `--today`. Credentials are checked before fetching or updating the database. The command reports sent, failed, and skipped reminders and exits nonzero if any send fails.

The dispatch module commits each flag after a successful send. Sender failures leave that reminder eligible for another run on the same threshold day, without undoing successful reminders. Repeated and overlapping dispatches sharing one SQLite file recheck flags under a write lock. Missed threshold days are not backfilled. Running without `--send-reminders` never sends messages.

External message delivery and SQLite cannot commit atomically. A crash after external delivery but before the flag commits, or an ambiguous transport failure, can still cause a duplicate on retry. See [reminder behavior](docs/reminders.md) for the delivery contract and limits.

Telegram credentials are read from `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` when the delivery loader is called. They are not read from TOML or `.env` files, and are not required for listing or previews. Missing or blank values raise a configuration error; credential values are omitted from errors and object representations.

`TelegramClient.send_message` implements the plain HTTP [sendMessage API](https://core.telegram.org/bots/api#sendmessage) using a caller-owned requests session. It sends JSON without a parse mode, applies the configured HTTP connect/read timeouts, rejects redirects, and requires a successful API response with a message ID. Errors omit raw response bodies and credential-bearing transport exception strings. Sends are not retried automatically; HTTP 429 activates a per-client cooldown using `retry_after` (60 seconds if unavailable).

## Telegram setup

1. Create a bot through [@BotFather](https://t.me/BotFather) with `/newbot` and save its token.
2. Open your new bot, press **Start**, and retrieve your private chat ID using the [setup guide](docs/telegram.md#get-your-chat-id).
3. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in your shell, then run `python -m devpost_reminder --send-reminders`.

The [Telegram setup guide](docs/telegram.md) includes PowerShell and Bash commands, an explanation of empty results, and common delivery errors. Messages are sent only when an unsent 7-day or 1-day reminder is due; a successful run can report zero sent.

## Scheduled runs

The [daily GitHub Actions workflow](.github/workflows/reminders.yml) runs at 07:17 UTC and supports manual runs from the default branch. Configure Actions secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` before using it. Its GitHub token needs permission to write the separate `bot-state` branch.

Each run checks opening reminders and the CSV schedule. The default CSV schedule sends weekly on Monday; other daily runs still check reminders.

The workflow restores SQLite before delivery and saves it afterward, including after partially failed sends. Runs share one concurrency group. See [state persistence](docs/state.md#daily-workflow) for permissions, failure behavior, and recovery limits. GitHub schedules may be delayed; they are not an exact-time guarantee.

Follow the [scheduling guide](docs/scheduling.md) to add GitHub Secrets, check the first run, or use Linux cron with a persistent local database instead.

## CSV exports

The [export module](devpost_reminder/export.py) generates a temporary CSV from stored events using configured location, status, theme, and keyword filters. Unlike opening reminders, it can include both open and upcoming events according to those settings. It includes IDs, titles, links, submission start dates, deadlines, days remaining, themes, prizes, and states, ordered by deadline and ID. Files use `utf-8-sig` for Excel and are removed after use.

The Telegram client can upload these CSVs with `sendDocument` and a caption containing the event count and nearest submission deadline. A document preserves a downloadable table for Excel instead of placing the CSV contents in a chat message.

`[export]` accepts `mode = "daily"`, `"weekly"`, or `"new"` (only when new matching events appear). The default is weekly on Monday; `weekday` uses Monday=0 through Sunday=6. SQLite stores the last successful export date and included IDs separately from reminder flags. Existing databases upgrade automatically.

Send only the CSV when its configured schedule is due:

```sh
python -m devpost_reminder --send-export
```

Send opening reminders and check the CSV schedule in one run, as the workflow does:

```sh
python -m devpost_reminder --send-reminders --send-export
```

Both commands require Telegram environment variables and a complete live fetch. `--send-export` respects the schedule; it does not force an upload. For a first test on any weekday, set `mode = "daily"` in `[export]`. Repeating a successful daily export on the same date skips it. Omit `--send-export` for reminder-only delivery.

An export sends the CSV or a short empty-selection text, then records confirmed success. Failures are logged independently of reminders; a failure in either operation produces a nonzero exit status while preserving successful delivery state. See the [CSV reference](docs/export.md) for selection and scheduling behavior.

## Checks

Install development dependencies and run the offline test suite:

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Tests use fake HTTP responses, injected senders, and temporary databases. An automatic pytest fixture blocks accidental HTTP requests. Coverage includes date ranges, timezone boundaries, filtering, HTTP policy, SQLite updates, independent reminder flags, repeated runs, sender failures, overlapping dispatches, and CLI previews.

## Deadline semantics

The inspected listing exposes a **submission period**, with no separate registration deadline. Reminders use the start of that period as the opening date for upcoming events. The end remains the submission deadline in storage and CSV exports; it is not a registration cutoff.

Dates are human-readable ranges without a time or timezone. They represent calendar dates, not exact cutoff timestamps. See the [Devpost data reference](docs/devpost-data.md) for the observed schema and limitations.

The parser handles same-month and cross-month ranges, explicit years spanning New Year, and single-day events. A single date is used for both start and deadline. Unknown formats and impossible dates stop the sync instead of guessing a deadline.

## License

[MIT](LICENSE)
