from __future__ import annotations

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")


def main() -> int:
    api_key = os.environ.get("EMAIL_SERVICE_API_KEY", "").strip()
    email_from = os.environ.get("EMAIL_FROM", "onboarding@resend.dev").strip()
    email_to = os.environ.get("ADMIN_EMAIL", "").strip()

    if not api_key or api_key == "re_xxxxxxxxx":
        print("Set EMAIL_SERVICE_API_KEY to your real Resend API key first.")
        return 1
    if not email_to:
        print("Set ADMIN_EMAIL to the recipient email you want to test.")
        return 1

    response = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "from": email_from,
            "to": [email_to],
            "subject": "Hello World",
            "html": "<p>Congrats on sending your <strong>first email</strong>!</p>",
        },
        timeout=15,
    )

    print(response.status_code)
    print(response.text)
    response.raise_for_status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
