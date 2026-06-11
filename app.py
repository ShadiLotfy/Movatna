from __future__ import annotations

import os
import re
import secrets
import string
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from dotenv import load_dotenv
from flask import Flask, jsonify, make_response, render_template, request
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, inspect, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from werkzeug.utils import secure_filename

from booking_extractor import export_booking_data


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
SESSION_TTL_MINUTES = 30
MAX_CONTENT_LENGTH = 20 * 1024 * 1024
DEFAULT_UPLOAD_LIMIT = 25
GLOBAL_RATE_LIMIT: dict[str, list[datetime]] = {}
LOGIN_RATE_LIMIT: dict[str, list[datetime]] = {}
EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,254}$", re.IGNORECASE)
USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{3,64}$")
ROLE_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{1,31}$")
PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16)

db = SQLAlchemy()


class AuthorizedUser(db.Model):
    __tablename__ = "authorized_users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(120), nullable=False, default="")
    role = db.Column(db.String(32), nullable=False, default="user")
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    upload_limit = db.Column(db.Integer, default=DEFAULT_UPLOAD_LIMIT, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: utcnow(), nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: utcnow(), onupdate=lambda: utcnow(), nullable=False)
    password_changed_at = db.Column(db.DateTime(timezone=True), nullable=True)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())[:120]


def clean_role(role: str) -> str:
    role = (role or "user").strip().lower()
    return role if ROLE_RE.fullmatch(role) else ""


def is_valid_email(email: str) -> bool:
    return bool(email and len(email) <= 255 and EMAIL_RE.fullmatch(email))


def is_valid_username(username: str) -> bool:
    return bool(USERNAME_RE.fullmatch(username or ""))


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


def generate_password(length: int = 18) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.islower() for c in password)
            and any(c.isupper() for c in password)
            and any(c.isdigit() for c in password)
            and any(c in "!@#$%^&*()-_=+" for c in password)
        ):
            return password


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
        ensure_user_schema()
        ensure_admin_user()

    register_security_hooks(app)
    register_error_handlers(app)
    register_routes(app)
    return app


def ensure_user_schema() -> None:
    inspector = inspect(db.engine)
    columns = {column["name"] for column in inspector.get_columns("authorized_users")}
    dialect = db.engine.dialect.name

    def add_column(name: str, definition: str) -> None:
        if name not in columns:
            db.session.execute(text(f"ALTER TABLE authorized_users ADD COLUMN {name} {definition}"))

    if dialect == "postgresql":
        add_column("username", "VARCHAR(64)")
        add_column("full_name", "VARCHAR(120) DEFAULT ''")
        add_column("role", "VARCHAR(32) DEFAULT 'user'")
        add_column("is_deleted", "BOOLEAN DEFAULT FALSE")
        add_column("password_hash", "VARCHAR(255)")
        add_column("upload_limit", f"INTEGER DEFAULT {DEFAULT_UPLOAD_LIMIT}")
        add_column("updated_at", "TIMESTAMP WITH TIME ZONE")
        add_column("password_changed_at", "TIMESTAMP WITH TIME ZONE")
    else:
        add_column("username", "VARCHAR(64)")
        add_column("full_name", "VARCHAR(120) DEFAULT ''")
        add_column("role", "VARCHAR(32) DEFAULT 'user'")
        add_column("is_deleted", "BOOLEAN DEFAULT 0")
        add_column("password_hash", "VARCHAR(255)")
        add_column("upload_limit", f"INTEGER DEFAULT {DEFAULT_UPLOAD_LIMIT}")
        add_column("updated_at", "DATETIME")
        add_column("password_changed_at", "DATETIME")

    db.session.commit()
    now = utcnow()
    for user in AuthorizedUser.query.all():
        changed = False
        if not user.username:
            user.username = unique_username_from_email(user.email)
            changed = True
        if user.full_name is None:
            user.full_name = ""
            changed = True
        if not user.role:
            user.role = "admin" if user.is_admin else "user"
            changed = True
        if user.is_deleted is None:
            user.is_deleted = False
            changed = True
        if user.upload_limit is None:
            user.upload_limit = DEFAULT_UPLOAD_LIMIT
            changed = True
        if not user.updated_at:
            user.updated_at = now
            changed = True
        if not user.password_hash:
            user.password_hash = hash_password(generate_password())
            changed = True
        if user.is_admin and user.role != "admin":
            user.role = "admin"
            changed = True
        if changed:
            db.session.add(user)
    db.session.commit()


def unique_username_from_email(email: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9._-]+", "", (email or "user").split("@", 1)[0]).lower() or "user"
    base = base[:48]
    candidate = base
    suffix = 1
    while AuthorizedUser.query.filter(func.lower(AuthorizedUser.username) == candidate).first():
        suffix += 1
        candidate = f"{base[:48]}{suffix}"
    return candidate


