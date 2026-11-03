# CSV exports

`devpost_reminder.export.generate_csv(events, config, today)` generates a CSV from an iterable of stored `Hackathon` records. It uses the standard-library `csv` module and needs no additional dependencies.

## Selection and columns

The export includes current records that match the configured location, status, theme, and keyword filters. Historical records marked `is_current = false` are excluded. Reminder flags do not affect export selection. The module deduplicates IDs and sorts by submission deadline ascending, then ID for stable ordering.

Columns are written in this order:

```text
id,title,url,start_date,deadline,days_left,themes,prize,open_state
```

Dates use `YYYY-MM-DD`. The deadline is the end of the submission period, not a separate registration deadline. `days_left` is the difference between the deadline and the supplied calendar date. There is no additional date filter: current records can have zero or negative days remaining if the source still lists them. Theme names share one cell, separated by `; `. Prize text comes from normalized storage records.

The file uses comma-separated columns, standard CSV quoting, `newline=""`, and `utf-8-sig` encoding. The UTF-8 BOM supports opening non-ASCII text correctly in Excel; CSV quoting preserves commas, quotes, and embedded newlines.

## Temporary files

The generator is a context manager. Inside its context, it yields a `CsvExport` containing the temporary file path, event IDs, count, and nearest deadline. A caller must read or upload the file before leaving that context. The file and its temporary directory are removed on both normal exit and exceptions.

When no events match, the generator yields `None` and does not create a file. The module does not write to SQLite, change reminder flags, or store CSVs in the repository.

## Delivery status

Generation is available independently of Telegram. CLI integration, `sendDocument`, export scheduling, and successful-export state will be added separately. No CSV is currently sent by the daily workflow. Empty selections will use a short text message when delivery is connected.
