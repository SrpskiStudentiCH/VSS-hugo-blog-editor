"""WSGI entrypoint for deployments whose Root Directory is the repo root.

Use with: gunicorn wsgi:app --bind 0.0.0.0:$PORT
(When Root Directory is set to `backend`, use `gunicorn app:app` instead.)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

from app import app  # noqa: E402,F401  (re-exported for gunicorn)
