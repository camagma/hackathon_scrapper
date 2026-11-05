"""Persist chat subscriptions and the Telegram update cursor atomically."""

import sqlite3


def _require_transaction(connection: sqlite3.Connection) -> None:
    if not connection.in_transaction:
        raise RuntimeError("Subscription changes require an explicit transaction")


def set_subscription(
    connection: sqlite3.Connection, chat_id: int, hackathon_id: int, *, active: bool,
) -> None:
    """Change membership without resetting previously delivered reminder flags."""
    _require_transaction(connection)
    if type(chat_id) is not int or chat_id == 0:
        raise ValueError("Chat ID must be a nonzero integer")
    if type(hackathon_id) is not int or hackathon_id <= 0:
        raise ValueError("Hackathon ID must be a positive integer")
    if type(active) is not bool:
        raise ValueError("Active must be a boolean")
    connection.execute(
        """INSERT INTO subscriptions (chat_id, hackathon_id, active) VALUES (?, ?, ?)
        ON CONFLICT(chat_id, hackathon_id) DO UPDATE SET active = excluded.active""",
        (chat_id, hackathon_id, int(active)),
    )


def subscribed_ids(connection: sqlite3.Connection, chat_id: int) -> tuple[int, ...]:
    """Return active subscriptions in stable ID order for one chat."""
    return tuple(row[0] for row in connection.execute(
        "SELECT hackathon_id FROM subscriptions WHERE chat_id = ? AND active = 1 ORDER BY hackathon_id",
        (chat_id,),
    ))


def read_update_offset(connection: sqlite3.Connection) -> int:
    """Return the next update ID, or zero before the first processed update."""
    row = connection.execute("SELECT next_offset FROM telegram_updates WHERE singleton = 1").fetchone()
    return row[0] if row is not None else 0


def advance_update_offset(connection: sqlite3.Connection, next_offset: int) -> None:
    """Advance the cursor in the same transaction as the processed changes."""
    _require_transaction(connection)
    if type(next_offset) is not int or next_offset < 0:
        raise ValueError("Update offset must be a nonnegative integer")
    if next_offset < read_update_offset(connection):
        raise ValueError("Update offset cannot move backwards")
    connection.execute(
        """INSERT INTO telegram_updates (singleton, next_offset) VALUES (1, ?)
        ON CONFLICT(singleton) DO UPDATE SET next_offset = excluded.next_offset""",
        (next_offset,),
    )
