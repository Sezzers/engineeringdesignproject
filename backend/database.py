import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "advising.db"


def get_db():
    """Open a connection that returns rows as dict-like objects."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create the tables if they do not exist yet."""
    conn = get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('student', 'advisor'))
        );

        CREATE TABLE IF NOT EXISTS advisors (
            user_id INTEGER PRIMARY KEY REFERENCES users(id),
            department TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS students (
            user_id INTEGER PRIMARY KEY REFERENCES users(id),
            advisor_id INTEGER NOT NULL REFERENCES advisors(user_id)
        );
        """
    )
    conn.commit()
    conn.close()