def ensure_admin_user() -> None:
    admin_email = normalize_email(require_env("ADMIN_EMAIL"))
    admin_password = require_env("ADMIN_PASSWORD")
    user = AuthorizedUser.query.filter(func.lower(AuthorizedUser.email) == admin_email).first()
    password_hash = hash_password(admin_password)
    username = normalize_username(os.environ.get("ADMIN_USERNAME", "")) or unique_username_from_email(admin_email)
    if user:
        user.username = user.username or username
        user.full_name = user.full_name or "Movanta Admin"
        user.role = "admin"
        user.is_admin = True
        user.is_active = True
        user.is_deleted = False
        user.password_hash = password_hash
        user.upload_limit = max(user.upload_limit or DEFAULT_UPLOAD_LIMIT, DEFAULT_UPLOAD_LIMIT)
        user.updated_at = utcnow()
    else:
        db.session.add(
            AuthorizedUser(
                email=admin_email,
                username=username,
                full_name="Movanta Admin",
                role="admin",
                is_admin=True,
                is_active=True,
                is_deleted=False,
                password_hash=password_hash,
                upload_limit=DEFAULT_UPLOAD_LIMIT,
                password_changed_at=utcnow(),
            )
        )
    db.session.commit()


def session_token(user: AuthorizedUser) -> str:
    now = utcnow()
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "username": user.username,
        "role": user.role,
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
    if not user or not user.is_active or user.is_deleted:
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
    if not user.is_admin or user.role != "admin":
        return None, (jsonify({"error": "Admin access required"}), 403)
    return user, None


