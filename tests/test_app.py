import base64
import io
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import app as application


ROOT = Path(__file__).resolve().parents[1]


class HostelAppTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.app = application.create_app(
            {
                "TESTING": True,
                "LOGIN_REQUIRED": False,
                "AUTO_TRAIN": False,
                "DATABASE_PATH": str(self.root / "hostel.sqlite3"),
                "UPLOAD_DIR": str(self.root / "uploads"),
                "ENCODINGS_PATH": str(self.root / "encodings.json"),
                "LEGACY_CSV": str(ROOT / "FaceDetectionDataset.csv"),
                "LEGACY_PHOTO_DIR": str(ROOT / "Hostel Student"),
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary.cleanup()

    def _csrf_headers(self):
        self.client.get("/")
        with self.client.session_transaction() as session:
            return {"X-CSRF-Token": session["csrf_token"]}

    def _database(self):
        return closing(sqlite3.connect(self.app.config["DATABASE_PATH"]))

    def test_imports_ten_students_and_reports_unmatched_photo(self):
        response = self.client.get("/api/students")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.get_json()), 10)
        dashboard = self.client.get("/api/dashboard").get_json()
        self.assertEqual(dashboard["total_students"], 10)
        self.assertEqual(dashboard["absent_today"], 10)
        self.assertEqual(
            self.app.config["DATA_QUALITY"]["unmatched_photos"],
            ["WhatsApp Image 2025-10-15 at 23.33.14_174f4a85.jpg"],
        )
        self.assertTrue(
            all(
                not student["registration_no"]
                and not student["room_no"]
                and not student["department"]
                and not student["guardian_contact"]
                for student in response.get_json()
            )
        )

    def test_new_student_requires_a_photo(self):
        response = self.client.post(
            "/api/students",
            data={"name": "New Student"},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("photo is required", response.get_json()["error"])

    def test_student_can_be_added_edited_and_removed_without_deleting_photo(self):
        image_buffer = io.BytesIO()
        Image.new("RGB", (20, 20), color="blue").save(image_buffer, format="PNG")
        image_buffer.seek(0)
        with patch.object(application.face_engine, "encode_photo", return_value=[0.0] * 128), patch.object(
            application.face_engine,
            "build_encodings",
            side_effect=lambda students, root: (
                [{"student_id": students[-1]["id"], "encoding": [0.0] * 128}],
                [],
            ),
        ):
            created = self.client.post(
                "/api/students",
                data={
                    "name": "New Student",
                    "registration_no": "R-100",
                    "room_no": "B-10",
                    "department": "Science",
                    "phone": "123456789",
                    "guardian_contact": "987654321",
                    "photo": (image_buffer, "student.png"),
                },
                headers=self._csrf_headers(),
                content_type="multipart/form-data",
            )
            self.assertEqual(created.status_code, 201)
            student = created.get_json()["student"]
            photo_path = Path(self.app.config["UPLOAD_DIR"]) / Path(student["photo"]).name
            self.assertTrue(photo_path.is_file())
            edited = self.client.put(
                f"/api/students/{student['id']}",
                data={
                    "name": "Updated Student",
                    "registration_no": "R-100",
                    "room_no": "B-11",
                    "department": "Science",
                    "phone": "123456789",
                    "guardian_contact": "987654321",
                },
                headers=self._csrf_headers(),
            )
            self.assertEqual(edited.status_code, 200)
            self.assertEqual(edited.get_json()["student"]["name"], "Updated Student")
            removed = self.client.delete(
                f"/api/students/{student['id']}", headers=self._csrf_headers()
            )
        self.assertEqual(removed.status_code, 200)
        self.assertTrue(photo_path.is_file())
        names = [student["name"] for student in self.client.get("/api/students").get_json()]
        self.assertNotIn("Updated Student", names)

    def test_recognition_marks_attendance_once_per_day(self):
        image_buffer = io.BytesIO()
        Image.new("RGB", (40, 40), color="white").save(image_buffer, format="PNG")
        image = "data:image/png;base64," + base64.b64encode(image_buffer.getvalue()).decode()
        payload = {"image": image}
        detection = [
            {
                "box": (1, 30, 30, 1),
                "student_id": 1,
                "distance": 0.1,
                "confidence": 80.0,
            }
        ]
        with patch.object(application.face_engine, "recognize_image", return_value=detection):
            first = self.client.post(
                "/api/recognize", json=payload, headers=self._csrf_headers()
            )
            second = self.client.post(
                "/api/recognize", json=payload, headers=self._csrf_headers()
            )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        with self._database() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM attendance").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM activity").fetchone()[0], 1)

    def test_unknown_face_snapshot_is_saved_and_rate_limited(self):
        image_buffer = io.BytesIO()
        Image.new("RGB", (40, 40), color="white").save(image_buffer, format="PNG")
        image = "data:image/png;base64," + base64.b64encode(image_buffer.getvalue()).decode()
        unknown = [{"box": (1, 30, 30, 1), "student_id": None, "distance": 0.8, "confidence": 0.0}]
        with patch.object(application.face_engine, "recognize_image", return_value=unknown):
            for _ in range(2):
                response = self.client.post(
                    "/api/recognize",
                    json={"image": image},
                    headers=self._csrf_headers(),
                )
                self.assertEqual(response.status_code, 200)
        with self._database() as db:
            snapshot = db.execute("SELECT snapshot FROM unknown_faces").fetchone()
            self.assertEqual(db.execute("SELECT COUNT(*) FROM unknown_faces").fetchone()[0], 1)
        self.assertTrue((self.root / "uploads" / Path(snapshot[0]).name).is_file())

    def test_login_requires_credentials_and_csrf(self):
        secured_app = application.create_app(
            {
                "TESTING": True,
                "LOGIN_REQUIRED": True,
                "ADMIN_USERNAME": "warden",
                "ADMIN_PASSWORD": "safe-test-password",
                "AUTO_TRAIN": False,
                "DATABASE_PATH": str(self.root / "secured.sqlite3"),
                "UPLOAD_DIR": str(self.root / "secure-uploads"),
                "ENCODINGS_PATH": str(self.root / "secure-encodings.json"),
                "LEGACY_CSV": str(ROOT / "FaceDetectionDataset.csv"),
                "LEGACY_PHOTO_DIR": str(ROOT / "Hostel Student"),
            }
        )
        client = secured_app.test_client()
        self.assertEqual(client.get("/").status_code, 302)
        login_page = client.get("/login")
        self.assertEqual(login_page.status_code, 200)
        with client.session_transaction() as session:
            token = session["csrf_token"]
        response = client.post(
            "/login",
            data={
                "username": "warden",
                "password": "safe-test-password",
                "csrf_token": token,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(client.get("/api/students").status_code, 200)

    def test_primary_pages_render(self):
        for path in ("/", "/recognition", "/students", "/students/new", "/attendance", "/students/1"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)


if __name__ == "__main__":
    unittest.main()
