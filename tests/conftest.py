import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Use isolated test database
test_db_dir = tempfile.mkdtemp()
os.environ["NOVA_TEST_MODE"] = "1"

from app.database import init_db
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    init_db()
    yield

@pytest.fixture
def client():
    return TestClient(app)

