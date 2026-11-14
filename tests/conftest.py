import os
import sys
import tempfile
from pathlib import Path

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Use strictly isolated temporary test database
_test_db_dir = tempfile.mkdtemp(prefix="nova-test-suite-")
_test_db_file = Path(_test_db_dir) / "test-isolated.db"
os.environ["NOVA_DB_PATH"] = str(_test_db_file)
os.environ["NOVA_TEST_MODE"] = "1"

import pytest
from fastapi.testclient import TestClient

from app.database import init_db
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    init_db()
    yield
    try:
        if _test_db_file.exists():
            _test_db_file.unlink(missing_ok=True)
    except Exception:
        pass


@pytest.fixture
def client():
    return TestClient(app)
