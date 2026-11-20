"""Flask application for hostel student recognition and attendance."""

from __future__ import annotations

import base64
import csv
import hmac
import io
import json
import logging
import os
import sqlite3
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    send_from_directory,
    url_for,
)
from PIL import Image, UnidentifiedImageError
from werkzeug.utils import secure_filename

import face_engine


ROOT = Path(__file__).resolve().parent
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
STUDENT_FIELDS = (
    "name",
    "registration_no",
    "room_no",
    "department",
    "phone",
    "guardian_contact",
)


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exception_type, exception_value, traceback):
        try:
            return super().__exit__(exception_type, exception_value, traceback)
        finally:
            self.close()


def connect_db(app: Flask) -> sqlite3.Connection:
    connection = sqlite3.connect(
        app.config["DATABASE_PATH"], factory=ClosingConnection
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def create_schema(app: Flask) -> None:
    with connect_db(app) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                registration_no TEXT NOT NULL DEFAULT '',
                room_no TEXT NOT NULL DEFAULT '',
                department TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                guardian_contact TEXT NOT NULL DEFAULT '',
                photo TEXT NOT NULL DEFAULT '',
                legacy_age TEXT NOT NULL DEFAULT '',
                legacy_notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE UNIQUE INDEX IF NOT EXISTS students_registration_no_unique
                ON students(registration_no) WHERE registration_no <> '';
            CREATE UNIQUE INDEX IF NOT EXISTS students_name_unique
                ON students(name COLLATE NOCASE);
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                attendance_date TEXT NOT NULL,
                attendance_time TEXT NOT NULL,
                UNIQUE(student_id, attendance_date)
            );
            CREATE TABLE IF NOT EXISTS unknown_faces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot TEXT NOT NULL,
                detected_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER REFERENCES students(id) ON DELETE SET NULL,
                label TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )


