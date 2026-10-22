import sqlite3
from datetime import date

import pytest

FROZEN_TODAY = date(2026, 10, 15)


@pytest.fixture
def today() -> date:
    """Frozen 'today' so overdue checks are reproducible."""
    return FROZEN_TODAY


@pytest.fixture
def db_path(tmp_path):
    """Path to a throwaway SQLite file, removed with tmp_path."""
    return tmp_path / "actiontrack.db"


@pytest.fixture
def db(db_path):
    """Open connection to a temporary database. Schema comes with store.py later."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.close()
