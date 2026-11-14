"""Availability, appointment requests, approval/conflict handling and file sharing."""
import re
import uuid
from datetime import date, datetime
from functools import wraps
from pathlib import Path

from flask import Blueprint, jsonify, request, send_from_directory, session

from database import get_db

bp = Blueprint("scheduling", __name__)

SLOT_MINUTES = 30
TOPICS = ["Course selection", "Internship", "Graduation", "Career advice", "Other"]
MEETING_MODES = ["In person", "Online"]
MAX_FILE_BYTES = 5 * 1024 * 1024
UPLOAD_DIR = Path(__file__).parent / "uploads"
REJECT_REASON_CONFLICT = "This time slot was reserved for another appointment."

TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


# ---------- helpers ----------

def error(message, status=400):
    return jsonify(error=message), status


def api_login_required(role=None):
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return error("Please log in first.", 401)
            if role and session.get("role") != role:
                return error("You are not allowed to do this.", 403)
            return view(*args, **kwargs)
        return wrapper
    return decorator


def to_minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def to_hhmm(minutes):
    return "%02d:%02d" % (minutes // 60, minutes % 60)


def parse_date(value):
    try:
        return datetime.strptime(value or "", "%Y-%m-%d").date()
    except ValueError:
        return None


def overlaps(start_a, end_a, start_b, end_b):
    """Two intervals overlap only if each starts before the other ends.
    13:00-13:30 and 13:30-14:00 do NOT overlap."""
    return start_a < end_b and end_a > start_b


def advisor_of_student(conn, student_id):
    row = conn.execute("SELECT advisor_id FROM students WHERE user_id = ?", (student_id,)).fetchone()
    return row["advisor_id"] if row else None


def approved_overlap_exists(conn, advisor_id, day, start, end, exclude_id=None):
    rows = conn.execute(
        "SELECT id, start_time, end_time FROM appointments "
        "WHERE advisor_id = ? AND appt_date = ? AND status = 'approved'",
        (advisor_id, day),
    ).fetchall()
    s, e = to_minutes(start), to_minutes(end)
    return any(
        r["id"] != exclude_id and overlaps(s, e, to_minutes(r["start_time"]), to_minutes(r["end_time"]))
        for r in rows
    )


def build_slots(conn, advisor_id, day):
    """All 30-minute slots of an advisor on a date, with an `available` flag."""
    iso = day.isoformat()
    if conn.execute(
        "SELECT 1 FROM blocked_dates WHERE advisor_id = ? AND blocked_date = ?", (advisor_id, iso)
    ).fetchone():
        return []

    rules = conn.execute(
        "SELECT * FROM availability WHERE advisor_id = ? AND weekday = ? "
        "AND valid_from <= ? AND valid_to >= ?",
        (advisor_id, day.weekday(), iso, iso),
    ).fetchall()

    now = datetime.now()
    slots = {}
    for rule in rules:
        t, end = to_minutes(rule["start_time"]), to_minutes(rule["end_time"])
        while t + SLOT_MINUTES <= end:
            start_s, end_s = to_hhmm(t), to_hhmm(t + SLOT_MINUTES)
            started = datetime.combine(day, datetime.min.time()).replace(hour=t // 60, minute=t % 60) <= now
            taken = approved_overlap_exists(conn, advisor_id, iso, start_s, end_s)
            slots[start_s] = {
                "start_time": start_s,
                "end_time": end_s,
                "meeting_mode": rule["meeting_mode"],
                "location": rule["location"],
                "available": not started and not taken,
                "reason": "Past" if started else ("Booked" if taken else ""),
            }
            t += SLOT_MINUTES
    return [slots[k] for k in sorted(slots)]


def appointment_dict(row):
    return {k: row[k] for k in row.keys()}


def can_access_appointment(conn, appt_id):
    """Return the appointment row if the logged-in user is its student or advisor."""
    appt = conn.execute(
        "SELECT a.*, s.full_name AS student_name, v.full_name AS advisor_name "
        "FROM appointments a JOIN users s ON s.id = a.student_id JOIN users v ON v.id = a.advisor_id "
        "WHERE a.id = ?",
        (appt_id,),
    ).fetchone()
    if appt is None:
        return None
    uid = session["user_id"]
    if uid not in (appt["student_id"], appt["advisor_id"]):
        return None
    return appt


# ---------- advisor: weekly availability rules ----------

@bp.route("/api/availability-rules", methods=["GET"])
@api_login_required("advisor")
def list_rules():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM availability WHERE advisor_id = ? ORDER BY weekday, start_time",
        (session["user_id"],),
    ).fetchall()
    conn.close()
    return jsonify([appointment_dict(r) for r in rows])


@bp.route("/api/availability-rules", methods=["POST"])
@api_login_required("advisor")
def add_rule():
    d = request.get_json(silent=True) or {}
    try:
        weekday = int(d.get("weekday"))
    except (TypeError, ValueError):
        return error("Please choose a day of the week.")
    start, end = d.get("start_time") or "", d.get("end_time") or ""
    valid_from, valid_to = parse_date(d.get("valid_from")), parse_date(d.get("valid_to"))
    mode = d.get("meeting_mode") or "In person"
    location = (d.get("location") or "").strip()

    if not 0 <= weekday <= 6:
        return error("Please choose a day of the week.")
    if not TIME_RE.match(start) or not TIME_RE.match(end):
        return error("Start and end time must look like 13:00.")
    if to_minutes(end) - to_minutes(start) < SLOT_MINUTES:
        return error("The end time must be at least %d minutes after the start time." % SLOT_MINUTES)
    if valid_from is None or valid_to is None:
        return error("Please enter valid start and end dates.")
    if valid_to < valid_from:
        return error("The end date cannot be before the start date.")
    if mode not in MEETING_MODES:
        return error("Meeting type must be one of: " + ", ".join(MEETING_MODES) + ".")

    conn = get_db()
    # Do not allow two rules that overlap on the same weekday and date range.
    existing = conn.execute(
        "SELECT * FROM availability WHERE advisor_id = ? AND weekday = ?", (session["user_id"], weekday)
    ).fetchall()
    for r in existing:
        dates_overlap = r["valid_from"] <= valid_to.isoformat() and r["valid_to"] >= valid_from.isoformat()
        if dates_overlap and overlaps(
            to_minutes(start), to_minutes(end), to_minutes(r["start_time"]), to_minutes(r["end_time"])
        ):
            conn.close()
            return error("This overlaps with an availability you already added for that day.", 409)

    cur = conn.execute(
        "INSERT INTO availability (advisor_id, weekday, start_time, end_time, valid_from, valid_to, "
        "meeting_mode, location) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (session["user_id"], weekday, start, end, valid_from.isoformat(), valid_to.isoformat(), mode, location),
    )
    conn.commit()
    conn.close()
    return jsonify(id=cur.lastrowid), 201


@bp.route("/api/availability-rules/<int:rule_id>", methods=["DELETE"])
@api_login_required("advisor")
def delete_rule(rule_id):
    conn = get_db()
    cur = conn.execute(
        "DELETE FROM availability WHERE id = ? AND advisor_id = ?", (rule_id, session["user_id"])
    )
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        return error("Availability not found.", 404)
    return jsonify(ok=True)


# ---------- advisor: closed dates ----------

@bp.route("/api/blocked-dates", methods=["GET"])
@api_login_required("advisor")
def list_blocked():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, blocked_date FROM blocked_dates WHERE advisor_id = ? ORDER BY blocked_date",
        (session["user_id"],),
    ).fetchall()
    conn.close()
    return jsonify([appointment_dict(r) for r in rows])


