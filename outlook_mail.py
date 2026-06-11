from __future__ import annotations

import html
import logging
import os
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import requests


GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
TOKEN_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
OTP_LENGTHS = {4, 5, 6, 8}
OTP_CONTEXT_RE = re.compile(
    r"\b(otp|one[-\s]*time|verification|verify|code|password|login|sign[-\s]*in)\b",
    re.IGNORECASE,
)
OTP_CANDIDATE_RE = re.compile(r"(?<!\d)(\d(?:[\s\u00a0\u200b\u200c\u200d\ufeff-]*\d){3,7})(?!\d)")


class OutlookMailError(RuntimeError):
    pass


class OutlookConfigError(OutlookMailError):
    pass


@dataclass(frozen=True)
class OutlookGraphConfig:
    tenant_id: str
    client_id: str
    client_secret: str
    refresh_token: str
    mailbox: str
    timeout_seconds: int
    retries: int

    @property
    def uses_delegated_token(self) -> bool:
        return bool(self.refresh_token)


@dataclass(frozen=True)
class OtpEmail:
    code: str
    received_at: str
    subject: str
    message_id: str


def outlook_graph_configured() -> bool:
    return bool(os.environ.get("OUTLOOK_GRAPH_CLIENT_ID", "").strip()) and (
        bool(os.environ.get("OUTLOOK_GRAPH_REFRESH_TOKEN", "").strip())
        or bool(os.environ.get("OUTLOOK_GRAPH_CLIENT_SECRET", "").strip())
    )


def graph_config_from_env() -> OutlookGraphConfig:
    client_id = os.environ.get("OUTLOOK_GRAPH_CLIENT_ID", "").strip()
    refresh_token = os.environ.get("OUTLOOK_GRAPH_REFRESH_TOKEN", "").strip()
    client_secret = os.environ.get("OUTLOOK_GRAPH_CLIENT_SECRET", "").strip()
    mailbox = os.environ.get("OUTLOOK_GRAPH_MAILBOX", os.environ.get("EMAIL_FROM", "")).strip()
    tenant_id = os.environ.get("OUTLOOK_GRAPH_TENANT_ID", "consumers").strip() or "consumers"
    timeout_seconds = int(os.environ.get("OUTLOOK_GRAPH_TIMEOUT_SECONDS", "10"))
    retries = int(os.environ.get("OUTLOOK_GRAPH_RETRIES", "3"))

    if not client_id:
        raise OutlookConfigError("OUTLOOK_GRAPH_CLIENT_ID is required for Outlook Graph mail.")
    if not refresh_token and not client_secret:
        raise OutlookConfigError("OUTLOOK_GRAPH_REFRESH_TOKEN or OUTLOOK_GRAPH_CLIENT_SECRET is required.")
    if not mailbox:
        raise OutlookConfigError("OUTLOOK_GRAPH_MAILBOX or EMAIL_FROM is required.")
    return OutlookGraphConfig(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        mailbox=mailbox,
        timeout_seconds=timeout_seconds,
        retries=max(1, retries),
    )


def graph_access_token(config: OutlookGraphConfig) -> str:
    token_url = TOKEN_URL_TEMPLATE.format(tenant=config.tenant_id)
    if config.refresh_token:
        data = {
            "client_id": config.client_id,
            "grant_type": "refresh_token",
            "refresh_token": config.refresh_token,
            "scope": os.environ.get(
                "OUTLOOK_GRAPH_SCOPES",
                "offline_access https://graph.microsoft.com/Mail.Send https://graph.microsoft.com/Mail.Read",
            ),
        }
        if config.client_secret:
            data["client_secret"] = config.client_secret
    else:
        data = {
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "grant_type": "client_credentials",
            "scope": "https://graph.microsoft.com/.default",
        }

    try:
        response = requests.post(token_url, data=data, timeout=config.timeout_seconds)
    except requests.RequestException as exc:
        raise OutlookMailError(f"Microsoft token refresh request failed: {exc.__class__.__name__}") from exc
    if not response.ok:
        raise OutlookMailError(f"Microsoft token refresh failed: {response.status_code} {safe_error(response)}")
    token = response.json().get("access_token")
    if not token:
        raise OutlookMailError("Microsoft token refresh returned no access token.")
    return token


