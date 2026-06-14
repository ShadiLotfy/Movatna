from __future__ import annotations

import os
import tempfile
import unittest
from io import BytesIO
from unittest.mock import patch


class AuthAdminTests(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".sqlite3")
        os.environ["DATABASE_URL"] = f"sqlite:///{self.db_path}"
        os.environ["ADMIN_EMAIL"] = "admin@example.com"
        os.environ["ADMIN_PASSWORD"] = "AdminPass!23456"
        os.environ["ADMIN_USERNAME"] = "admin"
        os.environ["JWT_SECRET"] = "test-secret-for-unit-tests-only"
        os.environ["COOKIE_SECURE"] = "false"
        import app

        app.GLOBAL_RATE_LIMIT.clear()
        app.LOGIN_RATE_LIMIT.clear()
        self.app_module = app
        self.app = app.create_app()
        self.client = self.app.test_client()

    def tearDown(self):
        os.close(self.db_fd)
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def admin_login(self):
        response = self.client.post(
            "/api/auth/login",
            json={"identifier": "admin@example.com", "password": "AdminPass!23456"},
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))

    def test_admin_creates_user_and_generated_password_logs_in(self):
        self.admin_login()
        create = self.client.post(
            "/api/admin/users",
            json={
                "name": "Test User",
                "email": "user@example.com",
                "username": "testuser",
                "role": "user",
                "uploadLimit": 3,
            },
        )
        self.assertEqual(create.status_code, 201, create.get_data(as_text=True))
        data = create.get_json()
        self.assertIn("generatedPassword", data)
        self.assertEqual(data["user"]["uploadLimit"], 3)

        self.client.post("/api/auth/logout")
        login = self.client.post(
            "/api/auth/login",
            json={"identifier": "testuser", "password": data["generatedPassword"]},
        )
        self.assertEqual(login.status_code, 200, login.get_data(as_text=True))

    def test_duplicate_email_is_rejected(self):
        self.admin_login()
        payload = {
            "name": "Test User",
            "email": "dupe@example.com",
            "username": "dupe",
            "role": "user",
            "uploadLimit": 5,
        }
        self.assertEqual(self.client.post("/api/admin/users", json=payload).status_code, 201)
        payload["username"] = "dupe2"
        response = self.client.post("/api/admin/users", json=payload)
        self.assertEqual(response.status_code, 409)

    def test_admin_can_remove_and_readd_user_email(self):
        self.admin_login()
        payload = {
            "name": "Reusable User",
            "email": "reuse@example.com",
            "username": "reuse",
            "role": "user",
            "uploadLimit": 2,
        }
        create = self.client.post("/api/admin/users", json=payload)
        self.assertEqual(create.status_code, 201, create.get_data(as_text=True))
        user_id = create.get_json()["user"]["id"]

        delete = self.client.delete(f"/api/admin/users/{user_id}")
        self.assertEqual(delete.status_code, 200, delete.get_data(as_text=True))

        payload["name"] = "Reusable User Again"
        payload["uploadLimit"] = 7
        recreate = self.client.post("/api/admin/users", json=payload)
        self.assertEqual(recreate.status_code, 201, recreate.get_data(as_text=True))
        data = recreate.get_json()
        self.assertEqual(data["user"]["id"], user_id)
        self.assertEqual(data["user"]["uploadLimit"], 7)
        self.assertFalse(data["user"]["isDeleted"])
        self.assertTrue(data["user"]["isActive"])

        self.client.post("/api/auth/logout")
        login = self.client.post(
            "/api/auth/login",
            json={"identifier": "reuse@example.com", "password": data["generatedPassword"]},
        )
        self.assertEqual(login.status_code, 200, login.get_data(as_text=True))

    def test_disabled_user_cannot_login(self):
        self.admin_login()
        create = self.client.post(
            "/api/admin/users",
            json={
                "name": "Disabled User",
                "email": "disabled@example.com",
                "username": "disabled",
                "role": "user",
                "uploadLimit": 3,
            },
        )
        self.assertEqual(create.status_code, 201, create.get_data(as_text=True))
        data = create.get_json()
        update = self.client.patch(f"/api/admin/users/{data['user']['id']}", json={"isActive": False})
        self.assertEqual(update.status_code, 200, update.get_data(as_text=True))

        self.client.post("/api/auth/logout")
        login = self.client.post(
            "/api/auth/login",
            json={"identifier": "disabled", "password": data["generatedPassword"]},
        )
        self.assertEqual(login.status_code, 403)

    def test_change_password(self):
        self.admin_login()
        response = self.client.post(
            "/api/auth/change-password",
            json={"currentPassword": "AdminPass!23456", "newPassword": "NewAdminPass!789"},
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.client.post("/api/auth/logout")
        login = self.client.post(
            "/api/auth/login",
            json={"identifier": "admin", "password": "NewAdminPass!789"},
        )
        self.assertEqual(login.status_code, 200, login.get_data(as_text=True))

    def test_admin_analytics_tracks_upload_usage_and_shipping_lines(self):
        self.admin_login()
        create = self.client.post(
            "/api/admin/users",
            json={
                "name": "Analytics User",
                "email": "analytics@example.com",
                "username": "analytics",
                "role": "user",
                "uploadLimit": 5,
            },
        )
        self.assertEqual(create.status_code, 201, create.get_data(as_text=True))
        created_user = create.get_json()
        user_id = created_user["user"]["id"]
        password = created_user["generatedPassword"]

        self.client.post("/api/auth/logout")
        login = self.client.post("/api/auth/login", json={"identifier": "analytics", "password": password})
        self.assertEqual(login.status_code, 200, login.get_data(as_text=True))

        rows = [
            {"Line": "MAERSK", "Booking No.": "A"},
            {"Line": "MAERSK", "Booking No.": "B"},
            {"Line": "MSC", "Booking No.": "C"},
        ]
        with patch.object(self.app_module, "export_booking_data", return_value=rows):
            upload = self.client.post(
                "/api/extract",
                data={
                    "files": [
                        (BytesIO(b"%PDF-1.4"), "one.pdf"),
                        (BytesIO(b"%PDF-1.4"), "two.pdf"),
                        (BytesIO(b"%PDF-1.4"), "three.pdf"),
                    ]
                },
                content_type="multipart/form-data",
            )
        self.assertEqual(upload.status_code, 200, upload.get_data(as_text=True))
        upload_data = upload.get_json()
        self.assertEqual(upload_data["summary"], {"processed": 3, "skipped": 0, "failed": 0})

        duplicate_rows = [{"Line": "MAERSK", "Booking No.": " a "}]
        with patch.object(self.app_module, "export_booking_data", return_value=duplicate_rows):
            duplicate = self.client.post(
                "/api/extract",
                data={"files": [(BytesIO(b"%PDF-1.4"), "duplicate.pdf")]},
                content_type="multipart/form-data",
            )
        self.assertEqual(duplicate.status_code, 200, duplicate.get_data(as_text=True))
        duplicate_data = duplicate.get_json()
        self.assertEqual(len(duplicate_data["rows"]), 1)
        self.assertIn("Already processed", duplicate_data["rows"][0]["Comments"])
        self.assertEqual(duplicate_data["summary"], {"processed": 0, "skipped": 1, "failed": 0})
        self.assertEqual(duplicate_data["skipped"][0]["bookingNo"], "a")
        self.assertEqual(duplicate_data["skipped"][0]["line"], "MAERSK")

        self.client.post("/api/auth/logout")
        self.admin_login()
        analytics = self.client.get("/api/admin/analytics")
        self.assertEqual(analytics.status_code, 200, analytics.get_data(as_text=True))
        data = analytics.get_json()
        self.assertEqual(data["kpis"]["totalUploadsProcessed"], 3)
        self.assertEqual(data["kpis"]["mostUsedShippingLine"]["line"], "MAERSK")
        self.assertEqual(data["kpis"]["mostUsedShippingLine"]["count"], 2)
        self.assertEqual({item["fileName"] for item in data["recentUploads"]}, {"one.pdf", "two.pdf", "three.pdf", "duplicate.pdf"})
        self.assertEqual({item["line"] for item in data["recentUploads"]}, {"MAERSK", "MSC"})
        self.assertIn("duplicate", {item["status"] for item in data["recentUploads"]})
        user_row = next(item for item in data["users"] if item["username"] == "analytics")
        self.assertEqual(user_row["uploadsUsed"], 3)
        self.assertEqual(user_row["uploadsRemaining"], 2)
        admin_row = next(item for item in data["users"] if item["username"] == "admin")
        self.assertTrue(admin_row["isUnlimited"])
        self.assertEqual(admin_row["uploadLimitLabel"], "Unlimited")
        self.assertIsNone(admin_row["uploadsUsed"])
        self.assertIsNone(admin_row["uploadsRemaining"])

        disable = self.client.patch(f"/api/admin/users/{user_id}", json={"isActive": False})
        self.assertEqual(disable.status_code, 200, disable.get_data(as_text=True))
        refreshed = self.client.get("/api/admin/analytics")
        self.assertEqual(refreshed.status_code, 200, refreshed.get_data(as_text=True))
        refreshed_data = refreshed.get_json()
        self.assertEqual(refreshed_data["kpis"]["activeUsers"], 1)
        self.assertEqual(refreshed_data["kpis"]["disabledDeletedUsers"], 1)

    def test_manual_review_extraction_is_recorded_as_failed_not_success(self):
        self.admin_login()
        manual_row = {
            "Line": "Manual Review",
            "Booking No.": "",
            "Equipment": "",
            "Vessel Name": "",
            "Voyage No.": "",
            "Port of Loading": "",
            "Port of Discharge": "",
            "Final Dest.": "",
            "ETS POL / Sailing Date": "",
            "ETA POD / Arrival Date": "",
            "SI & VGM Cut Off (Calculated)": "",
            "Assigning Cut Off (Calculated)": "",
            "Gate In Cut Off (Calculated)": "",
            "Client": "",
            "Comments": "Could not confidently extract this PDF. Please review manually.",
        }

        with patch.object(self.app_module, "export_booking_data", return_value=[manual_row]):
            upload = self.client.post(
                "/api/extract",
                data={"files": [(BytesIO(b"%PDF-1.4"), "failed.pdf")]},
                content_type="multipart/form-data",
            )

        self.assertEqual(upload.status_code, 200, upload.get_data(as_text=True))
        data = upload.get_json()
        self.assertEqual(data["summary"], {"processed": 0, "skipped": 0, "failed": 1})
        self.assertEqual(data["rows"][0]["Line"], "Manual Review")
        self.assertEqual(data["rows"][0]["Booking No."], "")

        analytics = self.client.get("/api/admin/analytics")
        self.assertEqual(analytics.status_code, 200, analytics.get_data(as_text=True))
        analytics_data = analytics.get_json()
        self.assertEqual(analytics_data["kpis"]["totalUploadsProcessed"], 0)
        self.assertEqual(analytics_data["recentUploads"][0]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
