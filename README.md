# engineeringdesignproject
In this project the idea is making an academic advising appointment system. It is a system where students request appointments with academic advisors during available time slots and share files. Advisors can manage their weekly availability and approve or reject appointment requests after checking for scheduling conflicts.


## Running

```
cd backend
pip install -r requirements.txt
python seed.py     # demo data (password for all users: password123)
python app.py      # http://127.0.0.1:5000
python test_flow.py  # automated check of the whole flow
```

Demo logins: advisor1@uni.edu, advisor2@uni.edu, studenta@uni.edu ... studentf@uni.edu

## API

| Request | Purpose |
|---|---|
| GET /api/availability?date=YYYY-MM-DD | Student: slots of own advisor |
| GET/POST /api/availability-rules, DELETE /api/availability-rules/id | Advisor: weekly availability |
| GET/POST /api/blocked-dates, DELETE /api/blocked-dates/id | Advisor: close a single date |
| POST /api/appointments | Student: new request (status pending) |
| GET /api/my-appointments | Own appointments |
| PATCH /api/appointments/id | Advisor: approve or reject |
| GET/POST /api/appointments/id/files, GET /api/files/id/download | PDF files of an appointment |

Statuses: pending, approved, rejected. Slots are 30 minutes.