def graph_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def send_graph_email(to_email: str, subject: str, text_body: str, html_body: str, *, logger: logging.Logger) -> None:
    config = graph_config_from_env()
    token = graph_access_token(config)
    endpoint = (
        f"{GRAPH_BASE_URL}/me/sendMail"
        if config.uses_delegated_token
        else f"{GRAPH_BASE_URL}/users/{config.mailbox}/sendMail"
    )
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": html_body},
            "toRecipients": [{"emailAddress": {"address": to_email}}],
        },
        "saveToSentItems": True,
    }

    for attempt in range(1, config.retries + 1):
        logger.info("Outlook Graph send attempt %s/%s to %s", attempt, config.retries, mask_email(to_email))
        try:
            response = requests.post(endpoint, headers=graph_headers(token), json=payload, timeout=config.timeout_seconds)
        except requests.RequestException as exc:
            if attempt < config.retries:
                wait_seconds = min(2 * attempt, 8)
                logger.warning(
                    "Outlook Graph send request failed with %s; retrying in %ss",
                    exc.__class__.__name__,
                    wait_seconds,
                )
                time.sleep(wait_seconds)
                continue
            raise OutlookMailError(f"Outlook Graph send request failed: {exc.__class__.__name__}") from exc
        if response.status_code == 202:
            logger.info("Outlook Graph accepted OTP email for %s", mask_email(to_email))
            return
        if response.status_code == 401 and attempt == 1:
            token = graph_access_token(config)
            continue
        if response.status_code in {429, 500, 502, 503, 504} and attempt < config.retries:
            wait_seconds = min(2 * attempt, 8)
            logger.warning(
                "Outlook Graph temporary send failure status=%s attempt=%s; retrying in %ss",
                response.status_code,
                attempt,
                wait_seconds,
            )
            time.sleep(wait_seconds)
            continue
        raise OutlookMailError(f"Outlook Graph send failed: {response.status_code} {safe_error(response)}")


def poll_latest_otp_graph(
    *,
    logger: logging.Logger,
    folder: str | None = None,
    timeout_seconds: int | None = None,
    interval_seconds: int | None = None,
    subject_hint: str | None = None,
    since: datetime | None = None,
) -> OtpEmail | None:
    config = graph_config_from_env()
    folder = (folder or os.environ.get("OUTLOOK_GRAPH_FOLDER", "inbox")).strip() or "inbox"
    if timeout_seconds is None:
        timeout_seconds = int(os.environ.get("OUTLOOK_GRAPH_POLL_SECONDS", "30"))
    if interval_seconds is None:
        interval_seconds = int(os.environ.get("OUTLOOK_GRAPH_POLL_INTERVAL_SECONDS", "5"))
    deadline = time.monotonic() + timeout_seconds

    attempt = 0
    while True:
        attempt += 1
        email = latest_otp_graph_once(
            logger=logger,
            config=config,
            folder=folder,
            subject_hint=subject_hint,
            since=since,
        )
        if email:
            return email
        if time.monotonic() >= deadline:
            logger.warning("No Outlook OTP email found before timeout after %s attempt(s)", attempt)
            return None
        time.sleep(interval_seconds)


