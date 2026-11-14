"""End-to-end check of the main flow and the error cases.
Run from the backend folder:  python test_flow.py
Uses a temporary database, so your real advising.db is untouched."""
import io
import tempfile
from datetime import date, timedelta
from pathlib import Path

import database

tmp = tempfile.mkdtemp()
database.DB_PATH = Path(tmp) / "test.db"

import scheduling  # noqa: E402
scheduling.UPLOAD_DIR = Path(tmp) / "uploads"

import seed  # noqa: E402
from app import app  # noqa: E402

seed.seed()
app.config["TESTING"] = True

results = []


def check(name, condition):
    results.append(condition)
    print(("PASS  " if condition else "FAIL  ") + name)


def login(email):
    c = app.test_client()
    r = c.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert r.status_code == 200, r.get_json()
    return c


def next_weekday(target, weeks_ahead=1):
    d = date.today() + timedelta(days=1)
    while d.weekday() != target:
        d += timedelta(days=1)
    return d + timedelta(weeks=weeks_ahead - 1)


tuesday = next_weekday(1)
adv1 = login("advisor1@uni.edu")
stuA = login("studenta@uni.edu")
stuB = login("studentb@uni.edu")
stuC = login("studentc@uni.edu")
stuD = login("studentd@uni.edu")

# --- availability ---
rule = {"weekday": 1, "start_time": "13:00", "end_time": "15:00", "valid_from": date.today().isoformat(),
        "valid_to": (date.today() + timedelta(days=90)).isoformat(), "meeting_mode": "In person", "location": "Room 201"}
check("advisor adds availability", adv1.post("/api/availability-rules", json=rule).status_code == 201)
check("overlapping availability rejected", adv1.post("/api/availability-rules", json={**rule, "start_time": "14:00", "end_time": "16:00"}).status_code == 409)
check("end before start rejected", adv1.post("/api/availability-rules", json={**rule, "weekday": 2, "start_time": "15:00", "end_time": "13:00"}).status_code == 400)
check("student cannot add availability", stuA.post("/api/availability-rules", json=rule).status_code == 403)

slots = stuA.get("/api/availability?date=" + tuesday.isoformat()).get_json()
check("4 slots generated for 13:00-15:00", [s["start_time"] for s in slots] == ["13:00", "13:30", "14:00", "14:30"])
check("other advisor's student sees nothing", stuD.get("/api/availability?date=" + tuesday.isoformat()).get_json() == [])

# --- requests ---
def request_slot(client, day, start, topic="Course selection"):
    return client.post("/api/appointments", json={"date": day.isoformat(), "start_time": start, "topic": topic, "description": "x"})

check("empty topic rejected", request_slot(stuA, tuesday, "13:00", topic="").status_code == 400)
check("past date rejected", request_slot(stuA, date.today() - timedelta(days=7), "13:00").status_code == 400)
check("time outside availability rejected", request_slot(stuA, tuesday, "16:00").status_code == 409)
wed = tuesday + timedelta(days=1)
check("closed/unavailable day rejected", request_slot(stuA, wed, "13:00").status_code == 409)

rA = request_slot(stuA, tuesday, "13:00")
rB = request_slot(stuB, tuesday, "13:00")
rC = request_slot(stuC, tuesday, "13:30")
check("student A request created", rA.status_code == 201)
check("student B can request same slot (pending)", rB.status_code == 201)
check("student C request created", rC.status_code == 201)
check("student cannot double-book own time", request_slot(stuA, tuesday, "13:00").status_code == 409)
check("student cannot approve", stuA.patch("/api/appointments/%d" % rA.get_json()["id"], json={"status": "approved"}).status_code == 403)

