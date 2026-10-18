from contextlib import contextmanager
from pathlib import Path
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE, name TEXT NOT NULL,
 password TEXT, role TEXT NOT NULL CHECK(role IN ('admin','user')),
 enabled INTEGER NOT NULL DEFAULT 1, quota INTEGER NOT NULL CHECK(quota>=0),
 totp TEXT, totp_confirmed INTEGER NOT NULL DEFAULT 0, totp_step INTEGER NOT NULL DEFAULT -1,
 created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS public_accounts (
 user_id TEXT PRIMARY KEY REFERENCES users(id), created_at INTEGER NOT NULL,
 established_at INTEGER, cleanup_protected INTEGER NOT NULL DEFAULT 0 CHECK(cleanup_protected IN (0,1)));
CREATE TABLE IF NOT EXISTS sessions (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 stage TEXT NOT NULL, csrf TEXT NOT NULL, expires INTEGER NOT NULL, auth_at INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS recovery (
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, digest TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS invites (
 digest TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS password_resets (
 digest TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS editor_tickets (
 id TEXT PRIMARY KEY, handle TEXT NOT NULL UNIQUE, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
 app_id TEXT NOT NULL, nonce TEXT NOT NULL, expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS rate_limits (key TEXT PRIMARY KEY, count INTEGER NOT NULL, reset INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
 id INTEGER PRIMARY KEY, actor TEXT, action TEXT NOT NULL, target TEXT, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS entries (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), parent TEXT REFERENCES entries(id),
 name TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('file','folder')),
 trash TEXT, created INTEGER NOT NULL, updated INTEGER NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS entries_name ON entries(owner,COALESCE(parent,''),name) WHERE trash IS NULL;
CREATE INDEX IF NOT EXISTS entries_owner ON entries(owner,parent,trash);
CREATE TABLE IF NOT EXISTS versions (
 id TEXT PRIMARY KEY, entry_id TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
 owner TEXT NOT NULL REFERENCES users(id), size INTEGER NOT NULL CHECK(size>=0),
 sha256 TEXT NOT NULL, created INTEGER NOT NULL, sequence INTEGER NOT NULL,
 UNIQUE(entry_id,sequence));
CREATE INDEX IF NOT EXISTS versions_owner ON versions(owner);
CREATE TABLE IF NOT EXISTS reservations (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), size INTEGER NOT NULL, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS shares (
 entry_id TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
 recipient TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, created INTEGER NOT NULL,
 PRIMARY KEY(entry_id,recipient));
PRAGMA user_version=2;
"""


class DB:
    def __init__(self, path: Path):
        self.path = path
        with self.connect() as c:
            if c.execute("PRAGMA user_version").fetchone()[0]>2:
                raise RuntimeError("Banco de uma versão mais recente. Não é seguro fazer downgrade.")
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=30000")
        try:
            yield c
        finally:
            c.close()

    @contextmanager
    def transaction(self):
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
                c.commit()
            except BaseException:
                c.rollback()
                raise