@bp.route("/api/blocked-dates", methods=["POST"])
@api_login_required("advisor")
def add_blocked():
    day = parse_date((request.get_json(silent=True) or {}).get("date"))
    if day is None:
        return error("Please choose a valid date.")
    if day < date.today():
        return error("You cannot close a date in the past.")
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO blocked_dates (advisor_id, blocked_date) VALUES (?, ?)",
            (session["user_id"], day.isoformat()),
        )
        conn.commit()
    except Exception:
        conn.close()
        return error("This date is already closed.", 409)
    conn.close()
    return jsonify(ok=True), 201


@bp.route("/api/blocked-dates/<int:blocked_id>", methods=["DELETE"])
@api_login_required("advisor")
def delete_blocked(blocked_id):
    conn = get_db()
    cur = conn.execute(
        "DELETE FROM blocked_dates WHERE id = ? AND advisor_id = ?", (blocked_id, session["user_id"])
    )
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        return error("Closed date not found.", 404)
    return jsonify(ok=True)


# ---------- student: slots and requests ----------

@bp.route("/api/topics")
@api_login_required()
def topics():
    return jsonify(TOPICS)


@bp.route("/api/availability")
@api_login_required("student")
def student_slots():
    day = parse_date(request.args.get("date"))
    if day is None:
        return error("Please choose a valid date.")
    conn = get_db()
    advisor_id = advisor_of_student(conn, session["user_id"])
    if advisor_id is None:
        conn.close()
        return error("No advisor is assigned to you.", 404)
    slots = build_slots(conn, advisor_id, day)
    conn.close()
    return jsonify(slots)