# --- files ---
aid, bid, cid = (r.get_json()["id"] for r in (rA, rB, rC))
pdf = (io.BytesIO(b"%PDF-1.4 test"), "staj_formu.pdf")
check("PDF upload works", stuA.post("/api/appointments/%d/files" % aid, data={"file": pdf}, content_type="multipart/form-data").status_code == 201)
check("non-PDF rejected", stuA.post("/api/appointments/%d/files" % aid, data={"file": (io.BytesIO(b"hello"), "a.txt")}, content_type="multipart/form-data").status_code == 400)
check("fake PDF rejected", stuA.post("/api/appointments/%d/files" % aid, data={"file": (io.BytesIO(b"hello"), "a.pdf")}, content_type="multipart/form-data").status_code == 400)
big = io.BytesIO(b"%PDF-" + b"0" * (5 * 1024 * 1024 + 10))
check("file over 5 MB rejected", stuA.post("/api/appointments/%d/files" % aid, data={"file": (big, "big.pdf")}, content_type="multipart/form-data").status_code == 413)
files = adv1.get("/api/appointments/%d/files" % aid).get_json()
check("advisor sees the file", len(files) == 1 and files[0]["original_name"] == "staj_formu.pdf")
check("advisor can download", adv1.get("/api/files/%d/download" % files[0]["id"]).status_code == 200)
check("other student cannot list files", stuB.get("/api/appointments/%d/files" % aid).status_code == 404)
check("other student cannot download", stuB.get("/api/files/%d/download" % files[0]["id"]).status_code == 404)
check("other student cannot upload", stuB.post("/api/appointments/%d/files" % aid, data={"file": (io.BytesIO(b"%PDF-1"), "x.pdf")}, content_type="multipart/form-data").status_code == 404)
check("other student cannot open appointment", stuB.get("/api/appointments/%d" % aid).status_code == 404)

# --- approve + conflict ---
r = adv1.patch("/api/appointments/%d" % aid, json={"status": "approved"})
check("advisor approves A", r.status_code == 200 and r.get_json()["status"] == "approved")
mine = {a["id"]: a for a in stuB.get("/api/my-appointments").get_json()}
check("B auto-rejected with reason", mine[bid]["status"] == "rejected" and "reserved" in mine[bid]["decision_reason"])
mineC = {a["id"]: a for a in stuC.get("/api/my-appointments").get_json()}
check("C (13:30) stays pending (13:00-13:30 and 13:30-14:00 do not conflict)", mineC[cid]["status"] == "pending")
check("approving answered request rejected", adv1.patch("/api/appointments/%d" % bid, json={"status": "approved"}).status_code == 409)
slots = stuC.get("/api/availability?date=" + tuesday.isoformat()).get_json()
check("13:00 shown as booked", next(s for s in slots if s["start_time"] == "13:00")["available"] is False)
check("booked slot cannot be requested", request_slot(stuB, tuesday, "13:00").status_code == 409)
check("advisor approves C", adv1.patch("/api/appointments/%d" % cid, json={"status": "approved"}).status_code == 200)

# --- overlap logic ---
check("overlap 13:00-13:30 vs 13:15-13:45", scheduling.overlaps(780, 810, 795, 825))
check("no overlap 13:00-13:30 vs 13:30-14:00", not scheduling.overlaps(780, 810, 810, 840))

# --- closed date ---
check("advisor closes a date", adv1.post("/api/blocked-dates", json={"date": (tuesday + timedelta(weeks=1)).isoformat()}).status_code == 201)
check("closed date has no slots", stuA.get("/api/availability?date=" + (tuesday + timedelta(weeks=1)).isoformat()).get_json() == [])
check("other weeks unaffected", len(stuA.get("/api/availability?date=" + (tuesday + timedelta(weeks=2)).isoformat()).get_json()) == 4)

# --- auth ---
anon = app.test_client()
check("anonymous API call -> 401", anon.get("/api/my-appointments").status_code == 401)
check("wrong password -> 401", anon.post("/api/auth/login", json={"email": "studenta@uni.edu", "password": "nope"}).status_code == 401)
check("pages load", stuA.get("/student").status_code == 200 and adv1.get("/advisor").status_code == 200)

print("\n%d/%d checks passed" % (sum(results), len(results)))
raise SystemExit(0 if all(results) else 1)