def login_rate_limited(identifier: str) -> bool:
    key = f"{client_key()}:{identifier}"
    return rate_limited(LOGIN_RATE_LIMIT, key, limit=5, window=timedelta(minutes=15))


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

    @app.post("/api/auth/login")
    def login():
        payload = request.get_json(silent=True) or {}
        identifier = normalize_username(str(payload.get("identifier", "")))
        password = clean_password(str(payload.get("password", "")))
        if not identifier or not password:
            return jsonify({"error": "Email/username and password are required"}), 400
        if login_rate_limited(identifier):
            return jsonify({"error": "Too many login attempts. Try again later."}), 429

        user = AuthorizedUser.query.filter(
            (func.lower(AuthorizedUser.email) == identifier) | (func.lower(AuthorizedUser.username) == identifier)
        ).first()
        if not user or user.is_deleted:
            return jsonify({"error": "Invalid credentials"}), 401
        if not user.is_active:
            return jsonify({"error": "This account is disabled"}), 403
        if not verify_password(user.password_hash, password):
            return jsonify({"error": "Invalid credentials"}), 401

        response = make_response(jsonify({"ok": True, "user": public_user(user)}))
        return set_session_cookie(response, session_token(user))

    @app.post("/api/auth/change-password")
    def change_password():
        user, error = auth_required()
        if error:
            return error
        payload = request.get_json(silent=True) or {}
        current_password = clean_password(str(payload.get("currentPassword", "")))
        new_password = clean_password(str(payload.get("newPassword", "")))
        if not verify_password(user.password_hash, current_password):
            return jsonify({"error": "Current password is incorrect"}), 401
        if not strong_password(new_password):
            return jsonify({"error": "New password must be at least 12 characters with upper, lower, number, and symbol"}), 400
        user.password_hash = hash_password(new_password)
        user.password_changed_at = utcnow()
        user.updated_at = utcnow()
        db.session.commit()
        return jsonify({"ok": True})

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
        users = AuthorizedUser.query.order_by(AuthorizedUser.created_at.desc(), AuthorizedUser.email.asc()).all()
        return jsonify({"users": [public_user(u) for u in users]})

    @app.post("/api/admin/users")
    def create_user():
        _, error = admin_required()
        if error:
            return error
        payload = request.get_json(silent=True) or {}
        full_name = clean_name(str(payload.get("name", "")))
        email = normalize_email(str(payload.get("email", "")))
        username = normalize_username(str(payload.get("username", ""))) or unique_username_from_email(email)
        role = clean_role(str(payload.get("role", "user")))
        upload_limit = parse_upload_limit(payload.get("uploadLimit", DEFAULT_UPLOAD_LIMIT))
        if not full_name:
            return jsonify({"error": "Name is required"}), 400
        if not is_valid_email(email):
            return jsonify({"error": "Valid email is required"}), 400
        if not is_valid_username(username):
            return jsonify({"error": "Username must be 3-64 characters using letters, numbers, dot, dash, or underscore"}), 400
        if not role:
            return jsonify({"error": "Valid role is required"}), 400
        if upload_limit is None:
            return jsonify({"error": "Upload limit must be a number from 1 to 500"}), 400
        existing_email = AuthorizedUser.query.filter(func.lower(AuthorizedUser.email) == email).first()
        if existing_email:
            return jsonify({"error": "Email already exists"}), 409
        existing_username = AuthorizedUser.query.filter(func.lower(AuthorizedUser.username) == username).first()
        if existing_username:
            return jsonify({"error": "Username already exists"}), 409

        generated_password = generate_password()
        user = AuthorizedUser(
            email=email,
            username=username,
            full_name=full_name,
            role=role,
            is_admin=role == "admin",
            is_active=True,
            is_deleted=False,
            password_hash=hash_password(generated_password),
            upload_limit=upload_limit,
            password_changed_at=None,
        )
        db.session.add(user)
        db.session.commit()
        return jsonify({"user": public_user(user), "generatedPassword": generated_password}), 201

    @app.patch("/api/admin/users/<int:user_id>")
    def update_user(user_id: int):
        _, error = admin_required()
        if error:
            return error
        user = db.session.get(AuthorizedUser, user_id)
        if not user or user.is_deleted:
            return jsonify({"error": "User not found"}), 404
        payload = request.get_json(silent=True) or {}

        if "name" in payload:
            full_name = clean_name(str(payload.get("name", "")))
            if not full_name:
                return jsonify({"error": "Name is required"}), 400
            user.full_name = full_name
        if "role" in payload and not is_primary_admin(user):
            role = clean_role(str(payload.get("role", "")))
            if not role:
                return jsonify({"error": "Valid role is required"}), 400
            user.role = role
            user.is_admin = role == "admin"
        if "uploadLimit" in payload:
            upload_limit = parse_upload_limit(payload.get("uploadLimit"))
            if upload_limit is None:
                return jsonify({"error": "Upload limit must be a number from 1 to 500"}), 400
            user.upload_limit = upload_limit
        if "isActive" in payload and not is_primary_admin(user):
            user.is_active = bool(payload.get("isActive"))

        user.updated_at = utcnow()
        db.session.commit()
        return jsonify({"user": public_user(user)})

    @app.post("/api/admin/users/<int:user_id>/reset-password")
    def reset_user_password(user_id: int):
        _, error = admin_required()
        if error:
            return error
        user = db.session.get(AuthorizedUser, user_id)
        if not user or user.is_deleted:
            return jsonify({"error": "User not found"}), 404
        generated_password = generate_password()
        user.password_hash = hash_password(generated_password)
        user.password_changed_at = utcnow()
        user.updated_at = utcnow()
        db.session.commit()
        return jsonify({"user": public_user(user), "generatedPassword": generated_password})

    @app.delete("/api/admin/users/<int:user_id>")
    def delete_user(user_id: int):
        _, error = admin_required()
        if error:
            return error
        user = db.session.get(AuthorizedUser, user_id)
        if not user or user.is_deleted:
            return jsonify({"error": "User not found"}), 404
        if is_primary_admin(user):
            return jsonify({"error": "The primary admin cannot be deleted"}), 400
        user.is_deleted = True
        user.is_active = False
        user.updated_at = utcnow()
        db.session.commit()
        return jsonify({"ok": True})

    @app.post("/api/extract")
    def extract():
        user, error = auth_required()
        if error:
            return error
        files = request.files.getlist("files")
        if not files:
            return jsonify({"error": "Upload at least one PDF"}), 400
        if not user.is_admin and len(files) > user.upload_limit:
            return jsonify({"error": f"Upload limit exceeded. You can upload up to {user.upload_limit} PDFs at once."}), 403

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


def strong_password(password: str) -> bool:
    return (
        len(password) >= 12
        and any(c.islower() for c in password)
        and any(c.isupper() for c in password)
        and any(c.isdigit() for c in password)
        and any(not c.isalnum() for c in password)
    )


def parse_upload_limit(value) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < 1 or parsed > 500:
        return None
    return parsed


def is_primary_admin(user: AuthorizedUser) -> bool:
    return normalize_email(user.email) == normalize_email(require_env("ADMIN_EMAIL"))


def public_user(user: AuthorizedUser) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "name": user.full_name,
        "role": user.role,
        "isAdmin": bool(user.is_admin),
        "isActive": bool(user.is_active),
        "isDeleted": bool(user.is_deleted),
        "uploadLimit": int(user.upload_limit or DEFAULT_UPLOAD_LIMIT),
        "createdAt": user.created_at.isoformat() if user.created_at else None,
        "updatedAt": user.updated_at.isoformat() if user.updated_at else None,
        "passwordChangedAt": user.password_changed_at.isoformat() if user.password_changed_at else None,
    }


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "7823"))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_ENV") != "production")
