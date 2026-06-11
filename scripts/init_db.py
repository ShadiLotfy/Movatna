from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import app, db, ensure_admin_user


def main() -> int:
    with app.app_context():
        db.create_all()
        ensure_admin_user()
    print("Movanta database initialized and admin account ensured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
