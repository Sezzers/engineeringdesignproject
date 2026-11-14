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

        -- Weekly availability rule, e.g. every Tuesday 13:00-15:00 between two dates.
        -- weekday: 0 = Monday ... 6 = Sunday. Times are "HH:MM".
        CREATE TABLE IF NOT EXISTS availability (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            advisor_id INTEGER NOT NULL REFERENCES advisors(user_id),
            weekday INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            valid_from TEXT NOT NULL,
            valid_to TEXT NOT NULL,
            meeting_mode TEXT NOT NULL DEFAULT 'In person',
            location TEXT NOT NULL DEFAULT ''
        );

        -- A single date the advisor closed (e.g. a meeting on that day).
        CREATE TABLE IF NOT EXISTS blocked_dates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            advisor_id INTEGER NOT NULL REFERENCES advisors(user_id),
            blocked_date TEXT NOT NULL,
            UNIQUE (advisor_id, blocked_date)
        );

        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES students(user_id),
            advisor_id INTEGER NOT NULL REFERENCES advisors(user_id),
            appt_date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            topic TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'approved', 'rejected')),
            decision_reason TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            appointment_id INTEGER NOT NULL REFERENCES appointments(id),
            uploader_id INTEGER NOT NULL REFERENCES users(id),
            original_name TEXT NOT NULL,
            stored_name TEXT NOT NULL UNIQUE,
            size_bytes INTEGER NOT NULL,
            mime_type TEXT NOT NULL,
            uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.commit()
    conn.close()
