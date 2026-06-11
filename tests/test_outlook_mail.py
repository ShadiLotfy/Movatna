from __future__ import annotations

import logging
import time
import unittest
from unittest.mock import patch

import outlook_mail
from outlook_mail import extract_otp_code


class OtpExtractionTests(unittest.TestCase):
    def test_extracts_common_otp_lengths(self):
        cases = {
            "Your code is 1234": "1234",
            "Verification code: 12345": "12345",
            "Your one-time password is 123456": "123456",
            "Use login code 12345678": "12345678",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(extract_otp_code(text), expected)

    def test_extracts_html_and_invisible_formatting(self):
        text = "<html><body><p>Your OTP is <b>12&nbsp;34\u200b56</b></p></body></html>"
        self.assertEqual(extract_otp_code(text), "123456")

    def test_prefers_contextual_code(self):
        text = "Invoice 555555 was generated. Your verification code is 123456."
        self.assertEqual(extract_otp_code(text), "123456")

    def test_returns_none_without_otp(self):
        self.assertIsNone(extract_otp_code("No security code in this message."))


class OtpPollingTests(unittest.TestCase):
    def test_poll_timeout_returns_none(self):
        start = time.monotonic()
        with patch.object(outlook_mail, "graph_config_from_env", return_value=object()):
            with patch.object(outlook_mail, "latest_otp_graph_once", return_value=None):
                result = outlook_mail.poll_latest_otp_graph(
                    logger=logging.getLogger("test"),
                    timeout_seconds=0,
                    interval_seconds=1,
                )
        self.assertIsNone(result)
        self.assertLess(time.monotonic() - start, 1)


if __name__ == "__main__":
    unittest.main()
