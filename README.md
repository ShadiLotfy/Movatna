# Movanta Shipping Dashboard

Production-ready Flask web app for secure OTP login, admin-managed authorized users, and PDF booking-confirmation extraction.

## Features

- No public registration.
- Email OTP login for pre-authorized users.
- Admin console gated to `ADMIN_EMAIL`.
- Add/revoke authorized user emails.
- PDF upload and extraction through the Python `booking_extractor.py` backend.
- Exact output schema:
  - Line
  - Booking No.
  - Equipment
  - Vessel Name
  - Voyage No.
  - Port of Loading
  - Port of Discharge
  - Final Dest.
  - ETS POL / Sailing Date
  - ETA POD / Arrival Date
  - SI & VGM Cut Off (Calculated)
  - Assigning Cut Off (Calculated)
  - Gate In Cut Off (Calculated)

## Project Structure

```text
.
├── app.py                  # Flask app, auth, admin APIs, PDF extraction API
├── booking_extractor.py    # Carrier-specific PDF extraction engine
├── templates/
│   └── index.html          # Tailwind dashboard shell
├── static/
│   ├── app.js              # Frontend API/UI logic
│   └── styles.css          # Small app styles
├── scripts/
│   └── init_db.py          # Admin/database bootstrap helper
├── requirements.txt
├── render.yaml
├── Procfile
├── .env.example
└── .gitignore
```

## Environment Variables

Copy `.env.example` to `.env` for local development. Never commit `.env`.

```bash
ADMIN_EMAIL=your-admin-email@example.com
ADMIN_PASSWORD=long-random-admin-bootstrap-secret
DATABASE_URL=sqlite:///instance/movanta.sqlite3
EMAIL_PROVIDER=outlook_graph
EMAIL_SERVICE_API_KEY=
EMAIL_FROM=movantaa@outlook.com
OUTLOOK_GRAPH_TENANT_ID=consumers
OUTLOOK_GRAPH_CLIENT_ID=
OUTLOOK_GRAPH_CLIENT_SECRET=
OUTLOOK_GRAPH_REFRESH_TOKEN=
OUTLOOK_GRAPH_SCOPES=offline_access https://graph.microsoft.com/Mail.Send https://graph.microsoft.com/Mail.Read
OUTLOOK_GRAPH_MAILBOX=movantaa@outlook.com
OUTLOOK_GRAPH_TIMEOUT_SECONDS=10
OUTLOOK_GRAPH_RETRIES=3
OUTLOOK_GRAPH_FOLDER=inbox
OUTLOOK_GRAPH_POLL_SECONDS=30
OUTLOOK_GRAPH_POLL_INTERVAL_SECONDS=5
SMTP_HOST=smtp-mail.outlook.com
SMTP_PORT=587
SMTP_TIMEOUT_SECONDS=8
SMTP_USERNAME=movantaa@outlook.com
SMTP_PASSWORD=outlook-app-password-or-smtp-password
ALLOW_LEGACY_SMTP=false
JWT_SECRET=64-character-random-secret
COOKIE_SECURE=false
FLASK_ENV=development
PYTHON_ENV=development
```

For your deployment, set `ADMIN_EMAIL` to the real admin email in the hosting provider environment settings. Do not hardcode it in code.

Generate a strong JWT secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Local Development

1. Create and activate a virtual environment.

```bash
python -m venv .venv
.venv\Scripts\activate
```

2. Install dependencies.

```bash
pip install -r requirements.txt
```

3. Create `.env`.

```bash
copy .env.example .env
```

4. Set real values in `.env`.

5. Initialize the database.

```bash
python scripts/init_db.py
```

6. Run the app.

```bash
python app.py
```

Open `http://localhost:7823`.

In development, if no email provider is configured, OTP codes are printed in the terminal. In production, set `EMAIL_PROVIDER=outlook_graph` with Microsoft Graph credentials, or use a verified Resend sender.

## Email Sending

The app can send OTPs through Microsoft Graph, Resend, or explicitly enabled legacy SMTP.

### Option A: Outlook Microsoft Graph

Use `movantaa@outlook.com` as the sender:

