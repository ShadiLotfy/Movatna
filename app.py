from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import smtplib
import tempfile
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlparse

import jwt
import requests
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from flask import Flask, current_app, jsonify, make_response, render_template, request
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from sqlalchemy import func
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from werkzeug.utils import secure_filename

from booking_extractor import export_booking_data
from outlook_mail import OutlookMailError, outlook_graph_configured, send_graph_email


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
OTP_TTL_MINUTES = 5
SESSION_TTL_MINUTES = 30
MAX_CONTENT_LENGTH = 20 * 1024 * 1024
OTP_RATE_LIMIT: dict[str, list[datetime]] = {}
OTP_VERIFY_RATE_LIMIT: dict[str, list[datetime]] = {}
GLOBAL_RATE_LIMIT: dict[str, list[datetime]] = {}
ADMIN_LOGIN_RATE_LIMIT: dict[str, list[datetime]] = {}
EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,254}$", re.IGNORECASE)
PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16)

db = SQLAlchemy()


class AuthorizedUser(db.Model):
    __tablename__ = "authorized_users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    admin_password_hash = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: utcnow(), nullable=False)


class OtpChallenge(db.Model):
    __tablename__ = "otp_challenges"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    otp_hash = db.Column(db.String(128), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    attempts = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: utcnow(), nullable=False)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def is_valid_email(email: str) -> bool:
    return bool(email and len(email) <= 255 and EMAIL_RE.fullmatch(email))


def clean_password(password: str) -> str:
    password = password or ""
    if len(password) > 512:
        return ""
    return password


def hash_password(password: str) -> str:
    return PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash or not password:
        return False
    try:
        return PASSWORD_HASHER.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, ValueError, TypeError):
        return False


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def database_uri() -> str:
    raw = os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        return f"sqlite:///{BASE_DIR / 'instance' / 'movanta.sqlite3'}"
    if raw.startswith("postgres://"):
        raw = raw.replace("postgres://", "postgresql+psycopg://", 1)
    elif raw.startswith("postgresql://") and "+psycopg" not in raw:
        raw = raw.replace("postgresql://", "postgresql+psycopg://", 1)
    return raw


def sqlalchemy_engine_options(uri: str) -> dict[str, int | bool]:
    if not uri.startswith("postgresql"):
        return {}
    return {
        "pool_pre_ping": True,
        "pool_recycle": int(os.environ.get("DB_POOL_RECYCLE_SECONDS", "300")),
    }


def create_app() -> Flask:
    db_uri = database_uri()
    app = Flask(__name__, instance_path=str(BASE_DIR / "instance"))
    app.config.update(
        SQLALCHEMY_DATABASE_URI=db_uri,
        SQLALCHEMY_ENGINE_OPTIONS=sqlalchemy_engine_options(db_uri),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,
        JSON_SORT_KEYS=False,
    )
    app.secret_key = require_env("JWT_SECRET")
    db.init_app(app)

    with app.app_context():
        db.create_all()
        ensure_admin_user()

    register_security_hooks(app)
    register_error_handlers(app)
    register_routes(app)
    return app


def ensure_admin_user() -> None:
    admin_email = normalize_email(require_env("ADMIN_EMAIL"))
    admin_password = require_env("ADMIN_PASSWORD")
    user = AuthorizedUser.query.filter(func.lower(AuthorizedUser.email) == admin_email).first()
    password_hash = hash_password(admin_password)
    if user:
        user.is_admin = True
        user.is_active = True
        user.admin_password_hash = password_hash
    else:
        db.session.add(
            AuthorizedUser(
                email=admin_email,
                is_admin=True,
                is_active=True,
                admin_password_hash=password_hash,
            )
        )
    db.session.commit()


def otp_digest(email: str, otp: str) -> str:
    secret = require_env("JWT_SECRET").encode("utf-8")
    return hmac.new(secret, f"{email}:{otp}".encode("utf-8"), hashlib.sha256).hexdigest()


def session_token(user: AuthorizedUser) -> str:
    now = utcnow()
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "is_admin": bool(user.is_admin),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=SESSION_TTL_MINUTES)).timestamp()),
    }
    return jwt.encode(payload, require_env("JWT_SECRET"), algorithm="HS256")


