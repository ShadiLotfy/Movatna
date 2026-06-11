from __future__ import annotations

import os
import tempfile
import unittest


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


if __name__ == "__main__":
    unittest.main()
