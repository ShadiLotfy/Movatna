"""Compatibility launcher for the Movanta Flask app.

Run:
    python server.py

For production use:
    gunicorn app:app --bind 0.0.0.0:$PORT
"""
from __future__ import annotations

import os

from app import app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "7823"))
    print("\n  Movanta Shipping Dashboard")
    print("  -------------------------------------")
    print(f"  App: http://localhost:{port}")
    print("\n  Press Ctrl+C to stop.\n")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