def current_user() -> AuthorizedUser | None:
    token = request.cookies.get("movanta_session") or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not token:
        return None
    try:
        payload = jwt.decode(token, require_env("JWT_SECRET"), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    user = db.session.get(AuthorizedUser, int(payload.get("sub", "0")))
    if not user or not user.is_active:
        return None
    return user


def auth_required():
    user = current_user()
    if not user:
        return None, (jsonify({"error": "Authentication required"}), 401)
    return user, None


def admin_required():
    user, error = auth_required()
    if error:
        return None, error
    admin_email = normalize_email(require_env("ADMIN_EMAIL"))
    if not user.is_admin or normalize_email(user.email) != admin_email:
        return None, (jsonify({"error": "Admin access required"}), 403)
    return user, None


def send_otp_email(email: str, otp: str) -> None:
    subject = "Your Movanta login code"
    text_body = (
        f"Your Movanta one-time password is {otp}.\n\n"
        f"This code expires in {OTP_TTL_MINUTES} minutes."
    )
    html_body = f"""
        <div style="font-family:Arial,sans-serif;line-height:1.5">
          <h2>Movanta login code</h2>
          <p>Your one-time password is:</p>
          <p style="font-size:28px;font-weight:700;letter-spacing:6px">{otp}</p>
          <p>This code expires in {OTP_TTL_MINUTES} minutes.</p>
        </div>
    """
    provider = os.environ.get("EMAIL_PROVIDER", "auto").strip().lower()
    api_key = os.environ.get("EMAIL_SERVICE_API_KEY", "").strip()
    email_from = os.environ.get("EMAIL_FROM", "movantaa@outlook.com").strip()
    smtp_host = os.environ.get("SMTP_HOST", "").strip()
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_timeout = int(os.environ.get("SMTP_TIMEOUT_SECONDS", "8"))
    smtp_username = os.environ.get("SMTP_USERNAME", "").strip()
    smtp_password = os.environ.get("SMTP_PASSWORD", "").strip()
    allow_legacy_smtp = os.environ.get("ALLOW_LEGACY_SMTP", "false").lower() == "true"

    if provider in {"outlook_graph", "graph", "microsoft_graph"} and not outlook_graph_configured():
        raise RuntimeError("Outlook Graph is selected but OUTLOOK_GRAPH_CLIENT_ID and token credentials are not configured.")

    if provider in {"auto", "outlook_graph", "graph", "microsoft_graph"} and outlook_graph_configured():
        try:
            send_graph_email(email, subject, text_body, html_body, logger=current_app.logger)
            return
        except OutlookMailError:
            current_app.logger.exception("Outlook Graph OTP send failed")
            if provider in {"outlook_graph", "graph", "microsoft_graph"}:
                raise

    if provider in {"auto", "resend"} and api_key:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "from": email_from,
                "to": [email],
                "subject": subject,
                "html": html_body,
            },
            timeout=15,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(f"Resend email send failed: {response.status_code} {response.text}") from exc
        return

    if provider == "smtp" or (provider == "auto" and allow_legacy_smtp and smtp_host and smtp_username and smtp_password):
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = email_from
        message["To"] = email
        message.set_content(text_body)
        message.add_alternative(html_body, subtype="html")
        with smtplib.SMTP(smtp_host, smtp_port, timeout=smtp_timeout) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(smtp_username, smtp_password)
            smtp.send_message(message)
        return

    if os.environ.get("FLASK_ENV") != "production":
        print(f"[dev otp] {email}: {otp}", flush=True)
        return

    if smtp_host and smtp_username and smtp_password and not allow_legacy_smtp:
        raise RuntimeError("Outlook SMTP password auth is disabled. Configure Outlook Graph or set ALLOW_LEGACY_SMTP=true.")
    raise RuntimeError("Configure EMAIL_PROVIDER with Outlook Graph or Resend email settings.")


def otp_rate_limited(email: str) -> bool:
    return rate_limited(OTP_RATE_LIMIT, email, limit=3, window=timedelta(minutes=10))


def otp_verify_rate_limited(email: str) -> bool:
    key = f"{client_key()}:{email}"
    return rate_limited(OTP_VERIFY_RATE_LIMIT, key, limit=5, window=timedelta(minutes=10))


def admin_login_rate_limited(email: str) -> bool:
    key = f"{client_key()}:{email}"
    return rate_limited(ADMIN_LOGIN_RATE_LIMIT, key, limit=5, window=timedelta(minutes=15))


def global_rate_limited() -> bool:
    return rate_limited(GLOBAL_RATE_LIMIT, client_key(), limit=120, window=timedelta(minutes=1))


