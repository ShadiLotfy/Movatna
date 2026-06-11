from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))
load_dotenv(BASE_DIR / ".env")

from outlook_mail import extract_otp_code, mask_code, mask_email, poll_latest_otp_graph, send_graph_email  # noqa: E402


SAMPLES = [
    ("plain 6 digit", "Your Movanta one-time password is 123456. It expires in 5 minutes.", "123456"),
    ("html spaced", "<p>Your login code is <strong>12 34 56</strong></p>", "123456"),
    ("4 digit", "Verification code: 9876", "9876"),
    ("5 digit", "OTP 54321", "54321"),
    ("8 digit", "Use one-time password 11223344 to sign in", "11223344"),
    ("zero width", "Your code is 12\u200b34\u200c56", "123456"),
]


def run_samples() -> int:
    ok = True
    for name, text, expected in SAMPLES:
        actual = extract_otp_code(text)
        passed = actual == expected
        ok = ok and passed
        print(f"{name}: {'ok' if passed else 'fail'}")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Test Outlook Graph OTP sending and mailbox detection.")
    parser.add_argument("--samples", action="store_true", help="Run local OTP extraction samples.")
    parser.add_argument("--send", metavar="EMAIL", help="Send a test OTP email through Outlook Graph.")
    parser.add_argument("--poll", action="store_true", help="Poll Outlook mailbox for the newest OTP email.")
    parser.add_argument("--timeout", type=int, default=30, help="Mailbox poll timeout in seconds.")
    parser.add_argument("--interval", type=int, default=5, help="Mailbox poll interval in seconds.")
    parser.add_argument("--folder", default=os.environ.get("OUTLOOK_GRAPH_FOLDER", "inbox"), help="Graph mail folder to check.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger("outlook-otp-test")

    if args.samples or (not args.send and not args.poll):
        sample_status = run_samples()
        if sample_status != 0:
            return sample_status

    if args.send:
        test_otp = "123456"
        logger.info("Sending test OTP email to %s", mask_email(args.send))
        send_graph_email(
            args.send,
            "Your Movanta login code",
            f"Your Movanta one-time password is {test_otp}.",
            f"<p>Your Movanta one-time password is <strong>{test_otp}</strong>.</p>",
            logger=logger,
        )
        logger.info("Send accepted by Microsoft Graph")

    if args.poll:
        logger.info("Polling Outlook folder=%s timeout=%ss", args.folder, args.timeout)
        found = poll_latest_otp_graph(
            logger=logger,
            folder=args.folder,
            timeout_seconds=args.timeout,
            interval_seconds=args.interval,
            since=datetime.now(timezone.utc).replace(microsecond=0) if args.send else None,
        )
        if not found:
            print("No OTP found before timeout.")
            return 2
        print(f"OTP found: {mask_code(found.code)}")
        print(f"OTP length: {len(found.code)}")
        print(f"Received at: {found.received_at}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
