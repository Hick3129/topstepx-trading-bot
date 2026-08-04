from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_read_root_returns_terminal_html():
    response = client.get("/")
    assert response.status_code == 200
    assert "TopstepX 程式交易戰情室 Terminal" in response.text

def test_health_api():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ONLINE"

def test_webhook_with_valid_oco_order():
    payload = {
        "ticker": "NQU4",
        "action": "BUY",
        "contracts": 1,
        "stop_loss": 19500.0,
        "take_profit": 19600.0
    }
    response = client.post("/api/v1/webhook", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "EXECUTED"
