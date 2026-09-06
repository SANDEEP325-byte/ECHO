import pytest
from fastapi.testclient import TestClient
from services.api.main import app

@pytest.mark.anyio
async def test_chat_handles_brain_exception(monkeypatch):
    async def fake_process(message):
        raise RuntimeError("Brain crashed.")

    monkeypatch.setattr(
        "services.api.main.echo_brain.process",
        fake_process,
    )

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={"message": "Hello"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "response": "I couldn't process your request because an internal component failed."
    }
