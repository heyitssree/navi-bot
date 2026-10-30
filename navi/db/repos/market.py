# navi/db/repos/market.py - moved from schema.py (no behaviour change)
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

from navi.db.connection import _db_write

logger = logging.getLogger("navi.db.market")


_MARKET_SEED_ITEMS: list[dict] = [
    {
        "item_id": "monsoon_insurance",
        "name": "Monsoon Insurance",
        "emoji": "🌧️",
        "base_price": 80,
        "current_price": 80,
        "volatility": "high",
        "description": "Price rises when it rains in Trivandrum. Climate anxiety, monetized.",
    },
    {
        "item_id": "it_layoff_hedge",
        "name": "IT Layoff Hedge",
        "emoji": "📱",
        "base_price": 60,
        "current_price": 60,
        "volatility": "medium",
        "description": "Spikes every Friday. Technopark vibes only.",
    },
    {
        "item_id": "banana_republic",
        "name": "Banana Republic Stock",
        "emoji": "🍌",
        "base_price": 40,
        "current_price": 40,
        "volatility": "low",
        "description": "Slow decay with random noise. A classic.",
    },
    {
        "item_id": "cricket_mood_index",
        "name": "Cricket Mood Index",
        "emoji": "🏏",
        "base_price": 70,
        "current_price": 70,
        "volatility": "high",
        "description": "Extremely volatile during IPL season.",
    },
    {
        "item_id": "chaya_kada_futures",
        "name": "Chaya Kada Futures",
        "emoji": "☕",
        "base_price": 30,
        "current_price": 30,
        "volatility": "very_low",
        "description": "The safest investment in Kerala. Tiny but steady gains.",
    },
    {
        "item_id": "coconut_oil_commodity",
        "name": "Coconut Oil Commodity",
        "emoji": "🌴",
        "base_price": 50,
        "current_price": 50,
        "volatility": "low",
        "description": "Follows a slow sine wave. Buy low, sell after the rains.",
    },
]


