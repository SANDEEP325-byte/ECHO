import pytest

from services.brain.gateway import AIGateway
from services.memory.conversation import Message
from services.brain.prompt_builder import prompt_builder

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


@pytest.mark.anyio
async def test_gateway_uses_prompt_builder(monkeypatch):
    gateway = AIGateway()

    messages = [
        Message(
            role="user",
            content="Hello ECHO",
        ),
    ]

    expected_prompt = "BUILT PROMPT"

    def fake_build(
        messages,
        tool_result=None,
        tools=None,
    ):
        assert messages[0].content == "Hello ECHO"
        assert tool_result is None
        assert tools is None

        return expected_prompt

    monkeypatch.setattr(
        prompt_builder,
        "build",
        fake_build,
    )

    fake_client = FakeAsyncClient()

    monkeypatch.setattr(
        "services.brain.gateway.httpx.AsyncClient",
        lambda timeout: fake_client,
    )

    response = await gateway.generate(messages)

    assert response == "Hello from ECHO."
    assert fake_client.last_json["prompt"] == expected_prompt

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
        
@pytest.mark.anyio
async def test_gateway_handles_client_exception(monkeypatch):
    gateway = AIGateway()

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def post(self, *args, **kwargs):
            raise RuntimeError("AI service unavailable.")

    monkeypatch.setattr(
        "services.brain.gateway.httpx.AsyncClient",
        lambda timeout: FakeAsyncClient(),
    )

    messages = [
        Message(role="user", content="Hello"),
    ]

    result = await gateway.generate(messages)

    assert result == "I couldn't reach the AI service right now."