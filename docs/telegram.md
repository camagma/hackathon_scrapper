# Set up Telegram reminders

## Create a bot

Open the official [@BotFather](https://t.me/BotFather), send `/newbot`, and follow the prompts for a name and username. Save the token it returns. See Telegram's [bot creation tutorial](https://core.telegram.org/bots/tutorial#obtain-your-bot-token).

Open your new bot's private chat and press **Start**, or send `/start`. Keep this chat available for the next step. A dedicated bot is easiest to configure because no other application will consume its updates.

## Get your chat ID

For this one-time manual setup, replace `<YOUR_TOKEN>` in this URL and open it locally:

```text
https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
```

In the returned `result` array, find your `/start` message and copy **`message.chat.id`**, not `update_id` or the bot's own ID. For example:

```json
{
  "ok": true,
  "result": [
    {
      "update_id": 1,
      "message": {
        "chat": {"id": 123456789, "type": "private"},
        "text": "/start"
      }
    }
  ]
}
```

Here the chat ID would be `123456789`; use the value from your own response. If `result` is empty, send a fresh message and request it again. Do not run another update consumer during setup. `getUpdates` is unavailable while a webhook is configured; use a new dedicated bot if your existing bot belongs to another integration. See the official [getUpdates reference](https://core.telegram.org/bots/api#getupdates).

The token-bearing URL is private. Do not commit it or share screenshots containing it. This lookup is a manual setup step; the application does not poll updates or run a webhook server.

## Configure your shell

Activate the project's virtual environment and install `requirements.txt` as shown in the [quick start](../README.md#quick-start). Run these commands from the repository root. Replace the example values with your token and chat ID.

Windows PowerShell:

```powershell
$env:TELEGRAM_BOT_TOKEN = "<YOUR_TOKEN>"
$env:TELEGRAM_CHAT_ID = "<YOUR_CHAT_ID>"
python -m devpost_reminder --send-reminders
```

Linux / macOS (Bash):

```bash
export TELEGRAM_BOT_TOKEN="<YOUR_TOKEN>"
export TELEGRAM_CHAT_ID="<YOUR_CHAT_ID>"
python -m devpost_reminder --send-reminders
```

These variables apply to the current shell and its child processes. Set them again in a new terminal. The application does not automatically load `.env` files and never reads Telegram credentials from `config.toml`. Keep real credentials out of tracked files.

## Check the result

The command fetches current hackathons, updates SQLite, and sends due reminders. Its final line reports sent, failed, and skipped counts. Zero sent is normal when no upcoming event matches the filters at exactly 7 or 1 days before submissions open, or the corresponding reminder was already sent.

Preview current reminders without sending or changing reminder flags:

```sh
python -m devpost_reminder --preview-reminders
```

Use the same database for previews and live runs to see the stored reminder flags. Use a separate demo database when importing old offline snapshots. Preserve your live SQLite file between runs.

To also check the CSV schedule, run `python -m devpost_reminder --send-reminders --send-export`. CSV uses the same token and chat ID, defaults to Mondays, and sends a short text if its scheduled selection is empty. See [CSV exports](export.md) for daily and new-event modes. The daily GitHub workflow already requests both reminders and exports.

| Problem | What to check |
| --- | --- |
| Missing environment variable | Set both variables in the shell that launches Python |
| HTTP 401 | Recheck the bot token; regenerate it through BotFather if necessary |
| HTTP 400 | Recheck the chat ID and confirm you started a chat with this bot |
| HTTP 403 | Unblock the bot and confirm it can send to the chosen chat |
| Rate limit / HTTP 429 | Wait for the server's cooldown before trying again |
| Transport timeout | Delivery may be uncertain; retries can duplicate a message accepted before the timeout |

For selection rules and delivery limits, see [reminder behavior](reminders.md). For the daily workflow and required GitHub Secrets, see [scheduled state persistence](state.md#daily-workflow).