def latest_otp_graph_once(
    *,
    logger: logging.Logger,
    config: OutlookGraphConfig,
    folder: str,
    subject_hint: str | None,
    since: datetime | None,
) -> OtpEmail | None:
    token = graph_access_token(config)
    endpoint = (
        f"{GRAPH_BASE_URL}/me/mailFolders/{folder}/messages"
        if config.uses_delegated_token
        else f"{GRAPH_BASE_URL}/users/{config.mailbox}/mailFolders/{folder}/messages"
    )
    params = {
        "$top": os.environ.get("OUTLOOK_GRAPH_MESSAGE_LIMIT", "20"),
        "$orderby": "receivedDateTime desc",
        "$select": "id,subject,receivedDateTime,bodyPreview,body",
    }
    try:
        response = requests.get(endpoint, headers=graph_headers(token), params=params, timeout=config.timeout_seconds)
    except requests.RequestException as exc:
        raise OutlookMailError(f"Outlook Graph mailbox read request failed: {exc.__class__.__name__}") from exc
    if response.status_code == 404:
        raise OutlookMailError(f"Outlook folder not found: {folder}")
    if response.status_code == 401:
        raise OutlookMailError("Outlook Graph token expired or lacks mail permissions.")
    if response.status_code == 429:
        raise OutlookMailError("Outlook Graph throttled the mailbox request.")
    if not response.ok:
        raise OutlookMailError(f"Outlook Graph mailbox read failed: {response.status_code} {safe_error(response)}")

    messages = response.json().get("value", [])
    logger.info("Outlook Graph checked folder=%s messages=%s", folder, len(messages))
    for message in messages:
        subject = message.get("subject") or ""
        received_at = message.get("receivedDateTime") or ""
        if since and parse_message_datetime(received_at) and parse_message_datetime(received_at) < since:
            continue
        if subject_hint and subject_hint.lower() not in subject.lower():
            continue
        body = (message.get("body") or {}).get("content") or ""
        text = f"{subject}\n{message.get('bodyPreview') or ''}\n{body}"
        code = extract_otp_code(text)
        if code:
            logger.info(
                "Outlook OTP found timestamp=%s code=%s subject=%s",
                received_at,
                mask_code(code),
                sanitize_log_text(subject),
            )
            return OtpEmail(code=code, received_at=received_at, subject=subject, message_id=message.get("id") or "")
    return None


def extract_otp_code(message_text: str) -> str | None:
    text = normalize_message_text(message_text)
    scored: list[tuple[int, int, int, str]] = []
    for match in OTP_CANDIDATE_RE.finditer(text):
        raw = match.group(1)
        code = re.sub(r"\D", "", raw)
        if len(code) not in OTP_LENGTHS:
            continue
        window = text[max(0, match.start() - 80) : match.end() + 80]
        sentence_start = max(text.rfind(".", 0, match.start()), text.rfind("\n", 0, match.start()))
        sentence_end_candidates = [idx for idx in (text.find(".", match.end()), text.find("\n", match.end())) if idx != -1]
        sentence_end = min(sentence_end_candidates) if sentence_end_candidates else len(text)
        sentence = text[sentence_start + 1 : sentence_end]
        context_score = 2 if OTP_CONTEXT_RE.search(sentence) else 1 if OTP_CONTEXT_RE.search(window) else 0
        length_score = {6: 4, 8: 3, 5: 2, 4: 1}.get(len(code), 0)
        scored.append((context_score, length_score, -match.start(), code))
    if not scored:
        return None
    scored.sort(reverse=True)
    return scored[0][3]


def normalize_message_text(value: str) -> str:
    unescaped = html.unescape(strip_html(value or ""))
    normalized = unicodedata.normalize("NFKC", unescaped)
    normalized = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def strip_html(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?i)<br\s*/?>", "\n", value)
    value = re.sub(r"(?i)</p\s*>", "\n", value)
    return re.sub(r"(?s)<[^>]+>", " ", value)


def parse_message_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None


def mask_email(email: str) -> str:
    local, _, domain = (email or "").partition("@")
    if not domain:
        return "***"
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}***@{domain}"


def mask_code(code: str) -> str:
    if len(code) <= 2:
        return "*" * len(code)
    return f"{code[:2]}{'*' * (len(code) - 2)}"


def sanitize_log_text(value: str, limit: int = 80) -> str:
    text = normalize_message_text(value)
    return text[:limit]


def safe_error(response: requests.Response) -> str:
    try:
        data: Any = response.json()
    except ValueError:
        data = response.text[:300]
    text = str(data)
    return re.sub(r"(?i)(access_token|refresh_token|client_secret|password)['\"]?\s*[:=]\s*['\"]?[^,'\"}\s]+", r"\1=***", text)