```env
EMAIL_PROVIDER=outlook_graph
EMAIL_FROM=movantaa@outlook.com
OUTLOOK_GRAPH_TENANT_ID=consumers
OUTLOOK_GRAPH_CLIENT_ID=your-microsoft-app-client-id
OUTLOOK_GRAPH_CLIENT_SECRET=your-microsoft-app-client-secret-if-confidential-client
OUTLOOK_GRAPH_REFRESH_TOKEN=your-delegated-refresh-token
OUTLOOK_GRAPH_SCOPES=offline_access https://graph.microsoft.com/Mail.Send https://graph.microsoft.com/Mail.Read
OUTLOOK_GRAPH_MAILBOX=movantaa@outlook.com
OUTLOOK_GRAPH_TIMEOUT_SECONDS=10
OUTLOOK_GRAPH_RETRIES=3
```

The Microsoft app must have delegated `Mail.Send`. Add delegated `Mail.Read` only if you use mailbox polling. Request `offline_access` when obtaining the refresh token so the server can refresh tokens without an interactive login.

To test Outlook OTP extraction locally without network:

```bash
python scripts/test_outlook_otp.py --samples
```

To send a test OTP through Outlook Graph:

```bash
python scripts/test_outlook_otp.py --send user@example.com
```

To poll the Outlook mailbox for the newest OTP email:

```bash
python scripts/test_outlook_otp.py --poll --timeout 30
```

### Option B: Legacy Outlook SMTP

SMTP password authentication is disabled by default because it was timing out on Render. Outlook.com mail apps require Modern Auth/OAuth2, so Microsoft Graph is the production path. Only enable SMTP if your host can reach Microsoft SMTP and you explicitly want the legacy fallback:

```env
EMAIL_PROVIDER=smtp
EMAIL_FROM=movantaa@outlook.com
SMTP_HOST=smtp-mail.outlook.com
SMTP_PORT=587
SMTP_TIMEOUT_SECONDS=8
SMTP_USERNAME=movantaa@outlook.com
SMTP_PASSWORD=your-outlook-app-password
ALLOW_LEGACY_SMTP=true
```

Do not commit this password.

### Option C: Resend API

