"""WSGI entry for gunicorn: gunicorn -w 4 -b 127.0.0.1:8000 wsgi:app"""
from app import app  # noqa: F401 — created by create_app() at import