def _clean(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _name_key(value: str) -> str:
    return " ".join(value.casefold().split())


def import_legacy_students(app: Flask) -> dict[str, list[str]]:
    """Import the supplied legacy CSV once; never overwrite existing app edits."""
    report: dict[str, list[str]] = {
        "unmatched_photos": [],
        "missing_photos": [],
        "duplicates": [],
        "missing_fields": [],
    }
    csv_path = Path(app.config["LEGACY_CSV"])
    photo_dir = Path(app.config["LEGACY_PHOTO_DIR"])
    with connect_db(app) as db:
        if db.execute(
            "SELECT 1 FROM app_state WHERE key = 'legacy_import_v1'"
        ).fetchone():
            saved_report = db.execute(
                "SELECT value FROM app_state WHERE key = 'legacy_quality_v1'"
            ).fetchone()
            if saved_report:
                return json.loads(saved_report["value"])
            rows = db.execute(
                "SELECT name, registration_no, room_no, department, guardian_contact, photo FROM students"
            ).fetchall()
            used_photos = {Path(row["photo"]).name.casefold() for row in rows if row["photo"]}
            report["missing_fields"] = [
                f"{row['name']}: {', '.join(field for field in ('registration_no', 'room_no', 'department', 'guardian_contact') if not row[field])}"
                for row in rows
                if any(not row[field] for field in ("registration_no", "room_no", "department", "guardian_contact"))
            ]
            report["missing_photos"] = [row["name"] for row in rows if not row["photo"]]
            if photo_dir.is_dir():
                report["unmatched_photos"] = sorted(
                    path.name
                    for path in photo_dir.iterdir()
                    if path.is_file()
                    and path.suffix.casefold() in ALLOWED_EXTENSIONS
                    and path.name.casefold() not in used_photos
                )
            db.execute(
                "INSERT INTO app_state(key, value) VALUES ('legacy_quality_v1', ?)",
                (json.dumps(report),),
            )
            return report

        used_photos: set[str] = set()
        seen_names: set[str] = set()
        matched_rows: list[dict[str, str]] = []
        if csv_path.is_file():
            with csv_path.open("r", encoding="utf-8-sig", newline="") as source:
                reader = csv.DictReader(source)
                for row in reader:
                    name = _clean(row.get("name"))
                    if not name:
                        report["duplicates"].append("Skipped a row with no name")
                        continue
                    key = _name_key(name)
                    if key in seen_names:
                        report["duplicates"].append(name)
                        continue
                    seen_names.add(key)

                    source_photo = Path(_clean(row.get("image_path"))).name
                    candidate = photo_dir / source_photo
                    if not source_photo or not candidate.is_file():
                        fallback = next(
                            (
                                path
                                for path in photo_dir.iterdir()
                                if path.is_file()
                                and path.stem.casefold() == Path(source_photo).stem.casefold()
                            ),
                            None,
                        )
                        candidate = fallback if fallback else candidate
                    if not candidate.is_file():
                        report["missing_photos"].append(name)
                        photo = ""
                    else:
                        photo = f"Hostel Student/{candidate.name}"
                        used_photos.add(candidate.name.casefold())

                    contact = "".join(_clean(row.get("contact")).split())
                    matched_rows.append(
                        {
                            "name": name,
                            "phone": contact,
                            "photo": photo,
                            "legacy_age": _clean(row.get("age")),
                            "legacy_notes": _clean(row.get("notes")),
                        }
                    )

        for row in matched_rows:
            db.execute(
                """
                INSERT INTO students
                    (name, phone, photo, legacy_age, legacy_notes)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    row["name"],
                    row["phone"],
                    row["photo"],
                    row["legacy_age"],
                    row["legacy_notes"],
                ),
            )
            absent = [
                field
                for field in ("registration_no", "room_no", "department", "guardian_contact")
                if not row.get(field)
            ]
            if absent:
                report["missing_fields"].append(f"{row['name']}: {', '.join(absent)}")

        if photo_dir.is_dir():
            report["unmatched_photos"] = sorted(
                path.name
                for path in photo_dir.iterdir()
                if path.is_file()
                and path.suffix.casefold() in ALLOWED_EXTENSIONS
                and path.name.casefold() not in used_photos
            )
        db.execute(
            "INSERT INTO app_state(key, value) VALUES ('legacy_import_v1', ?)",
            (datetime.now().isoformat(timespec="seconds"),),
        )
        db.execute(
            "INSERT INTO app_state(key, value) VALUES ('legacy_quality_v1', ?)",
            (json.dumps(report),),
        )
    return report


def _photo_url(photo: str) -> str:
    if photo.startswith("Hostel Student/"):
        return url_for("legacy_photo", filename=photo.split("/", 1)[1])
    if photo.startswith("static/uploads/"):
        return "/" + photo
    return ""


def _student_dict(row: sqlite3.Row) -> dict[str, object]:
    student = dict(row)
    student["photo_url"] = _photo_url(str(student.get("photo", "")))
    return student


def _read_encodings(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(payload, dict) and isinstance(payload.get("encodings"), list):
        return payload["encodings"]
    return []


def _refresh_encodings(app: Flask) -> dict[str, object]:
    with connect_db(app) as db:
        students = [
            dict(row)
            for row in db.execute("SELECT id, name, photo FROM students ORDER BY id")
        ]
    encodings, issues = face_engine.build_encodings(students, ROOT)
    face_engine.save_encodings(Path(app.config["ENCODINGS_PATH"]), encodings)
    app.config["ENCODINGS_CACHE"] = encodings
    app.config["ENCODING_ISSUES"] = issues
    return {"encoded": len(encodings), "issues": issues}


def _ensure_encodings(app: Flask) -> None:
    path = Path(app.config["ENCODINGS_PATH"])
    cached = _read_encodings(path)
    with connect_db(app) as db:
        student_ids = {
            row["id"]
            for row in db.execute("SELECT id FROM students")
        }
    cached_ids = {item.get("student_id") for item in cached}
    if cached and cached_ids == student_ids:
        app.config["ENCODINGS_CACHE"] = cached
        return
    try:
        _refresh_encodings(app)
    except (ImportError, RuntimeError, OSError) as exc:
        app.logger.warning("Face encodings were not refreshed: %s", exc)
        app.config["ENCODINGS_CACHE"] = []
        app.config["ENCODING_ISSUES"] = [f"Could not refresh face encodings: {exc}"]


def _save_upload(upload, upload_dir: Path) -> tuple[str, Path]:
    suffix = Path(secure_filename(upload.filename or "")).suffix.casefold()
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError("Choose a JPG, PNG, or WebP photo.")
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{suffix}"
    destination = upload_dir / filename
    try:
        upload.save(destination)
        with Image.open(destination) as image:
            image.verify()
    except (OSError, UnidentifiedImageError) as exc:
        destination.unlink(missing_ok=True)
        raise ValueError("The uploaded file is not a valid image.") from exc
    return f"static/uploads/{filename}", destination


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE_PATH=str(ROOT / "database" / "hostel.sqlite3"),
        LEGACY_CSV=str(ROOT / "FaceDetectionDataset.csv"),
        LEGACY_PHOTO_DIR=str(ROOT / "Hostel Student"),
        ENCODINGS_PATH=str(ROOT / "encodings.json"),
        UPLOAD_DIR=str(ROOT / "static" / "uploads"),
        MAX_CONTENT_LENGTH=8 * 1024 * 1024,
        AUTO_TRAIN=True,
        LOGIN_REQUIRED=True,
        ADMIN_USERNAME=os.environ.get("ADMIN_USERNAME", "admin"),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", ""),
        SECRET_KEY=os.environ.get("FLASK_SECRET_KEY") or uuid.uuid4().hex,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config:
        app.config.update(test_config)
    Path(app.config["DATABASE_PATH"]).parent.mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)

    create_schema(app)
    app.config["DATA_QUALITY"] = import_legacy_students(app)
    app.config["ENCODINGS_CACHE"] = []
    app.config["ENCODING_ISSUES"] = []
    if app.config["AUTO_TRAIN"]:
        _ensure_encodings(app)

    @app.before_request
    def protect_workspace():
        session.setdefault("csrf_token", uuid.uuid4().hex)
        endpoint = request.endpoint or ""
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            expected = session.get("csrf_token", "")
            supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
            if not expected or not hmac.compare_digest(expected, supplied):
                return jsonify(error="Your session token expired. Refresh the page and try again."), 400
        if not app.config["LOGIN_REQUIRED"]:
            return None
        if endpoint in {"login", "static"}:
            if endpoint == "static":
                filename = request.view_args.get("filename", "") if request.view_args else ""
                if filename.startswith("uploads/") and not session.get("admin"):
                    return jsonify(error="Sign in to view uploaded photos."), 401
            return None
        if session.get("admin"):
            return None
        if request.path.startswith("/api/"):
            return jsonify(error="Please sign in to continue."), 401
        return redirect(url_for("login", next=request.full_path))

    @app.context_processor
    def template_security_context():
        return {"csrf_token": session.get("csrf_token", "")}

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = ""
        if request.method == "POST":
            configured_password = app.config["ADMIN_PASSWORD"]
            if not configured_password:
                error = "Set the ADMIN_PASSWORD environment variable before signing in."
            elif (
                hmac.compare_digest(request.form.get("username", ""), app.config["ADMIN_USERNAME"])
                and hmac.compare_digest(request.form.get("password", ""), configured_password)
            ):
                session.clear()
                session["admin"] = app.config["ADMIN_USERNAME"]
                session["csrf_token"] = uuid.uuid4().hex
                destination = request.args.get("next", "")
                if not destination.startswith("/") or destination.startswith("//"):
                    destination = url_for("dashboard")
                return redirect(destination)
            else:
                error = "The username or password was not accepted."
        return render_template("login.html", error=error)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    def dashboard():
        return render_template("dashboard.html", active="dashboard")

    @app.get("/recognition")
    def recognition_page():
        return render_template("recognition.html", active="recognition")

    @app.get("/students")
    def students_page():
        return render_template("students.html", active="students")

    @app.get("/students/new")
    def add_student_page():
        return render_template("student_form.html", active="students")

    @app.get("/students/<int:student_id>")
    def student_profile(student_id: int):
        with connect_db(app) as db:
            student = db.execute(
                "SELECT * FROM students WHERE id = ?", (student_id,)
            ).fetchone()
            if student is None:
                return render_template("not_found.html", active="students"), 404
            history = db.execute(
                """
                SELECT attendance_date, attendance_time FROM attendance
                WHERE student_id = ? ORDER BY attendance_date DESC
                """,
                (student_id,),
            ).fetchall()
            count = db.execute(
                "SELECT COUNT(*) AS count FROM attendance WHERE student_id = ?",
                (student_id,),
            ).fetchone()["count"]
            tracked_days = db.execute(
                "SELECT COUNT(DISTINCT attendance_date) FROM attendance"
            ).fetchone()[0]
        student_data = _student_dict(student)
        return render_template(
            "profile.html",
            active="students",
            student=student_data,
            history=history,
            attendance_count=count,
            attendance_percentage=(
                round(count * 100 / tracked_days) if tracked_days else None
            ),
            tracked_days=tracked_days,
            photo_url=student_data["photo_url"],
        )

    @app.get("/attendance")
    def attendance_page():
        return render_template("attendance.html", active="attendance")

    @app.get("/hostel-photos/<path:filename>")
    def legacy_photo(filename: str):
        return send_from_directory(app.config["LEGACY_PHOTO_DIR"], filename)

    @app.get("/api/dashboard")
    def dashboard_data():
        today = date.today().isoformat()
        with connect_db(app) as db:
            total = db.execute("SELECT COUNT(*) FROM students").fetchone()[0]
            present = db.execute(
                "SELECT COUNT(*) FROM attendance WHERE attendance_date = ?", (today,)
            ).fetchone()[0]
            unknown = db.execute(
                "SELECT COUNT(*) FROM unknown_faces WHERE detected_at LIKE ?",
                (today + "%",),
            ).fetchone()[0]
            activities = db.execute(
                """
                SELECT label, created_at FROM activity
                ORDER BY id DESC LIMIT 8
                """
            ).fetchall()
            trend = db.execute(
                """
                SELECT attendance_date, COUNT(*) AS count FROM attendance
                WHERE attendance_date >= ? GROUP BY attendance_date
                ORDER BY attendance_date
                """,
                ((date.today() - timedelta(days=6)).isoformat(),),
            ).fetchall()
        return jsonify(
            {
                "total_students": total,
                "present_today": present,
                "absent_today": max(total - present, 0),
                "unknown_today": unknown,
                "activities": [dict(row) for row in activities],
                "attendance_trend": [dict(row) for row in trend],
                "data_quality": app.config["DATA_QUALITY"],
                "encoding_issues": app.config["ENCODING_ISSUES"],
            }
        )

    @app.get("/api/students")
    def list_students():
        with connect_db(app) as db:
            students = db.execute("SELECT * FROM students ORDER BY name COLLATE NOCASE").fetchall()
        encoded_ids = {
            item.get("student_id") for item in app.config["ENCODINGS_CACHE"]
        }
        result = [_student_dict(row) for row in students]
        for student in result:
            student["encoding_available"] = student["id"] in encoded_ids
        return jsonify(result)

    @app.post("/api/students")
    def add_student():
        values = {field: _clean(request.form.get(field)) for field in STUDENT_FIELDS}
        if not values["name"]:
            return jsonify(error="Student name is required."), 400
        saved_photo = ""
        destination = None
        upload = request.files.get("photo")
        if not upload or not upload.filename:
            return jsonify(error="A face photo is required for a new student."), 400
        try:
            saved_photo, destination = _save_upload(upload, Path(app.config["UPLOAD_DIR"]))
            face_engine.encode_photo(destination)
        except (RuntimeError, ImportError) as exc:
            if destination and destination.exists():
                destination.unlink()
            return jsonify(error=str(exc)), 503
        except ValueError as exc:
            if destination and destination.exists():
                destination.unlink()
            return jsonify(error=str(exc)), 400
        try:
            with connect_db(app) as db:
                cursor = db.execute(
                    """
                    INSERT INTO students
                        (name, registration_no, room_no, department, phone,
                         guardian_contact, photo)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (*[values[field] for field in STUDENT_FIELDS], saved_photo),
                )
                student_id = cursor.lastrowid
                db.execute(
                    "INSERT INTO activity(student_id, label, created_at) VALUES (?, ?, ?)",
                    (student_id, f"Added student {values['name']}", datetime.now().isoformat(timespec="seconds")),
                )
        except sqlite3.IntegrityError:
            if destination and destination.exists():
                destination.unlink()
            return jsonify(error="A student with that name or registration number already exists."), 409
        training = _refresh_encodings(app)
        with connect_db(app) as db:
            student = db.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        return jsonify(student=_student_dict(student), training=training), 201

    @app.put("/api/students/<int:student_id>")
    def update_student(student_id: int):
        values = {field: _clean(request.form.get(field)) for field in STUDENT_FIELDS}
        if not values["name"]:
            return jsonify(error="Student name is required."), 400
        with connect_db(app) as db:
            current = db.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        if current is None:
            return jsonify(error="Student not found."), 404

        photo = current["photo"]
        destination = None
        upload = request.files.get("photo")
        if upload and upload.filename:
            try:
                photo, destination = _save_upload(upload, Path(app.config["UPLOAD_DIR"]))
                face_engine.encode_photo(destination)
            except (RuntimeError, ImportError) as exc:
                if destination and destination.exists():
                    destination.unlink()
                return jsonify(error=str(exc)), 503
            except ValueError as exc:
                if destination and destination.exists():
                    destination.unlink()
                return jsonify(error=str(exc)), 400
        try:
            with connect_db(app) as db:
                db.execute(
                    """
                    UPDATE students SET name = ?, registration_no = ?, room_no = ?,
                        department = ?, phone = ?, guardian_contact = ?, photo = ?
                    WHERE id = ?
                    """,
                    (*[values[field] for field in STUDENT_FIELDS], photo, student_id),
                )
                db.execute(
                    "INSERT INTO activity(student_id, label, created_at) VALUES (?, ?, ?)",
                    (student_id, f"Updated student {values['name']}", datetime.now().isoformat(timespec="seconds")),
                )
        except sqlite3.IntegrityError:
            if destination and destination.exists():
                destination.unlink()
            return jsonify(error="A student with that name or registration number already exists."), 409
        training = _refresh_encodings(app)
        with connect_db(app) as db:
            student = db.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        return jsonify(student=_student_dict(student), training=training)

    @app.delete("/api/students/<int:student_id>")
    def delete_student(student_id: int):
        with connect_db(app) as db:
            student = db.execute("SELECT name FROM students WHERE id = ?", (student_id,)).fetchone()
            if student is None:
                return jsonify(error="Student not found."), 404
            db.execute("DELETE FROM students WHERE id = ?", (student_id,))
            db.execute(
                "INSERT INTO activity(label, created_at) VALUES (?, ?)",
                (f"Removed student {student['name']} from records", datetime.now().isoformat(timespec="seconds")),
            )
        training = _refresh_encodings(app)
        return jsonify(ok=True, training=training)

    @app.post("/api/retrain")
    def retrain():
        try:
            return jsonify(_refresh_encodings(app))
        except (ImportError, RuntimeError, OSError) as exc:
            app.logger.exception("Unable to refresh face encodings")
            return jsonify(error=str(exc)), 503

    last_unknown_snapshot = 0.0

    @app.post("/api/recognize")
    def recognize():
        nonlocal last_unknown_snapshot
        payload = request.get_json(silent=True) or {}
        image_data = payload.get("image", "")
        if not isinstance(image_data, str) or "," not in image_data:
            return jsonify(error="Provide a captured image."), 400
        try:
            raw = base64.b64decode(image_data.split(",", 1)[1], validate=True)
            with Image.open(io.BytesIO(raw)) as image:
                image_rgb = image.convert("RGB")
                image_size = image_rgb.size
                import numpy as np

                frame = np.asarray(image_rgb)
            detections = face_engine.recognize_image(
                frame, app.config["ENCODINGS_CACHE"]
            )
        except (ValueError, UnidentifiedImageError, OSError) as exc:
            return jsonify(error=f"Invalid image: {exc}"), 400
        except (ImportError, RuntimeError) as exc:
            app.logger.exception("Face recognition is unavailable")
            return jsonify(error=str(exc)), 503

        response_faces = []
        for detection in detections:
            student_id = detection["student_id"]
            student_data = None
            if student_id is not None:
                with connect_db(app) as db:
                    row = db.execute(
                        "SELECT * FROM students WHERE id = ?", (student_id,)
                    ).fetchone()
                    if row is not None:
                        student_data = _student_dict(row)
                        today = date.today().isoformat()
                        now = datetime.now().isoformat(timespec="seconds")
                        attendance_cursor = db.execute(
                            """
                            INSERT OR IGNORE INTO attendance
                                (student_id, attendance_date, attendance_time)
                            VALUES (?, ?, ?)
                            """,
                            (student_id, today, datetime.now().strftime("%H:%M:%S")),
                        )
                        if attendance_cursor.rowcount:
                            db.execute(
                                "INSERT INTO activity(student_id, label, created_at) VALUES (?, ?, ?)",
                                (student_id, f"Recognized {row['name']}", now),
                            )
            else:
                if time.monotonic() - last_unknown_snapshot >= 15:
                    snapshot_name = f"unknown-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.jpg"
                    snapshot_path = Path(app.config["UPLOAD_DIR"]) / snapshot_name
                    Image.fromarray(frame).save(snapshot_path, format="JPEG", quality=86)
                    with connect_db(app) as db:
                        detected_at = datetime.now().isoformat(timespec="seconds")
                        db.execute(
                            "INSERT INTO unknown_faces(snapshot, detected_at) VALUES (?, ?)",
                            (f"static/uploads/{snapshot_name}", detected_at),
                        )
                        db.execute(
                            "INSERT INTO activity(label, created_at) VALUES (?, ?)",
                            ("Unknown face snapshot saved", detected_at),
                        )
                    last_unknown_snapshot = time.monotonic()
            response_faces.append(
                {
                    **detection,
                    "student": student_data,
                    "box": list(detection["box"]),
                    "image_width": image_size[0],
                    "image_height": image_size[1],
                }
            )
        return jsonify(faces=response_faces)

    @app.get("/api/attendance")
    def attendance_data():
        selected_date = request.args.get("date", date.today().isoformat())
        with connect_db(app) as db:
            records = db.execute(
                """
                SELECT a.attendance_date, a.attendance_time, s.id AS student_id,
                    s.name, s.registration_no, s.room_no, s.department, s.photo
                FROM attendance a JOIN students s ON s.id = a.student_id
                WHERE a.attendance_date = ?
                ORDER BY a.attendance_time DESC
                """,
                (selected_date,),
            ).fetchall()
        return jsonify(
            [
                {
                    **dict(row),
                    "photo_url": _photo_url(row["photo"]),
                }
                for row in records
            ]
        )

    @app.get("/api/students/<int:student_id>/attendance")
    def student_attendance(student_id: int):
        with connect_db(app) as db:
            records = db.execute(
                """
                SELECT attendance_date, attendance_time FROM attendance
                WHERE student_id = ? ORDER BY attendance_date DESC
                """,
                (student_id,),
            ).fetchall()
        return jsonify([dict(row) for row in records])

    @app.get("/api/attendance/export.csv")
    def export_attendance():
        selected_date = request.args.get("date", date.today().isoformat())
        with connect_db(app) as db:
            records = db.execute(
                """
                SELECT a.attendance_date, a.attendance_time, s.name,
                    s.registration_no, s.room_no, s.department, s.phone
                FROM attendance a JOIN students s ON s.id = a.student_id
                WHERE a.attendance_date = ? ORDER BY a.attendance_time
                """,
                (selected_date,),
            ).fetchall()
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            ["Date", "Time", "Name", "Registration no.", "Room no.", "Department", "Phone"]
        )
        writer.writerows([tuple(row) for row in records])
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="attendance-{selected_date}.csv"'
            },
        )

    @app.errorhandler(413)
    def too_large(_error):
        return jsonify(error="The upload is too large (maximum 8 MB)."), 413

    return app


app = create_app()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
