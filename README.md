# Movanta Shipping Dashboard

Production-ready Flask web app for admin-managed users, generated-password login, and PDF booking-confirmation extraction.

## Features

- No public registration.
- Admin creates users with name, email, username, role, and upload limit.
- Strong random passwords are generated automatically and shown once to the admin.
- Passwords are Argon2id hashed before storage. Plain passwords are never stored.
- Users log in with email or username plus password.
- Admins can disable, delete, edit upload limits, edit roles, and reset passwords.
- Users can change their own password.
- PDF upload and extraction through `booking_extractor.py`.
- SpaceX-inspired dark D-DIN style interface with a ship loading animation.

## Project Structure

```text
app.py                  Flask app, auth, admin APIs, PDF extraction API
booking_extractor.py    Carrier-specific PDF extraction engine
templates/index.html    Dashboard shell
static/app.js           Frontend API/UI logic
static/styles.css       SpaceX-inspired D-DIN theme
scripts/init_db.py      Admin/database bootstrap helper
requirements.txt
render.yaml
Procfile
.env.example
```

## Environment Variables

Copy `.env.example` to `.env` for local development. Never commit `.env`.

```env
ADMIN_EMAIL=admin@example.com
ADMIN_USERNAME=admin
ADMIN_PASSWORD=replace-with-a-long-random-admin-password
DATABASE_URL=sqlite:///instance/movanta.sqlite3
DB_POOL_RECYCLE_SECONDS=300
JWT_SECRET=replace-with-a-64-character-random-secret
COOKIE_SECURE=false
FLASK_ENV=development
PYTHON_ENV=development
TESSERACT_CMD=
```

Generate a strong JWT secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Local Development

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python scripts/init_db.py
python app.py
```

Open `http://localhost:7823`.

### OCR Setup

Movanta uses free local OCR only when normal PDF text extraction is empty or cannot satisfy required fields.

Python packages are installed from `requirements.txt`:

```text
PyMuPDF
pdfplumber
Pillow
pytesseract
```

Tesseract itself is a system executable and must also be installed:

- Windows: install Tesseract OCR, then set `TESSERACT_CMD` in `.env`, for example `C:\Program Files\Tesseract-OCR\tesseract.exe`.
- Linux/Render: `Aptfile` installs `tesseract-ocr`.

If Tesseract is missing, the extractor still tries selectable-text paths first, but scanned PDFs cannot OCR until the binary is available.

## User Management

1. Sign in with `ADMIN_EMAIL` or `ADMIN_USERNAME` and `ADMIN_PASSWORD`.
2. Open **Admin**.
3. Click **Create User**.
4. Enter name, email, optional username, role, and upload limit.
5. The app generates a strong password and shows it once.
6. Copy it immediately. It will not be shown again.

Admins can later reset a user's password. Resetting also shows the new generated password once.

## Authentication

Main endpoints:

```text
POST /api/auth/login
POST /api/auth/change-password
POST /api/auth/logout
GET  /api/me
```

Admin endpoints:

```text
GET    /api/admin/users
POST   /api/admin/users
PATCH  /api/admin/users/<id>
POST   /api/admin/users/<id>/reset-password
DELETE /api/admin/users/<id>
```

Extraction endpoint:

```text
POST /api/extract
```

## Security Notes

- Email-code delivery and mailbox polling are not used.
- Users must be created by an admin.
- Passwords are generated with Python `secrets` and include upper, lower, number, and symbol characters.
- Password hashes use Argon2id through `argon2-cffi`.
- Sessions are signed JWT cookies with 30-minute expiration, `HttpOnly`, `SameSite=Strict`, and configurable `Secure`.
- Login endpoints are rate-limited in-process.
- Admin-only APIs require an active user with role `admin`.
- State-changing requests are blocked when the `Origin` host does not match the request host.
- Security headers include `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, and `Permissions-Policy`.

## Database Schema

The app creates and upgrades the `authorized_users` table at startup.

Important columns:

```sql
email VARCHAR(255) UNIQUE NOT NULL
username VARCHAR(64) UNIQUE NOT NULL
full_name VARCHAR(120) NOT NULL
role VARCHAR(32) NOT NULL
is_admin BOOLEAN NOT NULL
is_active BOOLEAN NOT NULL
is_deleted BOOLEAN NOT NULL
password_hash VARCHAR(255) NOT NULL
upload_limit INTEGER NOT NULL
created_at TIMESTAMP NOT NULL
updated_at TIMESTAMP NOT NULL
password_changed_at TIMESTAMP
```

## Deploy to Render

1. Push this folder to GitHub.
2. Create a Render Web Service.
3. Use:

```text
Build command: pip install -r requirements.txt
Start command: gunicorn app:app --bind 0.0.0.0:$PORT
```

4. Render also reads `Aptfile` and installs `tesseract-ocr` for OCR fallback.
5. Set environment variables:

```env
ADMIN_EMAIL=
ADMIN_USERNAME=admin
ADMIN_PASSWORD=
DATABASE_URL=
DB_POOL_RECYCLE_SECONDS=300
JWT_SECRET=
COOKIE_SECURE=true
FLASK_ENV=production
PYTHON_ENV=production
TESSERACT_CMD=
```

## Testing

```bash
python -m py_compile app.py booking_extractor.py server.py scripts/init_db.py
python -m unittest discover -s tests -v
node --check static/app.js
```
