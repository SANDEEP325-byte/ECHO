import pytest

from services.brain.gateway import AIGateway
from services.memory.conversation import Message


class FakeResponse:
    def __init__(self, data=None, status_code=200):
        self._data = data or {"response": "Hello from ECHO."}
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP error")

    def json(self):
        return self._data


class FakeAsyncClient:
    def __init__(self, response=None):
        self.response = response or FakeResponse()
        self.post_called = False
        self.last_url = None
        self.last_json = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    async def post(self, url, json):
        self.post_called = True
        self.last_url = url
        self.last_json = json
        return self.response


def test_gateway_builds_prompt_with_messages():
    messages = [
        Message(
            role="system",
            content="User's name is Sandeep.",
        ),
        Message(
            role="user",
            content="Hello ECHO",
        ),
        Message(
            role="assistant",
            content="Hello! How can I help?",
        ),
    ]

    prompt = AIGateway._build_prompt(messages)

    assert "You are ECHO, a personal AI assistant." in prompt
    assert "User's name is Sandeep." in prompt
    assert "User: Hello ECHO" in prompt
    assert "ECHO: Hello! How can I help?" in prompt
    assert "Answer only the latest user message." in prompt


def test_gateway_builds_prompt_with_tool_result():
    messages = [
        Message(
            role="user",
            content="What is 25 * 4?",
        ),
    ]

    prompt = AIGateway._build_prompt(
        messages,
        tool_result="100",
    )

    assert "Tool result: 100" in prompt
    assert "Use this result as the factual answer." in prompt
    assert "Do not recalculate or change the tool result." in prompt

def test_gateway_builds_prompt_without_tool_result():
    messages = [
        Message(
            role="user",
            content="Hello ECHO",
        ),
    ]

    prompt = AIGateway._build_prompt(messages)

    assert "Tool result:" not in prompt


@pytest.mark.anyio
async def test_gateway_generate_returns_ollama_response(monkeypatch):
    gateway = AIGateway()

    fake_client = FakeAsyncClient(
        FakeResponse(
            {
                "response": "Hello from Ollama."
            }
        )
    )

    monkeypatch.setattr(
        "services.brain.gateway.httpx.AsyncClient",
        lambda timeout: fake_client,
    )

    messages = [
        Message(
            role="user",
            content="Hello ECHO",
        ),
    ]

    response = await gateway.generate(messages)

    assert response == "Hello from Ollama."
    assert fake_client.post_called
    assert fake_client.last_json["stream"] is False


@pytest.mark.anyio
async def test_gateway_generate_sends_tool_result(monkeypatch):
    gateway = AIGateway()

    fake_client = FakeAsyncClient(
        FakeResponse(
            {
                "response": "The result is 100."
            }
        )
    )

    monkeypatch.setattr(
        "services.brain.gateway.httpx.AsyncClient",
        lambda timeout: fake_client,
    )

    messages = [
        Message(
            role="user",
            content="What is 25 * 4?",
        ),
    ]

    response = await gateway.generate(
        messages,
        tool_result="100",
    )

    assert response == "The result is 100."

    assert "Tool result: 100" in fake_client.last_json["prompt"]


@pytest.mark.anyio
async def test_gateway_raises_http_error(monkeypatch):
    gateway = AIGateway()

    fake_client = FakeAsyncClient(
        FakeResponse(
            status_code=500,
        )
    )

    monkeypatch.setattr(
        "services.brain.gateway.httpx.AsyncClient",
        lambda timeout: fake_client,
    )

    messages = [
        Message(
            role="user",
            content="Hello ECHO",
        ),
    ]

    with pytest.raises(RuntimeError):
        await gateway.generate(messages)