@bp.route("/api/appointments", methods=["POST"])
@api_login_required("student")
def create_appointment():
    d = request.get_json(silent=True) or {}
    day = parse_date(d.get("date"))
    start = d.get("start_time") or ""
    topic = (d.get("topic") or "").strip()
    description = (d.get("description") or "").strip()

    if not topic:
        return error("Please choose a meeting topic.")
    if topic not in TOPICS:
        return error("This topic is not valid.")
    if len(description) > 500:
        return error("The description can be at most 500 characters.")
    if day is None or not TIME_RE.match(start):
        return error("Please choose a date and a time.")
    if day < date.today():
        return error("You cannot request an appointment in the past.")

    conn = get_db()
    # The advisor always comes from the stored assignment, never from the request.
    advisor_id = advisor_of_student(conn, session["user_id"])
    if advisor_id is None:
        conn.close()
        return error("No advisor is assigned to you.", 404)

    slot = next((s for s in build_slots(conn, advisor_id, day) if s["start_time"] == start), None)
    if slot is None:
        conn.close()
        return error("Your advisor is not available at this time.", 409)
    if not slot["available"]:
        conn.close()
        msg = "This time has already passed." if slot["reason"] == "Past" else "This time is already booked."
        return error(msg, 409)

    # A student cannot hold two active requests at overlapping times.
    s, e = to_minutes(slot["start_time"]), to_minutes(slot["end_time"])
    mine = conn.execute(
        "SELECT start_time, end_time FROM appointments WHERE student_id = ? AND appt_date = ? "
        "AND status IN ('pending', 'approved')",
        (session["user_id"], day.isoformat()),
    ).fetchall()
    if any(overlaps(s, e, to_minutes(r["start_time"]), to_minutes(r["end_time"])) for r in mine):
        conn.close()
        return error("You already have a request at this time.", 409)

    cur = conn.execute(
        "INSERT INTO appointments (student_id, advisor_id, appt_date, start_time, end_time, topic, description) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (session["user_id"], advisor_id, day.isoformat(), slot["start_time"], slot["end_time"], topic, description),
    )
    conn.commit()
    conn.close()
    return jsonify(id=cur.lastrowid, status="pending"), 201


@bp.route("/api/my-appointments")
@api_login_required()
def my_appointments():
    conn = get_db()
    column = "student_id" if session["role"] == "student" else "advisor_id"
    rows = conn.execute(
        "SELECT a.*, s.full_name AS student_name, v.full_name AS advisor_name, "
        "(SELECT COUNT(*) FROM files f WHERE f.appointment_id = a.id) AS file_count "
        "FROM appointments a JOIN users s ON s.id = a.student_id JOIN users v ON v.id = a.advisor_id "
        "WHERE a.%s = ? ORDER BY a.appt_date, a.start_time" % column,
        (session["user_id"],),
    ).fetchall()
    conn.close()
    return jsonify([appointment_dict(r) for r in rows])


@bp.route("/api/appointments/<int:appt_id>")
@api_login_required()
def appointment_detail(appt_id):
    conn = get_db()
    appt = can_access_appointment(conn, appt_id)
    conn.close()
    if appt is None:
        return error("Appointment not found.", 404)
    return jsonify(appointment_dict(appt))


# ---------- advisor: approve / reject ----------