def rate_limited(bucket: dict[str, list[datetime]], key: str, *, limit: int, window: timedelta) -> bool:
    cutoff = utcnow() - window
    recent = [ts for ts in bucket.get(key, []) if ts > cutoff]
    bucket[key] = recent
    if len(recent) >= limit:
        return True
    recent.append(utcnow())
    return False


def client_key() -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.remote_addr or "unknown"


def set_session_cookie(response, token: str):
    secure_cookie = os.environ.get("COOKIE_SECURE", "true").lower() != "false"
    response.set_cookie(
        "movanta_session",
        token,
        max_age=SESSION_TTL_MINUTES * 60,
        httponly=True,
        secure=secure_cookie,
        samesite="Strict",
    )
    return response


def register_security_hooks(app: Flask) -> None:
    @app.before_request
    def global_auth_rate_limit():
        if request.path.startswith("/api/auth/") and global_rate_limited():
            return jsonify({"error": "Too many requests. Try again shortly."}), 429
        return None

    @app.before_request
    def same_origin_for_state_changes():
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return None
        origin = request.headers.get("Origin")
        if not origin:
            return None
        origin_host = urlparse(origin).netloc
        if origin_host and origin_host != request.host:
            return jsonify({"error": "Cross-origin request blocked"}), 403
        return None

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return response


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(SQLAlchemyError)
    def handle_database_error(exc: SQLAlchemyError):
        db.session.rollback()
        if isinstance(exc, OperationalError):
            db.engine.dispose()
        app.logger.exception("Database error")
        return jsonify({"error": "Database temporarily unavailable. Please try again."}), 503