def _seed_market_items(conn: sqlite3.Connection) -> None:
    """Insert default market items if the table is empty."""
    count = conn.execute("SELECT COUNT(*) FROM market_items").fetchone()[0]
    if count > 0:
        return
    for item in _MARKET_SEED_ITEMS:
        conn.execute(
            """
            INSERT OR IGNORE INTO market_items
                (item_id, name, emoji, base_price, current_price, volatility, description)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [item["item_id"], item["name"], item["emoji"],
             item["base_price"], item["current_price"],
             item["volatility"], item["description"]],
        )


def get_market_items(conn: sqlite3.Connection) -> list[dict]:
    """Return all market items with current prices."""
    rows = conn.execute(
        "SELECT item_id, name, emoji, base_price, current_price, volatility, description "
        "FROM market_items ORDER BY item_id"
    ).fetchall()
    return [
        {
            "item_id": r[0], "name": r[1], "emoji": r[2],
            "base_price": r[3], "current_price": r[4],
            "volatility": r[5], "description": r[6],
        }
        for r in rows
    ]


def get_market_item(conn: sqlite3.Connection, item_id: str) -> dict | None:
    """Return a single market item by item_id, or None."""
    row = conn.execute(
        "SELECT item_id, name, emoji, base_price, current_price, volatility, description "
        "FROM market_items WHERE item_id = ?",
        [item_id],
    ).fetchone()
    if not row:
        return None
    return {
        "item_id": row[0], "name": row[1], "emoji": row[2],
        "base_price": row[3], "current_price": row[4],
        "volatility": row[5], "description": row[6],
    }


def update_market_price(
    conn: sqlite3.Connection,
    item_id: str,
    new_price: int,
) -> None:
    """Set a market item's current price and update last_updated."""
    _db_write(lambda: (
        conn.execute(
            "UPDATE market_items SET current_price = ?, last_updated = CURRENT_TIMESTAMP WHERE item_id = ?",
            [new_price, item_id],
        ),
        conn.commit(),
    ))


def record_price_history(
    conn: sqlite3.Connection,
    item_id: str,
    price: int,
    date_str: str,
) -> None:
    """Persist a daily price point for history display."""
    def _write() -> None:
        conn.execute(
            "INSERT INTO market_prices (item_id, price, recorded_at) VALUES (?, ?, ?)",
            [item_id, price, date_str],
        )
        conn.commit()
    _db_write(_write)


def get_price_history(
    conn: sqlite3.Connection,
    item_id: str,
    days: int = 7,
) -> list[dict]:
    """Return the last N days of price history for an item."""
    rows = conn.execute(
        """
        SELECT CAST(recorded_at AS TEXT), price FROM market_prices
        WHERE item_id = ?
        ORDER BY recorded_at DESC LIMIT ?
        """,
        [item_id, days],
    ).fetchall()
    return [{"date": r[0], "price": r[1]} for r in reversed(rows)]


def buy_holding(
    conn: sqlite3.Connection,
    user_id: int,
    item_id: str,
    quantity: int,
    purchase_price: int,
    expires_at: datetime,
) -> None:
    """Add a new holding row for a user purchase."""
    # Store as UTC without timezone offset so SQLite CURRENT_TIMESTAMP comparisons work correctly
    expires_str = expires_at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    def _write() -> None:
        conn.execute(
            """
            INSERT INTO holdings (user_id, item_id, quantity, purchase_price, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [user_id, item_id, quantity, purchase_price, expires_str],
        )
        conn.commit()
    _db_write(_write)


def get_user_holdings(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    """Return all non-expired holdings for a user, joined with market item info."""
    rows = conn.execute(
        """
        SELECT h.id, h.item_id, m.name, m.emoji, m.current_price,
               h.quantity, h.purchase_price, h.purchased_at, h.expires_at
        FROM holdings h
        JOIN market_items m ON m.item_id = h.item_id
        WHERE h.user_id = ? AND h.expires_at > CURRENT_TIMESTAMP
        ORDER BY h.purchased_at
        """,
        [user_id],
    ).fetchall()
    return [
        {
            "id": r[0], "item_id": r[1], "name": r[2], "emoji": r[3],
            "current_price": r[4], "quantity": r[5], "purchase_price": r[6],
            "purchased_at": r[7], "expires_at": r[8],
        }
        for r in rows
    ]


def get_user_holding_for_item(
    conn: sqlite3.Connection,
    user_id: int,
    item_id: str,
) -> list[dict]:
    """Return non-expired holdings for a user for a specific item (FIFO order)."""
    rows = conn.execute(
        """
        SELECT id, quantity, purchase_price, purchased_at, expires_at
        FROM holdings
        WHERE user_id = ? AND item_id = ? AND expires_at > CURRENT_TIMESTAMP
        ORDER BY purchased_at ASC
        """,
        [user_id, item_id],
    ).fetchall()
    return [
        {
            "id": r[0], "quantity": r[1], "purchase_price": r[2],
            "purchased_at": r[3], "expires_at": r[4],
        }
        for r in rows
    ]


def reduce_holding(
    conn: sqlite3.Connection,
    holding_id: int,
    qty_to_remove: int,
) -> None:
    """Reduce quantity of a holding row, deleting it if it reaches 0."""
    def _write() -> None:
        conn.execute(
            "UPDATE holdings SET quantity = quantity - ? WHERE id = ?",
            [qty_to_remove, holding_id],
        )
        conn.execute("DELETE FROM holdings WHERE id = ? AND quantity <= 0", [holding_id])
        conn.commit()
    _db_write(_write)


def expire_stale_holdings(
    conn: sqlite3.Connection,
) -> list[dict]:
    """Delete all expired holding rows and return them (for notification purposes)."""
    rows = conn.execute(
        """
        SELECT h.user_id, m.name, m.emoji, h.quantity, h.purchase_price
        FROM holdings h
        JOIN market_items m ON m.item_id = h.item_id
        WHERE h.expires_at <= CURRENT_TIMESTAMP
        """
    ).fetchall()
    expired = [
        {"user_id": r[0], "name": r[1], "emoji": r[2], "quantity": r[3], "purchase_price": r[4]}
        for r in rows
    ]
    if expired:
        _db_write(lambda: (
            conn.execute("DELETE FROM holdings WHERE expires_at <= CURRENT_TIMESTAMP"),
            conn.commit(),
        ))
    return expired
