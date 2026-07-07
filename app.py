import os
import json
from datetime import datetime
from collections import defaultdict

from flask import (
    Flask, flash, redirect, render_template,
    request, session, url_for, jsonify,
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.secret_key = "hostelfix_sece_2025_secret"

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "app.sqlite3")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

db = SQLAlchemy(app)

UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
DB_READY = False

ADMIN_EMAIL    = "admin@sece.ac.in"
ADMIN_PASSWORD = "Admin@1234"


def is_admin():
    return session.get("role") == "admin"


class Complaint(db.Model):
    __tablename__ = "complaints"
    id             = db.Column(db.Integer,     primary_key=True)
    student_email  = db.Column(db.String(120), nullable=False, index=True)
    student_name   = db.Column(db.String(120), nullable=False)
    room_number    = db.Column(db.String(50),  nullable=False)
    category       = db.Column(db.String(50),  nullable=False)
    priority       = db.Column(db.String(10),  nullable=False)
    description    = db.Column(db.Text,        nullable=False)
    image_filename = db.Column(db.String(255), nullable=True)
    status         = db.Column(db.String(20),  nullable=False, default="Pending")
    admin_note     = db.Column(db.Text,        nullable=True)
    created_at     = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow)
    updated_at     = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow,
                               onupdate=datetime.utcnow)


def _allowed_image(filename):
    if not filename or "." not in filename:
        return False
    return filename.rsplit(".", 1)[1].lower() in {"png", "jpg", "jpeg", "webp"}


@app.before_request
def _setup():
    global DB_READY
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    if not DB_READY:
        db.create_all()
        DB_READY = True


@app.route("/")
def login():
    if "user" in session:
        return redirect(url_for("welcome"))
    return render_template("login.html")


@app.route("/login", methods=["POST"])
def handle_login():
    email    = (request.form.get("email")    or "").strip().lower()
    password = (request.form.get("password") or "").strip()

    if email == ADMIN_EMAIL and password == ADMIN_PASSWORD:
        session["user"] = email
        session["role"] = "admin"
        return redirect(url_for("welcome"))

    if email and password and email.endswith("@sece.ac.in"):
        session["user"] = email
        session["role"] = "student"
        return redirect(url_for("welcome"))

    return render_template("login.html", error="Invalid credentials or non-SECE email.")


@app.route("/welcome")
def welcome():
    if "user" not in session:
        return redirect(url_for("login"))

    if is_admin():
        complaints = Complaint.query.order_by(Complaint.created_at.desc()).all()

        from sqlalchemy import func
        cat_rows = db.session.query(
            Complaint.category, func.count(Complaint.id)
        ).group_by(Complaint.category).all()
        cat_labels = [r[0] for r in cat_rows]
        cat_counts = [r[1] for r in cat_rows]

        pri_rows = db.session.query(
            Complaint.priority, func.count(Complaint.id)
        ).group_by(Complaint.priority).all()
        pri_dict = {r[0]: r[1] for r in pri_rows}

        now = datetime.utcnow()
        month_labels = []
        monthly_issued   = []
        monthly_resolved = []
        for i in range(5, -1, -1):
            m = now.month - i
            y = now.year
            while m <= 0:
                m += 12
                y -= 1
            month_labels.append(datetime(y, m, 1).strftime("%b %Y"))
            issued   = sum(1 for c in complaints if c.created_at.month == m and c.created_at.year == y)
            resolved = sum(1 for c in complaints if c.status == "Resolved"
                           and c.updated_at.month == m and c.updated_at.year == y)
            monthly_issued.append(issued)
            monthly_resolved.append(resolved)

    else:
        complaints = (
            Complaint.query
            .filter_by(student_email=session["user"])
            .order_by(Complaint.created_at.desc())
            .all()
        )
        cat_labels = cat_counts = month_labels = monthly_issued = monthly_resolved = []
        pri_dict = {}

    total       = len(complaints)
    pending     = sum(1 for c in complaints if c.status == "Pending")
    in_progress = sum(1 for c in complaints if c.status == "In Progress")
    resolved    = sum(1 for c in complaints if c.status == "Resolved")
    stats = dict(total=total, pending=pending, in_progress=in_progress, resolved=resolved)

    return render_template(
        "welcome.html",
        email=session["user"],
        role=session.get("role"),
        complaints=complaints,
        stats=stats,
        cat_labels=json.dumps(cat_labels),
        cat_counts=json.dumps(cat_counts),
        pri_dict=json.dumps(pri_dict),
        month_labels=json.dumps(month_labels),
        monthly_issued=json.dumps(monthly_issued),
        monthly_resolved=json.dumps(monthly_resolved),
    )