def register_routes(app: Flask) -> None:
    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True})

    @app.post("/api/auth/request-otp")
    def request_otp():
        email = normalize_email((request.get_json(silent=True) or {}).get("email", ""))
        if not is_valid_email(email):
            return jsonify({"error": "Valid email is required"}), 400
        if email == normalize_email(require_env("ADMIN_EMAIL")):
            return jsonify({"error": "Admins must sign in with email and password"}), 400
        user = AuthorizedUser.query.filter(func.lower(AuthorizedUser.email) == email, AuthorizedUser.is_active.is_(True)).first()
        if not user:
            return jsonify({"error": "This email is not authorized"}), 403
        if user.is_admin:
            return jsonify({"error": "Admins must sign in with email and password"}), 400
        if otp_rate_limited(email):
            return jsonify({"error": "Too many OTP requests. Try again later."}), 429

        OtpChallenge.query.filter(func.lower(OtpChallenge.email) == email).delete()
        otp = f"{secrets.randbelow(900000) + 100000}"
        db.session.add(
            OtpChallenge(
                email=email,
                otp_hash=otp_digest(email, otp),
                expires_at=utcnow() + timedelta(minutes=OTP_TTL_MINUTES),
            )
        )
        db.session.commit()
        try:
            send_otp_email(email, otp)
        except Exception:
            app.logger.exception("Failed to send OTP email to %s", email)
            OtpChallenge.query.filter(func.lower(OtpChallenge.email) == email).delete()
            db.session.commit()
            return jsonify({"error": "Could not send OTP. Check email configuration and try again."}), 503
        return jsonify({"ok": True, "message": "OTP sent"})

    @app.post("/api/auth/verify-otp")
    def verify_otp():
        payload = request.get_json(silent=True) or {}
        email = normalize_email(payload.get("email", ""))
        otp = str(payload.get("otp", "")).strip()
        if not is_valid_email(email) or not re_fullmatch(r"\d{6}", otp):
            return jsonify({"error": "Valid email and 6-digit OTP are required"}), 400
        if otp_verify_rate_limited(email):
            return jsonify({"error": "Too many OTP verification attempts. Request a new code later."}), 429

        challenge = (
            OtpChallenge.query.filter(func.lower(OtpChallenge.email) == email)
            .order_by(OtpChallenge.created_at.desc())
            .first()
        )
        if not challenge or as_utc(challenge.expires_at) < utcnow():
            if challenge:
                db.session.delete(challenge)
                db.session.commit()
            return jsonify({"error": "OTP expired. Request a new code."}), 400

        otp_matches = hmac.compare_digest(challenge.otp_hash, otp_digest(email, otp))
        db.session.delete(challenge)
        if not otp_matches:
            db.session.commit()
            return jsonify({"error": "Invalid OTP"}), 400

        user = AuthorizedUser.query.filter(func.lower(AuthorizedUser.email) == email, AuthorizedUser.is_active.is_(True)).first()
        if not user or user.is_admin:
            db.session.commit()
            return jsonify({"error": "This email is not authorized"}), 403
        db.session.commit()

        response = make_response(jsonify({"ok": True, "user": public_user(user)}))
        return set_session_cookie(response, session_token(user))

    @app.post("/api/auth/admin-login")
    def admin_login():
        payload = request.get_json(silent=True) or {}
        email = normalize_email(payload.get("email", ""))
        password = clean_password(str(payload.get("password", "")))
        if not is_valid_email(email) or not password:
            return jsonify({"error": "Valid email and password are required"}), 400
        if email != normalize_email(require_env("ADMIN_EMAIL")):
            return jsonify({"error": "Invalid admin credentials"}), 401
        if admin_login_rate_limited(email):
            return jsonify({"error": "Too many admin login attempts. Try again later."}), 429

        user = AuthorizedUser.query.filter(
            func.lower(AuthorizedUser.email) == email,
            AuthorizedUser.is_admin.is_(True),
            AuthorizedUser.is_active.is_(True),
        ).first()
        if not user or not verify_password(user.admin_password_hash, password):
            return jsonify({"error": "Invalid admin credentials"}), 401

        response = make_response(jsonify({"ok": True, "user": public_user(user)}))
        return set_session_cookie(response, session_token(user))

    @app.post("/api/auth/logout")
    def logout():
        response = make_response(jsonify({"ok": True}))
        response.delete_cookie("movanta_session")
        return response

    @app.get("/api/me")
    def me():
        user, error = auth_required()
        if error:
            return error
        return jsonify({"user": public_user(user)})

    @app.get("/api/admin/users")
    def list_users():
        _, error = admin_required()
        if error:
            return error
        users = AuthorizedUser.query.order_by(AuthorizedUser.email.asc()).all()
        return jsonify({"users": [public_user(u) for u in users]})

    @app.post("/api/admin/users")
    def add_user():
        _, error = admin_required()
        if error:
            return error
        email = normalize_email((request.get_json(silent=True) or {}).get("email", ""))
        if not is_valid_email(email):
            return jsonify({"error": "Valid email is required"}), 400
        existing = AuthorizedUser.query.filter(func.lower(AuthorizedUser.email) == email).first()
        if existing:
            existing.is_active = True
            db.session.commit()
            return jsonify({"user": public_user(existing)})
        user = AuthorizedUser(email=email, is_admin=False, is_active=True)
        db.session.add(user)
        db.session.commit()
        return jsonify({"user": public_user(user)}), 201

    @app.delete("/api/admin/users/<int:user_id>")
    def delete_user(user_id: int):
        _, error = admin_required()
        if error:
            return error
        user = db.session.get(AuthorizedUser, user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404
        if normalize_email(user.email) == normalize_email(require_env("ADMIN_EMAIL")):
            return jsonify({"error": "The primary admin cannot be deleted"}), 400
        user.is_active = False
        db.session.commit()
        return jsonify({"ok": True})

    @app.post("/api/extract")
    def extract():
        _, error = auth_required()
        if error:
            return error
        files = request.files.getlist("files")
        if not files:
            return jsonify({"error": "Upload at least one PDF"}), 400

        temp_paths: list[Path] = []
        try:
            for file in files:
                filename = secure_filename(file.filename or "")
                if not filename.lower().endswith(".pdf"):
                    return jsonify({"error": f"{filename or 'file'} is not a PDF"}), 400
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
                file.save(tmp.name)
                tmp.close()
                temp_paths.append(Path(tmp.name))

            rows = export_booking_data(temp_paths)
            for row, source in zip(rows, files):
                if (source.filename or "").lower() == "latt trading.pdf":
                    row["Line"] = "LATT"
            return jsonify({"rows": rows})
        finally:
            for path in temp_paths:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass


def re_fullmatch(pattern: str, value: str) -> bool:
    import re

    return re.fullmatch(pattern, value or "") is not None


def public_user(user: AuthorizedUser) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "isAdmin": bool(user.is_admin),
        "isActive": bool(user.is_active),
        "createdAt": user.created_at.isoformat() if user.created_at else None,
    }


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "7823"))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_ENV") != "production")
