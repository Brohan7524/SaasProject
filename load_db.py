"""
load_db.py  -  loads the generated CSVs into a SQLite database (data/workplace.db).

Why explicit CREATE TABLE statements instead of letting pandas guess?
  So the types, primary keys and foreign keys are exactly what we intend, and
  the SQL files in sql/ can rely on them.

SQLite has no real DATE type. Dates are stored as ISO text ('2025-03-01' or
'2025-03-01 09:30:00'). ISO text sorts correctly and works with date() / strftime().
"""
import sqlite3
from pathlib import Path

import pandas as pd

RAW_DIR = Path("data/raw")
DB_PATH = Path("data/workplace.db")

SCHEMA = """
CREATE TABLE clients (
    client_id     TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    industry      TEXT NOT NULL,
    region        TEXT NOT NULL,
    plan          TEXT NOT NULL,
    go_live_date  TEXT NOT NULL,
    seats         INTEGER NOT NULL
);

CREATE TABLE client_config (
    client_id                 TEXT NOT NULL REFERENCES clients(client_id),
    feature                   TEXT NOT NULL,
    enabled                   INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    enabled_date              TEXT,            -- NULL when the feature is not enabled
    offices_enabled           INTEGER NOT NULL,
    policy_max_days_per_week  INTEGER,         -- only set for Attendance Policy
    PRIMARY KEY (client_id, feature)
);

CREATE TABLE offices (
    office_id        TEXT PRIMARY KEY,
    client_id        TEXT NOT NULL REFERENCES clients(client_id),
    city             TEXT NOT NULL,
    desks            INTEGER NOT NULL,
    rooms            INTEGER NOT NULL,
    parking_spots    INTEGER NOT NULL,
    has_qr_scanners  INTEGER NOT NULL CHECK (has_qr_scanners IN (0, 1)),
    calendar_synced  INTEGER NOT NULL CHECK (calendar_synced IN (0, 1))
);

CREATE TABLE employees (
    employee_id  TEXT PRIMARY KEY,
    client_id    TEXT NOT NULL REFERENCES clients(client_id),
    office_id    TEXT NOT NULL REFERENCES offices(office_id),
    department   TEXT NOT NULL,
    join_date    TEXT NOT NULL
);

CREATE TABLE events (
    event_id     INTEGER PRIMARY KEY,
    employee_id  TEXT NOT NULL REFERENCES employees(employee_id),
    client_id    TEXT NOT NULL REFERENCES clients(client_id),
    feature      TEXT NOT NULL,
    action       TEXT NOT NULL CHECK (action IN ('view','book','check_in','cancel','no_show')),
    ts           TEXT NOT NULL
);

CREATE TABLE support_tickets (
    ticket_id    TEXT PRIMARY KEY,
    client_id    TEXT NOT NULL REFERENCES clients(client_id),
    feature      TEXT NOT NULL,
    category     TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    resolved_at  TEXT                          -- NULL = still open
);
"""

# Indexes are created AFTER loading: building them once at the end is much faster
# than updating them on every inserted row.
INDEXES = """
CREATE INDEX idx_events_client_feature_ts ON events (client_id, feature, ts);
CREATE INDEX idx_events_employee_feature_ts ON events (employee_id, feature, ts);
CREATE INDEX idx_employees_client ON employees (client_id);
CREATE INDEX idx_employees_office ON employees (office_id);
CREATE INDEX idx_offices_client ON offices (client_id);
CREATE INDEX idx_tickets_client_feature ON support_tickets (client_id, feature, created_at);
"""

# Load order matters only for readability; foreign keys are checked at the end.
TABLES = ["clients", "client_config", "offices", "employees", "events", "support_tickets"]


def read_csv(table):
    """Read a CSV; keep nullable integer columns as integers (not floats like 3.0)."""
    df = pd.read_csv(RAW_DIR / f"{table}.csv")
    if table == "client_config":
        df["policy_max_days_per_week"] = df["policy_max_days_per_week"].astype("Int64")
    return df


def load_table(conn, table):
    df = read_csv(table)
    # Write in chunks so the 1M-row events table does not use too much memory.
    df.to_sql(table, conn, if_exists="append", index=False, chunksize=100_000)
    return len(df)


def verify(conn, csv_counts):
    """Row counts in SQLite must equal the CSV row counts, and foreign keys must hold."""
    print(f"\n{'table':16s} {'csv rows':>10s} {'db rows':>10s}  status")
    all_ok = True
    for table in TABLES:
        db_rows = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        ok = db_rows == csv_counts[table]
        all_ok = all_ok and ok
        print(f"{table:16s} {csv_counts[table]:>10,} {db_rows:>10,}  {'OK' if ok else 'MISMATCH'}")

    broken = conn.execute("PRAGMA foreign_key_check").fetchall()
    print(f"\nForeign key violations: {len(broken)}")
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    print(f"SQLite integrity check: {integrity}")
    return all_ok and not broken and integrity == "ok"


def main():
    if DB_PATH.exists():
        DB_PATH.unlink()                 # start from a clean database every time

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)

    csv_counts = {}
    for table in TABLES:
        csv_counts[table] = load_table(conn, table)
        print(f"loaded {table}")

    conn.executescript(INDEXES)
    conn.execute("ANALYZE")              # gives the query planner statistics about the indexes
    conn.commit()

    ok = verify(conn, csv_counts)

    print("\nIndexes:")
    for name, tbl in conn.execute("SELECT name, tbl_name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"):
        print(f"  {name} on {tbl}")

    print("\nColumn types of events:")
    for _, col, typ, *_ in conn.execute("PRAGMA table_info(events)"):
        print(f"  {col:12s} {typ}")

    # Prove the main index is actually used for the typical query shape.
    plan = conn.execute("""EXPLAIN QUERY PLAN
        SELECT COUNT(*) FROM events
        WHERE client_id = 'C001' AND feature = 'Desk Booking' AND ts >= '2025-06-01'""").fetchall()
    print("\nQuery plan for a client+feature+ts filter:")
    for row in plan:
        print("  ", row[-1])

    conn.close()
    print(f"\nDatabase size: {DB_PATH.stat().st_size / 1e6:.1f} MB")
    print("RESULT:", "ALL CHECKS PASSED" if ok else "CHECKS FAILED")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
