"""SQLite layer: schema, safe per-request connections, and automatic migration of the old DB."""
import sqlite3
from datetime import datetime

from flask import g

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    is_admin BOOLEAN DEFAULT 0,
    created_at TEXT,
    last_login TEXT,
    business_name TEXT,
    gstin TEXT,
    phone TEXT,
    address TEXT
);
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    company TEXT,
    email TEXT,
    phone TEXT,
    address TEXT,
    gstin TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_no TEXT UNIQUE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
    buyer_name TEXT NOT NULL,
    buyer_email TEXT,
    buyer_address TEXT,
    status TEXT NOT NULL DEFAULT 'unpaid',
    subtotal REAL NOT NULL DEFAULT 0,
    discount_total REAL NOT NULL DEFAULT 0,
    gst_total REAL NOT NULL DEFAULT 0,
    total REAL NOT NULL DEFAULT 0,
    notes TEXT,
    due_date TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS invoice_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    category TEXT,
    qty REAL NOT NULL,
    rate REAL NOT NULL,
    discount_pct REAL NOT NULL DEFAULT 0,
    gst_rate REAL NOT NULL,
    line_discount REAL NOT NULL DEFAULT 0,
    line_gst REAL NOT NULL DEFAULT 0,
    line_total REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS otps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    purpose TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    expires_at REAL NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inv_user ON invoices(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_items_inv ON invoice_items(invoice_id);
CREATE INDEX IF NOT EXISTS idx_clients_user ON clients(user_id);
CREATE INDEX IF NOT EXISTS idx_otps_email ON otps(email, purpose);
"""


def connect(path=None):
    conn = sqlite3.connect(path or config.DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.DatabaseError:
        pass
    return conn


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def init_db(path=None):
    """Create tables and migrate an old (v1/v2) database in place. Safe to run on every start."""
    conn = connect(path)
    try:
        # --- migrate legacy invoices table (no invoice_no column) ---
        legacy_rows = []
        has_inv = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='invoices'").fetchone()
        if has_inv and "invoice_no" not in _columns(conn, "invoices"):
            legacy_rows = conn.execute("SELECT * FROM invoices").fetchall()
            conn.execute("ALTER TABLE invoices RENAME TO invoices_legacy")
            conn.execute("DROP INDEX IF EXISTS idx_inv_user")

        conn.executescript(SCHEMA)

        # --- add new user columns to an old users table ---
        existing = _columns(conn, "users")
        for col in ("created_at", "last_login", "business_name", "gstin", "phone", "address"):
            if col not in existing:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT")

        # --- import legacy invoices as single-item invoices ---
        for r in legacy_rows:
            email = (r["user_email"] or "").strip().lower()
            if not email:
                continue
            u = conn.execute("SELECT id FROM users WHERE lower(email)=?", (email,)).fetchone()
            if u:
                uid = u["id"]
            else:
                uid = conn.execute("INSERT INTO users(email, is_admin, created_at) VALUES (?,0,?)",
                                   (email, now())).lastrowid
            rate = float(r["rate"] or 0)
            gst_amt = float(r["gst_amount"] or 0)
            gst_pct = round(gst_amt / rate * 100, 2) if rate else 0
            created = r["date"] or now()
            inv_id = conn.execute(
                """INSERT INTO invoices(invoice_no,user_id,buyer_name,status,subtotal,discount_total,
                   gst_total,total,created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                (f"TMP-{r['id']}", uid, "Walk-in customer", "sent", rate, 0, gst_amt,
                 float(r["total_amount"] or 0), created)).lastrowid
            conn.execute(
                """INSERT INTO invoice_items(invoice_id,name,category,qty,rate,discount_pct,gst_rate,
                   line_discount,line_gst,line_total) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (inv_id, r["product_name"] or "Item", "Other", 1, rate, 0, gst_pct, 0, gst_amt,
                 float(r["total_amount"] or 0)))
            year = str(created)[:4]
            conn.execute("UPDATE invoices SET invoice_no=? WHERE id=?", (f"INV-{year}-{inv_id:05d}", inv_id))
        conn.commit()
    finally:
        conn.close()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
