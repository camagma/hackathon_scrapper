# Reminder behavior

## Calendar-day selection

`devpost_reminder/reminders.py` calculates `days_left` as the difference between two calendar dates. It never converts the submission deadline into midnight or infers a cutoff timezone from Devpost.

The current date comes from the configured IANA timezone, defaulting to `Europe/Kyiv`. The dispatcher captures that date once per batch. An explicit date can be supplied to the Python API for deterministic tests; the CLI's `--today` override is restricted to preview mode.

| Days remaining | Behavior |
| --- | --- |
| Exactly 7 | Eligible if `reminded_7d` is false |
| Exactly 1 | Eligible if `reminded_1d` is false |
| Any other value, including zero or negative | No reminder |

Only `is_current` events that pass all configured status, location, theme, and keyword filters qualify. Fetched and stored events share the same filter implementation. Selection is deduplicated by event ID and ordered by deadline, then ID.

There is no catch-up window: a skipped 7-day run does not generate a reminder 6 days before the deadline. A failed send may be retried on the same threshold day. The separate 1-day reminder remains eligible even if the 7-day reminder was missed or already sent.

## Message text

Messages include the title, ISO submission deadline, days remaining, and event URL. The label explicitly identifies the end of project submissions, not registration:

```text
AI Agent Challenge
Дата окончания приёма проектов: 2026-11-10
Осталось дней: 7
https://example.com/
```

## Dispatch contract

`deliver_reminders(connection, config, send, today=...)` accepts a callback `send(text)`. It must return normally only after confirmed success and raise an exception on failure. The dispatcher records each successful reminder before proceeding to the next event. It returns counts of sent, failed, and skipped candidates.

Sender exceptions are logged with event ID, threshold, and exception type. Exception strings are omitted because transport errors can contain URLs carrying credentials. Sender failures leave flags unchanged and do not prevent other reminders from being attempted. SQLite errors propagate and stop delivery.

For each candidate, the dispatcher acquires an immediate SQLite write transaction, reloads the event, and rechecks filters, deadline, and reminder state. It holds that lock through sending and flag persistence. A second dispatcher sharing the same database must wait and recheck the committed flag. A candidate that became ineligible is skipped. The two reminder flags are independent and survive metadata updates and deadline changes.

## Delivery limits

This provides durable deduplication for successful ordinary runs and concurrent dispatchers sharing one database. It cannot make an external API and SQLite commit atomically. A process crash after delivery but before flag persistence, a failed SQLite commit after delivery, or a timeout after the service accepted the message leaves delivery uncertain. A retry can duplicate that message. Flags are not preemptively set because that would silently lose reminders when sending fails.

Independent database copies cannot coordinate through SQLite locks. The daily GitHub Actions workflow serializes its runs and restores the latest persisted state before delivery. Independent local runs are outside that coordination.

## Preview

```sh
python -m devpost_reminder --offline inspection/response.json --db data/demo.sqlite3 --preview-reminders --today 2026-11-05
```

This imports the snapshot, then previews pending reminders from current stored events. It does not invoke a sender or mark reminder flags. Use a separate demo database for saved snapshots.

## CLI delivery

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`, then run:

```sh
python -m devpost_reminder --send-reminders
```

Credentials are validated before network access or database updates. The CLI fetches a complete listing, saves it, and connects the dispatcher to `TelegramClient.send_message`. The sender uses the configured HTTP connect/read timeouts. Successful sends retain their flags even if a later send fails; the summary reports all outcomes and exits with code 1 when any sender call fails.

`devpost_reminder.app.run` coordinates these operations and returns a `RunResult` without printing. `devpost_reminder/cli.py` handles argument parsing, console output, and exit codes. The same application entry point can be called without CLI arguments; it validates delivery and preview modes before performing any side effects.

Sending is mutually exclusive with preview mode. Offline snapshots and `--today` are only available for inspection and previews, so live delivery uses current fetched state and the configured timezone's actual date. A failed fetch prevents all sends. Plain listing mode never loads Telegram credentials or sends messages.
