"""SQLite persistence for the linked PayPal wallet, spending cap, and orders.

Single demo user ("demo") for the hackathon MVP.
"""
import os
import sqlite3
import time
from contextlib import contextmanager

DB_PATH = os.getenv("SIXTHCENTS_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "sixthcents.db"))
DEMO_USER = "demo"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    vault_id TEXT,
    paypal_customer_id TEXT,
    payer_email TEXT,
    pending_setup_token TEXT,
    spending_cap REAL
);
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,               -- our id, also sent as PayPal-Request-Id
    user_id TEXT NOT NULL,
    confirmation_token TEXT UNIQUE,    -- single use: a token can only ever create one order
    paypal_order_id TEXT,
    capture_id TEXT,
    product_id TEXT,
    title TEXT,
    size TEXT,
    amount REAL,
    currency TEXT,
    status TEXT,                       -- CREATED | COMPLETED | CAPTURE_CONFIRMED | DENIED | FAILED
    webhook_confirmed INTEGER DEFAULT 0,
    created_at REAL,
    updated_at REAL
);
"""


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init():
    with db() as c:
        c.executescript(SCHEMA)
        c.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (DEMO_USER,))


def get_user(user_id=DEMO_USER):
    with db() as c:
        row = c.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def update_user(user_id=DEMO_USER, **fields):
    allowed = {"vault_id", "paypal_customer_id", "payer_email", "pending_setup_token", "spending_cap"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    with db() as c:
        c.execute(f"UPDATE users SET {cols} WHERE id = ?", (*fields.values(), user_id))


def create_order(order_id, user_id, confirmation_token, product_id, title, size, amount, currency):
    """Insert a new order. Raises sqlite3.IntegrityError if the token was already used."""
    now = time.time()
    with db() as c:
        c.execute(
            "INSERT INTO orders (id, user_id, confirmation_token, product_id, title, size, amount, currency, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'CREATED', ?, ?)",
            (order_id, user_id, confirmation_token, product_id, title, size, amount, currency, now, now),
        )


def update_order(order_id, **fields):
    allowed = {"paypal_order_id", "capture_id", "status", "webhook_confirmed"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    fields["updated_at"] = time.time()
    cols = ", ".join(f"{k} = ?" for k in fields)
    with db() as c:
        c.execute(f"UPDATE orders SET {cols} WHERE id = ?", (*fields.values(), order_id))


def get_order(order_id):
    with db() as c:
        row = c.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        return dict(row) if row else None


def find_order_by_paypal_id(paypal_order_id):
    with db() as c:
        row = c.execute("SELECT * FROM orders WHERE paypal_order_id = ?", (paypal_order_id,)).fetchone()
        return dict(row) if row else None


def find_order_by_capture_id(capture_id):
    with db() as c:
        row = c.execute("SELECT * FROM orders WHERE capture_id = ?", (capture_id,)).fetchone()
        return dict(row) if row else None