1. Create a free account at [resend.com](https://resend.com).
2. Create an API key.
3. Set `EMAIL_PROVIDER=resend`.
4. Set `EMAIL_SERVICE_API_KEY` to that key. Replace `re_xxxxxxxxx` with your real Resend API key.
5. Set `EMAIL_FROM` to a verified sender. For a first test, use `onboarding@resend.dev`.

To test Resend locally:

```bash
python scripts/test_resend.py
```

If no email provider is configured in local development, OTPs are printed to the terminal/log file.

## Free Database Options

For local development, SQLite works through:

```text
DATABASE_URL=sqlite:///instance/movanta.sqlite3
```

For production free tiers, use a hosted Postgres database:

- [Supabase free tier](https://supabase.com)
- [Neon free tier](https://neon.tech)

Use the provider connection string as `DATABASE_URL`. The app supports both `postgres://...` and `postgresql://...` URLs.

## Deploy to Render Free Tier

Render is the simplest free option for this project because it runs Python and the PDF extraction backend in one service.

1. Push this folder to a GitHub repository.
2. Create a free Render account at [render.com](https://render.com).
3. Click **New +** then **Web Service**.
4. Connect your GitHub repo.
5. Use these settings:
   - Runtime: Python
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app:app --bind 0.0.0.0:$PORT`
   - Plan: Free
6. Add environment variables:
   - `ADMIN_EMAIL`
   - `ADMIN_PASSWORD`
   - `DATABASE_URL`
   - `EMAIL_PROVIDER`
   - `EMAIL_SERVICE_API_KEY`
   - `EMAIL_FROM`
   - `OUTLOOK_GRAPH_TENANT_ID`
   - `OUTLOOK_GRAPH_CLIENT_ID`
   - `OUTLOOK_GRAPH_CLIENT_SECRET`
   - `OUTLOOK_GRAPH_REFRESH_TOKEN`
   - `OUTLOOK_GRAPH_MAILBOX`
   - `SMTP_HOST`
   - `SMTP_PORT`
   - `SMTP_TIMEOUT_SECONDS`
   - `SMTP_USERNAME`
   - `SMTP_PASSWORD`
   - `ALLOW_LEGACY_SMTP`
   - `JWT_SECRET`
   - `COOKIE_SECURE=true`
   - `FLASK_ENV=production`
   - `PYTHON_ENV=production`
7. Deploy.

Render gives you a free subdomain like:

```text
https://movanta.onrender.com
```

No credit card is normally required for the free web service path, but provider policies can change. If Render asks for billing details, use another free host that supports Python web services or deploy through a student/open-source plan.

## Free Domain / Subdomain Options

The easiest free option is to use the hosting provider subdomain:

- Render: `your-app.onrender.com`
- Vercel: `your-app.vercel.app`
- Netlify: `your-app.netlify.app`
- GitHub Pages: `username.github.io`

For a custom free domain, look for reputable free-domain/community providers or use a free DNS/subdomain service. Avoid providers that require suspicious browser extensions, forced ads, or account sharing.

## Vercel / Netlify Note

Vercel and Netlify are excellent for static frontends and JavaScript serverless functions, but this app uses Python PDF extraction. Deploying the whole app to Render is simpler and more reliable on free tiers.

A split deployment is possible:

- Frontend on Vercel or Netlify.
- Python API on Render.
- Configure CORS and point frontend API calls to the Render URL.

The included app is intentionally single-service to reduce deployment moving parts.

## Security Notes

- No registration route exists.
- Users must already exist in the database.
- Admin authentication uses `ADMIN_EMAIL` plus `ADMIN_PASSWORD` only. Admin OTP login is disabled.
- Admin passwords are stored with Argon2id hashes. Rotate `ADMIN_PASSWORD` in the hosting environment to rotate the admin password on the next app boot.
- User authentication uses cryptographically random 6-digit OTPs.
- OTPs are HMAC-SHA256 hashed before storage, expire after 5 minutes, and are deleted immediately after one verification attempt whether the attempt succeeds or fails.
- OTP request and verification endpoints are rate-limited. The included limiter is process-local; use Redis-backed limits before running multiple web instances.
- Sessions are signed JWT cookies with 30-minute expiration, `HttpOnly`, `SameSite=Strict`, and configurable `Secure`.
- Admin-only APIs require the session user to match `ADMIN_EMAIL`.
- Auth endpoints have a global per-client rate limit to reduce brute-force and DoS pressure.
- State-changing requests are blocked when the `Origin` host does not match the request host.
- Security headers include `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, and `Permissions-Policy`.

## Database Schema

The app creates these tables automatically through SQLAlchemy. For production, use managed PostgreSQL instead of SQLite.

```sql
CREATE TABLE authorized_users (
  id SERIAL PRIMARY KEY,
  email VARCHAR(255) UNIQUE NOT NULL,
  is_admin BOOLEAN NOT NULL DEFAULT FALSE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  admin_password_hash VARCHAR(255),
  created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX ix_authorized_users_email ON authorized_users (email);

CREATE TABLE otp_challenges (
  id SERIAL PRIMARY KEY,
  email VARCHAR(255) NOT NULL,
  otp_hash VARCHAR(128) NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX ix_otp_challenges_email ON otp_challenges (email);
```

## Production Deployment Checklist

1. Create a managed PostgreSQL database through Render, Neon, Supabase, AWS RDS, or DigitalOcean Managed Databases.
2. Set `DATABASE_URL` to the provider connection string. The app accepts `postgres://`, `postgresql://`, and `postgresql+psycopg://` formats.
3. Configure Outlook Graph or Resend. In production, do not rely on console OTP output.
4. Generate `JWT_SECRET` with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
5. Set `ADMIN_EMAIL` to the exact administrator account and set a long random `ADMIN_PASSWORD`.
6. Set `COOKIE_SECURE=true`, `FLASK_ENV=production`, and `PYTHON_ENV=production`.
7. Terminate HTTPS at the cloud platform load balancer or reverse proxy. Render-managed domains and custom domains receive automatic TLS certificates after DNS verification.
8. If using your own reverse proxy, redirect HTTP to HTTPS and proxy to Gunicorn over an internal network only.
9. Run one web instance with the included limiter, or replace the in-memory rate-limit dictionaries with Redis before horizontal scaling.
10. After first deploy, open `/api/health`, then sign in through the Admin tab and add authorized user emails.
- Uploaded PDFs are stored only in temporary files and deleted after extraction.
- `.env`, databases, caches, and dependencies are excluded by `.gitignore`.

## API Summary

```text
POST /api/auth/request-otp
POST /api/auth/verify-otp
POST /api/auth/logout
GET  /api/me
GET  /api/admin/users
POST /api/admin/users
DELETE /api/admin/users/<id>
POST /api/extract
```

## PDF Extraction CLI

You can still run extraction directly:

```bash
python booking_extractor.py 11.pdf MSC.pdf
```

Or use the Python API:

```python
from booking_extractor import export_booking_data

rows = export_booking_data(["11.pdf", "MSC.pdf"])
df = export_booking_data(["11.pdf", "MSC.pdf"], as_dataframe=True)
```
