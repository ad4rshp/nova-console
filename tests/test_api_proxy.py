import pytest
from app.services.modelfile import update_modelfile, read_modelfile

def test_dashboard_api_endpoint(client):
    """Ensure /api/dashboard returns structured state without crashing."""
    res = client.get("/api/dashboard")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data
    assert "ram" in data
    assert "gpu" in data
    assert "models" in data

def test_terminal_propose_and_execute_flow(client):
    """Ensure proposing generates a token and executing with that token succeeds."""
    propose_res = client.post("/api/terminal/propose", json={"command": "python --version"})
    assert propose_res.status_code == 200
    pdata = propose_res.json()
    token = pdata.get("approval_token")
    assert token

    # Execute with valid token
    exec_res = client.post("/api/terminal/execute", json={
        "command": "python --version",
        "approval_token": token,
        "approved": True
    })
    assert exec_res.status_code == 200
    edata = exec_res.json()
    assert edata["ok"] is True
    assert edata["return_code"] == 0

    # Replaying the same token must be rejected with 403
    replay_res = client.post("/api/terminal/execute", json={
        "command": "python --version",
        "approval_token": token,
        "approved": True
    })
    assert replay_res.status_code == 403

def test_modelfile_bounds_validation(client):
    """Ensure parameter bounds are enforced and reject out-of-range values."""
    # num_ctx limit is (1024, 65536)
    bad_res = client.post("/api/modelfile", json={"num_ctx": 9999999})
    assert bad_res.status_code == 400
    assert "outside safe limits" in bad_res.json()["error"]

    # Valid values should succeed
    good_res = client.post("/api/modelfile", json={"num_ctx": 4096, "temperature": 0.4})
    assert good_res.status_code == 200
    assert good_res.json()["parameters"]["num_ctx"] == "4096"
