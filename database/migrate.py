"""轻量 schema 迁移执行器：python database/migrate.py

按 database/migrations/ 下的编号顺序执行未应用的迁移，
已应用的记录在 schema_version 表里。
"""
import glob
import importlib.util
import os
import sqlite3
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DB_PATH = os.path.join(PROJECT_ROOT, "database", "players.db")
MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")


def _current_version(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version "
        "(version INTEGER PRIMARY KEY, applied_at TEXT)"
    )
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return row[0] or 0


def run_migrations():
    conn = sqlite3.connect(DB_PATH)

    try:
        current = _current_version(conn)
        files = sorted(glob.glob(os.path.join(MIGRATIONS_DIR, "*.py")))

        for path in files:
            version = int(os.path.basename(path).split("_")[0])

            if version <= current:
                continue

            name = os.path.basename(path)
            print(f"Applying migration {name}...")

            spec = importlib.util.spec_from_file_location(
                f"migration_{version}",
                path,
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.upgrade(conn)

            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (version, time.strftime("%Y-%m-%d %H:%M:%S")),
            )
            conn.commit()
            print(f"  -> applied {name}")

        print(f"Schema version: {_current_version(conn)}")
    finally:
        conn.close()


if __name__ == "__main__":
    run_migrations()