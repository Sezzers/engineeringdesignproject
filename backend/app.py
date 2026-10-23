import os
from functools import wraps

from flask import Flask, jsonify, redirect, render_template, request, session
from werkzeug.security import check_password_hash

from database import get_db, init_db

app = Flask(__name__, template_folder="../frontend", static_folder="../frontend/static")
# Use a real secret from the environment in production
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

HOME_BY_ROLE = {"student": "/student", "advisor": "/advisor"}


def login_required(role=None):
    """Protect a page. Redirect to /login if not signed in or wrong role."""
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return redirect("/login")
            if role and session.get("role") != role:
                return redirect(HOME_BY_ROLE[session["role"]])
            return view(*args, **kwargs)
        return wrapper
    return decorator


# ---------- Pages ----------

@app.route("/")
def index():
    if "user_id" in session:
        return redirect(HOME_BY_ROLE[session["role"]])
    return redirect("/login")


@app.route("/login")
def login_page():
    if "user_id" in session:
        return redirect(HOME_BY_ROLE[session["role"]])
    return render_template("login.html")


@app.route("/student")
@login_required("student")
def student_home():
    return render_template("student_home.html")


@app.route("/advisor")
@login_required("advisor")
def advisor_home():
    return render_template("advisor_home.html")


# ---------- API ----------

@app.route("/api/auth/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify(error="Email and password are required."), 400

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()

    if user is None or not check_password_hash(user["password_hash"], password):
        return jsonify(error="Invalid email or password."), 401

    session.clear()
    session["user_id"] = user["id"]
    session["role"] = user["role"]
    return jsonify(
        id=user["id"],
        full_name=user["full_name"],
        role=user["role"],
        redirect=HOME_BY_ROLE[user["role"]],
    )


@app.route("/api/auth/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify(ok=True)


@app.route("/api/me")
def api_me():
    if "user_id" not in session:
        return jsonify(error="Not authenticated."), 401

    conn = get_db()
    user = conn.execute(
        "SELECT id, email, full_name, role FROM users WHERE id = ?", (session["user_id"],)
    ).fetchone()
    result = dict(user)
    if user["role"] == "student":
        advisor = conn.execute(
            """SELECT u.id, u.full_name, u.email, a.department
               FROM students s
               JOIN users u ON u.id = s.advisor_id
               JOIN advisors a ON a.user_id = s.advisor_id
               WHERE s.user_id = ?""",
            (user["id"],),
        ).fetchone()
        result["advisor"] = dict(advisor) if advisor else None
    conn.close()
    return jsonify(result)


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
