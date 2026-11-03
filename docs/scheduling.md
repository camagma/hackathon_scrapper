# Schedule daily reminders

Choose GitHub Actions for hosted runs, or cron on a Linux machine with persistent storage. Use one scheduler for a bot: an independent local database does not share reminder flags with the Actions database.

## GitHub Actions

### Add repository secrets

Create the bot and get its private chat ID using the [Telegram setup guide](telegram.md). In your repository, open **Settings → Secrets and variables → Actions → Secrets → New repository secret** and add:

| Name | Value |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | The token issued by BotFather |
| `TELEGRAM_CHAT_ID` | Your destination chat ID, including any leading minus sign |

Use repository secrets, not Actions variables or environment secrets: this workflow references `secrets` directly and does not select an environment. Do not add quotes around values in the GitHub form. See [GitHub's secrets guide](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets).

### Check repository permissions

Ensure GitHub Actions is enabled and your repository's action policy permits `actions/checkout` and `actions/setup-python`. The workflow requests `contents: write` for its reminder job. The automatic `GITHUB_TOKEN` handles Git access; do not create a separate token secret.

Repository or organization rules must allow that token to create and update `bot-state`. Rules requiring pull requests or signed commits on every branch can block state publication; scope those rules appropriately for this dedicated state branch. Keep protections for application code.

Do not create an empty `bot-state` branch manually. The helper creates it on the first successful save. An existing state branch without a valid database is treated as an error rather than an invitation to reset reminder history.

### Run it once

1. Open **Actions → Daily hackathon reminders → Run workflow**.
2. Select the repository's default branch, normally `main`, and start the run.
3. Check **Restore reminder state**, **Fetch hackathons and send reminders**, and **Save reminder state** in the job logs.
4. Confirm that `bot-state` contains `hackathons.sqlite3` after the application created a database and saving succeeded.

The workflow is already configured for manual runs. It must exist on the default branch; see [GitHub's manual-run guide](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow). This workflow skips delivery if you choose another branch.

A green run with `0 sent` is normal when no unsent reminder is due. A red application step can still have a successful save step: previously sent reminders need their flags preserved. A failed restore must prevent delivery, and a failed save requires investigation before another attempt. See [state failure handling](state.md#failures-and-recovery).

### Daily operation

The schedule is `17 7 * * *`: 07:17 UTC daily, corresponding to 09:17 in Kyiv in winter and 10:17 in summer. Edit `.github/workflows/reminders.yml` to change it. The app still uses `timezone` in `config.toml` to determine its current calendar date.

GitHub may delay scheduled jobs; this is not an exact-time service. Runs are serialized without cancelling the current run. Avoid manually cancelling delivery because the runner may have flags that are not yet saved remotely. Inspect failed runs, especially the save step, before retrying.

The workflow explicitly uses `data/hackathons.sqlite3` for restore, delivery, and save. Keep those paths aligned if you change them. Local reminder history is not automatically uploaded: hosted runs start from `bot-state`, not your workstation's database.

## Linux cron alternative

Use an always-on machine and a persistent project directory. The examples below assume `/home/you/apps/hackathon_scrapper`; replace `/home/you` with your own absolute home path throughout. Install the project dependencies in that directory's `.venv` using Python 3.11+.

Create a private shell file at `/home/you/.config/devpost-reminder.env`:

```sh
export TELEGRAM_BOT_TOKEN='<YOUR_TOKEN>'
export TELEGRAM_CHAT_ID='<YOUR_CHAT_ID>'
```

Set its permissions to `600`. This file is outside the repository and is explicitly sourced by the wrapper; the application does not load `.env` files itself.

Create `/home/you/bin/run-devpost-reminders`:

```sh
#!/bin/sh
set -eu
. /home/you/.config/devpost-reminder.env
cd /home/you/apps/hackathon_scrapper
exec .venv/bin/python -m devpost_reminder --send-reminders
```

Set the wrapper's permissions to `700` and create `/home/you/.cache`. Run the wrapper manually first to check credentials and dependencies.

Open `crontab -e` and add this single line:

```cron
17 9 * * * /usr/bin/flock -n /home/you/.cache/devpost-reminder.lock /home/you/bin/run-devpost-reminders >> /home/you/.cache/devpost-reminder.log 2>&1
```

This runs at 09:17 in the cron host's timezone. Confirm that timezone and the path to `flock` on your host. The lock skips overlapping runs; output is appended to a local log. Monitor the log for failures and configure rotation as needed. See the [crontab manual](https://man7.org/linux/man-pages/man5/crontab.5.html) for scheduling and environment behavior.

Cron does not inherit variables from your interactive terminal; the wrapper sources them explicitly. The virtual environment is invoked by path, so shell activation is unnecessary. SQLite stays on local disk between runs, and no `state_db.py` restore/save is needed. Preserve the database file to retain reminder flags.

Disable the GitHub workflow if switching to cron, and reconcile any existing reminder history before sending from a different database. These instructions do not enable either scheduler or create secrets automatically.
