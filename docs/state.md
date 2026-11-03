# Persist runner state in Git

`scripts/state_db.py` restores and saves the reminder database through a dedicated `bot-state` branch on the repository's `origin` remote. The daily workflow will use this helper; the workflow itself is not added yet.

GitHub-hosted runners do not retain the previous job's local SQLite file. This project uses a separate state branch instead of a dependency cache because [Actions caches can be evicted and existing cache contents cannot be changed](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching). Losing reminder flags can cause reminders to be sent again.

## State format

The branch contains one file, `hackathons.sqlite3`, with no application code or Telegram credentials. The helper uses Git objects to create commits without switching the working branch or changing the staging area. The application database stays ignored on the code branch.

Each restore records its source commit in an ignored `*.state-revision` file beside the database. Saving uses that exact revision as its parent and performs a normal push without force. If another writer has advanced the branch, the push is rejected instead of overwriting newer reminder flags. The future workflow must also serialize runs before sending messages.

## Runner usage

Use a disposable checkout with Git, Python 3.11+, an `origin` remote, and permission to push to `bot-state`. The helper itself uses only the standard library. It does not modify the main branch or require a separate local checkout of the state branch.

Restore before running the application:

```sh
python scripts/state_db.py restore --database data/hackathons.sqlite3
```

Restore requires a fresh destination without an existing database, journal, or revision marker. It will not overwrite a local working database. Only a genuinely missing `bot-state` branch initializes a first run; network errors, missing files on an existing branch, and corrupt SQLite data stop restoration.

Run the application against that same database. Once the application has finished, save it:

```sh
python scripts/state_db.py save --database data/hackathons.sqlite3
```

The first successful save creates the state branch. Later saves create a child commit only when the snapshot changed. SQLite's backup API produces a consistent standalone file, including committed WAL data. Integrity and reminder-column checks reject corrupt or unrelated databases. Saving requires the restore marker; it cannot silently publish an arbitrary fresh database over existing remote state.

The helper defaults to the current repository and `data/hackathons.sqlite3`; `--repo` and `--database` override those paths. It does not read `config.toml`, so the workflow must pass the same database path to both the helper and the application.

## Failures and recovery

Preserve state after a partially successful application run too: some reminders may already have committed their flags even when the application exits nonzero. The workflow will save state after such runs, provided restoration succeeded and a database exists.

A failed push is an error, not a reason to force-push or initialize an empty database. Inspect and reconcile the newest state before another delivery attempt. An interrupted runner or failed save after external message delivery can still cause duplicates; Git persistence does not remove the [external-delivery limits](reminders.md#delivery-limits).

Tests exercise creation, restoration, unchanged snapshots, stale writers, corrupt state, unavailable remotes, and WAL backups using temporary local Git repositories. They do not contact GitHub or Telegram.