@bp.route("/api/appointments/<int:appt_id>", methods=["PATCH"])
@api_login_required("advisor")
def decide_appointment(appt_id):
    d = request.get_json(silent=True) or {}
    status = d.get("status")
    reason = (d.get("reason") or "").strip()
    if status not in ("approved", "rejected"):
        return error("Status must be 'approved' or 'rejected'.")

    conn = get_db()
    conn.isolation_level = None  # manual transaction control
    try:
        # IMMEDIATE takes the write lock now, so two simultaneous approvals
        # are processed one after the other and the check below stays valid.
        conn.execute("BEGIN IMMEDIATE")
        appt = conn.execute(
            "SELECT * FROM appointments WHERE id = ? AND advisor_id = ?", (appt_id, session["user_id"])
        ).fetchone()
        if appt is None:
            conn.execute("ROLLBACK")
            return error("Appointment not found.", 404)
        if appt["status"] != "pending":
            conn.execute("ROLLBACK")
            return error("This request has already been answered.", 409)

        if status == "rejected":
            conn.execute(
                "UPDATE appointments SET status = 'rejected', decision_reason = ? WHERE id = ?",
                (reason or "Rejected by the advisor.", appt_id),
            )
            conn.execute("COMMIT")
            return jsonify(id=appt_id, status="rejected")

        if approved_overlap_exists(
            conn, session["user_id"], appt["appt_date"], appt["start_time"], appt["end_time"], exclude_id=appt_id
        ):
            conn.execute("ROLLBACK")
            return error("Another appointment is already approved for this time.", 409)

        conn.execute("UPDATE appointments SET status = 'approved' WHERE id = ?", (appt_id,))
        s, e = to_minutes(appt["start_time"]), to_minutes(appt["end_time"])
        others = conn.execute(
            "SELECT id, start_time, end_time FROM appointments WHERE advisor_id = ? AND appt_date = ? "
            "AND status = 'pending' AND id != ?",
            (session["user_id"], appt["appt_date"], appt_id),
        ).fetchall()
        rejected = []
        for o in others:
            if overlaps(s, e, to_minutes(o["start_time"]), to_minutes(o["end_time"])):
                conn.execute(
                    "UPDATE appointments SET status = 'rejected', decision_reason = ? WHERE id = ?",
                    (REJECT_REASON_CONFLICT, o["id"]),
                )
                rejected.append(o["id"])
        conn.execute("COMMIT")
        return jsonify(id=appt_id, status="approved", auto_rejected=rejected)
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        return error("Something went wrong. Please try again.", 500)
    finally:
        conn.close()


# ---------- files (PDF, tied to one appointment) ----------

@bp.route("/api/appointments/<int:appt_id>/files")
@api_login_required()
def list_files(appt_id):
    conn = get_db()
    if can_access_appointment(conn, appt_id) is None:
        conn.close()
        return error("Appointment not found.", 404)
    rows = conn.execute(
        "SELECT f.id, f.original_name, f.size_bytes, f.uploaded_at, u.full_name AS uploader_name "
        "FROM files f JOIN users u ON u.id = f.uploader_id WHERE f.appointment_id = ? ORDER BY f.id",
        (appt_id,),
    ).fetchall()
    conn.close()
    return jsonify([appointment_dict(r) for r in rows])


@bp.route("/api/appointments/<int:appt_id>/files", methods=["POST"])
@api_login_required()
def upload_file(appt_id):
    conn = get_db()
    if can_access_appointment(conn, appt_id) is None:
        conn.close()
        return error("Appointment not found.", 404)

    f = request.files.get("file")
    if f is None or not f.filename:
        conn.close()
        return error("Please choose a file.")
    if not f.filename.lower().endswith(".pdf"):
        conn.close()
        return error("Only PDF files are accepted.")

    data = f.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        conn.close()
        return error("The file is too large. The limit is 5 MB.", 413)
    if len(data) == 0:
        conn.close()
        return error("The file is empty.")
    if not data.startswith(b"%PDF-"):  # check the real content, not just the name
        conn.close()
        return error("This file is not a valid PDF.")

    UPLOAD_DIR.mkdir(exist_ok=True)
    stored = uuid.uuid4().hex + ".pdf"
    (UPLOAD_DIR / stored).write_bytes(data)
    original = Path(f.filename).name[:200]
    cur = conn.execute(
        "INSERT INTO files (appointment_id, uploader_id, original_name, stored_name, size_bytes, mime_type) "
        "VALUES (?, ?, ?, ?, ?, 'application/pdf')",
        (appt_id, session["user_id"], original, stored, len(data)),
    )
    conn.commit()
    conn.close()
    return jsonify(id=cur.lastrowid), 201


@bp.route("/api/files/<int:file_id>/download")
@api_login_required()
def download_file(file_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    allowed = row is not None and can_access_appointment(conn, row["appointment_id"]) is not None
    conn.close()
    if not allowed:
        return error("File not found.", 404)
    return send_from_directory(
        UPLOAD_DIR, row["stored_name"], as_attachment=True, download_name=row["original_name"]
    )
