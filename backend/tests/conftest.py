"""
Pytest: set env before `api` is imported (SKIP_DB_INIT avoids real Postgres in unit tests).
"""
import os

os.environ.setdefault("SKIP_DB_INIT", "1")
os.environ.setdefault("FLASK_ENV", "testing")
# Must match the Origin value used in test_api_http.py
os.environ.setdefault("CORS_ORIGINS", "http://testclient.local")
os.environ.setdefault("PAYMENT_TEST_MODE", "true")
os.environ.setdefault("LOG_LEVEL", "WARNING")

import pytest
from api import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
