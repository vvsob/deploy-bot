# Telegram deployment bot

Python 3.11+ bot that runs a configured script when an allowed operator sends
`/deploy`, privately or in a group. Authorization uses numeric Telegram **user
IDs**, not usernames or chat IDs. Other users and anonymous/channel senders are
denied. Command arguments are rejected.

## Setup

Run these commands from this directory:

```sh
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell instead:
# .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Copy `config.example.json` to `config.json`. Set your token from Telegram's
@BotFather, your operators' numeric user IDs, and the script to run. You can find
a user's ID in the `from.id` field of a Telegram Bot API message update.
Keep the token private; `config.json` is excluded from Git in this folder.

Create your deployment script at the configured path. The sample config expects
`deploy.sh`; no deployment actions are supplied automatically.

```sh
python bot.py --config config.json
```

Send `/deploy` to the bot. It replies when execution starts and when it finishes,
including the exit code on failure. Script stdout/stderr go to the bot process's
console/server logs, not Telegram. No public web server is needed: the bot uses
long polling and requires outbound access to Telegram.

## Configuration

- `bot_token`: Telegram bot token.
- `operator_ids`: nonempty list of positive numeric Telegram user IDs.
- `script`: script file path, absolute or relative to the config file.
- `shell`: executable and optional fixed flags as a JSON array. Defaults to
  `["/bin/bash"]`. For PowerShell scripts use
  `["powershell.exe", "-NoProfile", "-NonInteractive", "-File"]` and a `.ps1`
  script. Bash scripts on Windows require an installed Bash interpreter.
- `working_directory`: directory relative to the config file (or absolute).
  If omitted, the script's directory is used.

Restart the bot after editing the config. Run one bot instance per token; the
deployment lock prevents overlap within that process. Messages queued while the
bot was offline are discarded on startup to avoid stale deployments.

The script runs with the bot's OS account, permissions, and environment. Keep the
config and script writable only by trusted administrators. The script should run
noninteractively, exit after deployment, and return a nonzero exit code on failure.
There is no execution timeout. Let a deployment finish before stopping the bot;
scripts are responsible for any background processes they launch.

## Tests

From this directory (no Telegram token or network needed):

```sh
python -m unittest discover -v
```

Tests execute harmless local Python scripts to verify authorization, actual
execution, working-directory handling, overlap protection, and failure recovery.
