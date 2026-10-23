from werkzeug.security import generate_password_hash

from database import get_db, init_db

DEPARTMENT = "Computer Engineering"
PASSWORD = "password123"  # demo password for every seeded user

ADVISORS = [
    ("advisor1@uni.edu", "Advisor 1"),
    ("advisor2@uni.edu", "Advisor 2"),
]

# (email, name, index of the assigned advisor in ADVISORS)
STUDENTS = [
    ("studenta@uni.edu", "Student A", 0),
    ("studentb@uni.edu", "Student B", 0),
    ("studentc@uni.edu", "Student C", 0),
    ("studentd@uni.edu", "Student D", 1),
    ("studente@uni.edu", "Student E", 1),
    ("studentf@uni.edu", "Student F", 1),
]


def add_user(conn, email, name, role):
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, full_name, role) VALUES (?, ?, ?, ?)",
        (email, generate_password_hash(PASSWORD), name, role),
    )
    return cur.lastrowid


def seed():
    init_db()
    conn = get_db()
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
        print("Database already has users, skipping seed.")
        conn.close()
        return

    advisor_ids = []
    for email, name in ADVISORS:
        uid = add_user(conn, email, name, "advisor")
        conn.execute("INSERT INTO advisors (user_id, department) VALUES (?, ?)", (uid, DEPARTMENT))
        advisor_ids.append(uid)

    for email, name, advisor_index in STUDENTS:
        uid = add_user(conn, email, name, "student")
        conn.execute(
            "INSERT INTO students (user_id, advisor_id) VALUES (?, ?)",
            (uid, advisor_ids[advisor_index]),
        )

    conn.commit()
    conn.close()
    print("Seeded 2 advisors and 6 students. Password for all: " + PASSWORD)


if __name__ == "__main__":
    seed()
