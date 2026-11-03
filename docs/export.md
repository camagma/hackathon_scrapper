# CSV exports

`devpost_reminder.export.generate_csv(events, config, today)` generates a CSV from an iterable of stored `Hackathon` records. It uses the standard-library `csv` module and needs no additional dependencies.

## Selection and columns

The export includes current records that match the configured location, status, theme, and keyword filters. It can include open and upcoming events; the reminder-only upcoming restriction does not apply to CSV selection. Historical records marked `is_current = false` are excluded. Reminder flags do not affect export selection. The module deduplicates IDs and sorts by submission deadline ascending, then ID for stable ordering.

Columns are written in this order:

```text
id,title,url,start_date,deadline,days_left,themes,prize,open_state
```

Dates use `YYYY-MM-DD`. The deadline is the end of the submission period, not a separate registration deadline. `days_left` is the difference between the deadline and the supplied calendar date. There is no additional date filter: current records can have zero or negative days remaining if the source still lists them. Theme names share one cell, separated by `; `. Prize text comes from normalized storage records.

The file uses comma-separated columns, standard CSV quoting, `newline=""`, and `utf-8-sig` encoding. The UTF-8 BOM supports opening non-ASCII text correctly in Excel; CSV quoting preserves commas, quotes, and embedded newlines.

## Temporary files

The generator is a context manager. Inside its context, it yields a `CsvExport` containing the temporary file path, event IDs, count, and nearest deadline. A caller must read or upload the file before leaving that context. The file and its temporary directory are removed on both normal exit and exceptions.

When no events match, the generator yields `None` and does not create a file. Generation does not write to SQLite or change reminder flags, and CSVs are never stored in the repository. The separate delivery function updates successful-export history.

## Telegram upload

`TelegramClient.send_document(path, caption)` uploads a CSV through the plain HTTP [sendDocument API](https://core.telegram.org/bots/api#senddocument) using multipart/form-data. The client supplies the same environment-based credentials as text delivery. The caption is plain text, with a maximum of 1024 characters.

`CsvExport.caption` includes the event count and nearest submission deadline. Upload within the export context so the file remains available:

```python
with generate_csv(events, config, today) as report:
    if report is not None:
        client.send_document(report.path, report.caption)
```

Using a document retains the CSV's encoding and structure as a downloadable file that can be opened in Excel. Sending the contents as a chat message would lose that file workflow and run into message-length limits.

The upload closes its file handle even on failure. It shares text delivery's timeouts, redirect rejection, sanitized errors, and rate-limit cooldown. Empty files are rejected locally. Telegram rejections and uncertain transport failures raise `TelegramError`; automatic upload retries are not performed.

## Delivery status

`deliver_export` connects generation, upload callbacks, scheduling, and successful-export storage. The CLI's `--send-export` option and daily workflow use it after opening reminders, if reminders were requested.

The function takes a SQLite connection, configuration, document and text sender callbacks, and the current calendar date. It returns a status (`sent`, `empty`, `skipped`, or `failed`) and an event count. Both callbacks must raise on failure and return normally only after confirmed delivery.

Selection, the schedule check, delivery, and success recording share one immediate transaction. Overlapping calls using the same database therefore observe the first call's committed success before deciding whether to send. A due nonempty export sends the full matching selection, even in new-event mode. After confirmed delivery, it records all exported IDs and the date.

If a daily or weekly export is due but no events match, it sends `No hackathons match your current filters.` without creating or uploading a file. Confirmed text delivery records the date and an empty ID set. New-event mode with an empty selection is not due and sends nothing.

File, sender, and database exceptions are logged by exception type and returned as `failed`; raw exception text is omitted to avoid credential-bearing URLs. The transaction rolls back and temporary files are cleaned up. Reminder delivery can continue independently. A successful external send followed by a failed database commit remains subject to the same uncertain-delivery limits as reminders.

## Run from the CLI

```sh
python -m devpost_reminder --send-export
python -m devpost_reminder --send-reminders --send-export
```

The first command only checks the export schedule; the second also sends opening reminders. Both require the same Telegram environment variables and a live fetch. Offline mode, preview mode, and date overrides cannot be combined with CSV delivery. Plain listing and preview modes never send a CSV.

The summary reports `CSV export: sent`, `empty`, `skipped`, or `failed`, plus the event count. A skipped export means its schedule is not due or its successful snapshot already covers the current date/new-event selection. `--send-export` does not bypass these checks. To test on a non-Monday, temporarily set `[export].mode = "daily"`; after a successful export, subsequent runs that day skip it.

The application captures one date in the configured timezone for reminders and CSV. It attempts exports even after individual reminder failures and reports a failed process exit if either operation fails. On HTTP 429, the shared Telegram client's cooldown applies to both methods, so delivery may need a later run after that cooldown.

The daily workflow passes both flags. Its final save step retains reminder and export history in the same SQLite snapshot, including after partial failures. Cron users can pass both flags in their wrapper too.

## Schedule settings

Configure an independent CSV schedule in `config.toml`:

```toml
[export]
mode = "weekly"
weekday = 0
```

| Mode | When an export is due |
| --- | --- |
| `daily` | Once per calendar date after the last successful export |
| `weekly` | On the configured weekday, unless already successful that date |
| `new` | Only when matching event IDs have appeared since the last successful export |

The default is `weekly`, with `weekday = 0` (Monday). Weekdays run from 0 through 6 (Sunday); the setting only affects weekly mode. Unknown settings and invalid values fail configuration loading.

`export_due` takes the current calendar date, last successful export date, and a `has_new` flag. The caller must supply dates in the configured timezone. The rule does not perform network requests or change state. Only confirmed success should advance the supplied history; a failed upload remains eligible for retry.

Weekly exports do not catch up on another weekday after a missed run. New-event mode may export more than once on the same day if additional matching IDs appear. A date earlier than the last successful export never triggers a new export. These rules do not affect 7-day or 1-day reminders.

## Successful-export state

SQLite schema version 2 adds `export_state`, storing the last successful date and the IDs in that export. The upgrade preserves all existing event rows and reminder flags. Reading a fresh database returns empty export state, so the first nonempty selection has new IDs.

`ExportState.has_new(ids)` compares the current matching IDs with the previous successful snapshot. Removing an ID does not count as a new event; an ID absent from that snapshot does, including a returning event or one newly included by a filter change. The next successful export replaces the snapshot with all currently exported IDs.

State is recorded only after the sender confirms the document or the empty-selection text. The recording helper requires a transaction; `deliver_export` enforces the send-before-record order. Failed sends never advance success. A confirmed empty-selection text records an empty ID set, preventing repeated daily or weekly empty notifications on the same date.
