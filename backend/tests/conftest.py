import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# Use a throwaway DB file for the whole test session (set before app import).
_tmpdir = tempfile.mkdtemp(prefix="civiclens-test-")
os.environ["CIVICLENS_DB_PATH"] = str(Path(_tmpdir) / "test.db")
os.environ["NIGHTLY_ENABLED"] = "false"  # no scheduler threads during tests

from fastapi.testclient import TestClient  # noqa: E402

from app.db.database import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services.kbo_import import run_import  # noqa: E402


@pytest.fixture(scope="session")
def imported():
    """Run the real snapshot import once for the whole test session."""
    init_db()
    db = SessionLocal()
    try:
        stats = run_import(db)
    finally:
        db.close()
    return stats


@pytest.fixture()
def db(imported):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(imported):
    with TestClient(app) as test_client:
        yield test_client
