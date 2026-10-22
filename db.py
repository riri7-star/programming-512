"""SQLite persistence layer."""
import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS campuses (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    policy_key  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    username    TEXT NOT NULL UNIQUE COLLATE NOCASE,
    full_name   TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('lecturer','admin','operator')),
    campus_id   INTEGER REFERENCES campuses(id),
    salt        BLOB NOT NULL,
    pw_hash     BLOB NOT NULL,
    iterations  INTEGER NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS resources (
    id          INTEGER PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL,
    capacity    INTEGER NOT NULL CHECK (capacity > 0),
    campus_id   INTEGER NOT NULL REFERENCES campuses(id),
    active      INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS bookings (
    id           INTEGER PRIMARY KEY,
    resource_id  INTEGER NOT NULL REFERENCES resources(id),
    lecturer_id  INTEGER NOT NULL REFERENCES users(id),
    campus_id    INTEGER NOT NULL REFERENCES campuses(id),
    start_ts     TEXT NOT NULL,
    end_ts       TEXT NOT NULL,
    duration_min INTEGER NOT NULL CHECK (duration_min > 0),
    purpose      TEXT NOT NULL DEFAULT 'Teaching',
    status       TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','cancelled')),
    created_at   TEXT NOT NULL,
    CHECK (end_ts > start_ts)
);
CREATE INDEX IF NOT EXISTS idx_bookings_resource ON bookings(resource_id, start_ts, end_ts);
CREATE INDEX IF NOT EXISTS idx_bookings_lecturer ON bookings(lecturer_id);
"""


class Database:
    """Thin wrapper: one connection, explicit transactions, parameterised SQL only."""

    def __init__(self, path="smart_campus.db"):
        self._conn = sqlite3.connect(path, isolation_level=None)  # we control transactions
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)

    @contextmanager
    def transaction(self):
        """BEGIN IMMEDIATE takes the write lock first, so check-then-insert is atomic."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield self._conn
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")

    def query(self, sql, params=()):
        return self._conn.execute(sql, params).fetchall()

    def one(self, sql, params=()):
        return self._conn.execute(sql, params).fetchone()

    def execute(self, sql, params=()):
        with self.transaction() as conn:
            return conn.execute(sql, params).lastrowid

    def close(self):
        self._conn.close()
