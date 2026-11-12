"""Exercise browser-facing Nginx auth, query forwarding and WS upgrade paths."""

import os

import pytest
import requests

DASHBOARD = os.getenv("DASHBOARD_URL", "http://localhost:5173").rstrip("/")


@pytest.fixture(scope="module")
def dashboard_token():
    try:
        response = requests.post(
            DASHBOARD + "/auth/token",
            json={"client_id": "dashboard", "secret": "art-dev-secret"}, timeout=5,
        )
    except requests.RequestException as exc:
        if os.getenv("REQUIRE_LIVE_STACK") == "1":
            pytest.fail(f"Dashboard proxy unavailable: {exc}")
        pytest.skip("Dashboard proxy unavailable")
    assert response.status_code == 200, response.text
    return response.json()["token"]


def test_dashboard_auth_and_api_query_forwarding(dashboard_token):
    response = requests.get(
        DASHBOARD + "/api/v1/flights", params={"limit": 1},
        headers={"Authorization": f"Bearer {dashboard_token}"}, timeout=10,
    )
    assert response.status_code == 200, response.text
    page = response.json()
    assert "total" in page and len(page["flights"]) <= 1


def test_dashboard_websocket_upgrade(dashboard_token):
    with requests.get(
        DASHBOARD + "/ws", params={"token": dashboard_token},
        headers={
            "Connection": "Upgrade", "Upgrade": "websocket",
            "Sec-WebSocket-Key": "c3ludGhldGljLXRlc3QtMQ==",
            "Sec-WebSocket-Version": "13", "Origin": DASHBOARD,
        }, timeout=5, stream=True,
    ) as response:
        assert response.status_code == 101
        assert response.headers.get("Upgrade", "").lower() == "websocket"
