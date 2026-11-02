# Devpost Hackathon Reminder

A Python project for tracking online Devpost hackathons and receiving submission deadline reminders in Telegram.

**Status: early development.** Fetch and filter online hackathons from the Devpost listing, or explore saved responses offline. SQLite storage, reminders, Telegram delivery, scheduled runs, and CSV export are planned.

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

Install dependencies and list events from a saved response without making network requests:

```sh
python -m pip install -r requirements.txt
python main.py --offline inspection/response.json
```

The command prints matching titles, links, submission periods, themes, prizes, locations, and statuses. An offline snapshot represents a single page; the command warns when it is incomplete.

To fetch and filter the current listing:

```sh
python main.py
```

This checks `robots.txt` and fetches bounded listing pages. It does not modify the snapshots in `inspection/`. Use `python inspect_endpoint.py` to refresh the original single-page inspection snapshot instead.

## Configuration

Edit [config.toml](config.toml), or pass `--config path/to/config.toml`:

```toml
online_only = true
statuses = ["open", "upcoming"]
themes = ["Machine Learning/AI"]
keywords = ["agent", "Python"]
```

An empty `themes` or `keywords` array disables that filter. Theme names match exactly, ignoring case. Keywords match substrings in titles, organization names, or themes, ignoring case. Values within each list use OR; separate filters use AND. There is no description search because the listing does not provide descriptions.

Online and status filters are sent to Devpost and checked again locally. Theme and keyword filtering happens locally without additional requests. Setting `online_only = false` includes both online and in-person events.

The `[http]` section controls request limits. Defaults request 40 records per page, at most 10 pages, with a two-second pause between requests, a clear User-Agent, and connect/read timeouts. The client respects robots crawl delays and request rates. HTTP 429 and selected transient server errors receive at most two retries with backoff and `Retry-After` handling. If the required wait exceeds 120 seconds, the run stops rather than retrying early. Other HTTP errors and connection failures stop the run.

Incomplete pagination, an unexpected schema, or exhausted retries produce a nonzero exit status without printing a partial listing. Increase `http.max_pages` if the listing exceeds its configured limit. Individual project pages and participant profiles are never requested.

## Checks

Run the current offline filter and HTTP-policy tests with the standard library:

```sh
python -m unittest discover -s tests -v
```

The tests use in-memory HTTP responses and make no network requests. They can also be collected by pytest. Date and reminder tests will accompany those features.

## Deadline semantics

The inspected listing exposes a **submission period**, with no separate registration deadline. Planned reminders will refer to the end of that submission period.

Dates are human-readable ranges without a time or timezone. They represent calendar dates, not exact cutoff timestamps. See the [Devpost data reference](docs/devpost-data.md) for the observed schema and limitations.

## Roadmap

- Store events in SQLite with idempotent updates.
- Send Telegram reminders 7 days and 1 day before the submission deadline.
- Run daily through GitHub Actions with persistent reminder state.
- Deliver deadline-sorted CSV exports through Telegram, weekly by default.

## License

[MIT](LICENSE)