@app.route("/complaint")
def complaint():
    if "user" not in session:
        return redirect(url_for("login"))
    if is_admin():
        flash("Admins cannot submit complaints.")
        return redirect(url_for("welcome"))
    return render_template("complaint.html")


@app.route("/submit_complaint", methods=["POST"])
def submit_complaint():
    if "user" not in session:
        return redirect(url_for("login"))
    if is_admin():
        return redirect(url_for("welcome"))

    student_name = (request.form.get("name")        or "").strip()
    room_number  = (request.form.get("room")        or "").strip()
    category     = (request.form.get("category")    or "").strip()
    priority     = (request.form.get("priority")    or "").strip()
    description  = (request.form.get("description") or "").strip()

    if not all([student_name, room_number, category, priority, description]):
        flash("Please fill all required fields.")
        return redirect(url_for("complaint"))
    if len(description) > 500:
        flash("Description must be 500 characters or less.")
        return redirect(url_for("complaint"))

    priority = {"Low": "Low", "Medium": "Medium", "High": "High"}.get(priority, priority)

    c = Complaint(
        student_email=session["user"],
        student_name=student_name,
        room_number=room_number,
        category=category,
        priority=priority,
        description=description,
        status="Pending",
    )
    db.session.add(c)
    db.session.commit()

    uploaded = request.files.get("image")
    if uploaded and uploaded.filename and uploaded.filename.strip():
        if not _allowed_image(uploaded.filename):
            flash("Invalid image type. Upload PNG/JPG/JPEG/WEBP only.")
            return redirect(url_for("complaint"))
        final_filename = f"{c.id}_{secure_filename(uploaded.filename)}"
        uploaded.save(os.path.join(UPLOAD_DIR, final_filename))
        c.image_filename = final_filename
        db.session.commit()

    flash("Complaint submitted successfully!")
    return redirect(url_for("welcome"))


@app.route("/admin/update_complaint/<int:cid>", methods=["POST"])
def update_complaint(cid):
    if not is_admin():
        return jsonify({"ok": False, "error": "Unauthorized"}), 403
    c = Complaint.query.get_or_404(cid)
    new_status = (request.form.get("status")     or "").strip()
    admin_note = (request.form.get("admin_note") or "").strip()
    if new_status in {"Pending", "In Progress", "Resolved"}:
        c.status = new_status
    c.admin_note = admin_note
    c.updated_at = datetime.utcnow()
    db.session.commit()
    flash(f"Complaint #{cid} updated to '{c.status}'.")
    return redirect(url_for("welcome"))


@app.route("/admin/delete_complaint/<int:cid>", methods=["POST"])
def delete_complaint(cid):
    if not is_admin():
        return jsonify({"ok": False, "error": "Unauthorized"}), 403
    c = Complaint.query.get_or_404(cid)
    if c.image_filename:
        img_path = os.path.join(UPLOAD_DIR, c.image_filename)
        if os.path.exists(img_path):
            os.remove(img_path)
    db.session.delete(c)
    db.session.commit()
    flash(f"Complaint #{cid} deleted.")
    return redirect(url_for("welcome"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)
