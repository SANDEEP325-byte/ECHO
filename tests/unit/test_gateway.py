import pytest

from services.brain.gateway import AIGateway
from services.configuration.settings import settings
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


class FakeInteraction:
    def __init__(self, output_text: str = "Hello from Gemini.") -> None:
        self.output_text = output_text


class FakeInteractions:
    def __init__(
        self,
        response: FakeInteraction | None = None,
        should_raise: bool = False,
    ) -> None:
        self.response = response or FakeInteraction()
        self.should_raise = should_raise
        self.last_model: str | None = None
        self.last_input: str | None = None

    async def create(self, model: str, input: str) -> FakeInteraction:
        if self.should_raise:
            raise RuntimeError("Gemini API error")
        self.last_model = model
        self.last_input = input
        return self.response


class FakeAio:
    def __init__(self, interactions: FakeInteractions) -> None:
        self.interactions = interactions


class FakeGeminiClient:
    def __init__(self, interactions: FakeInteractions | None = None) -> None:
        self.interactions = interactions or FakeInteractions()
        self.aio = FakeAio(self.interactions)


# Ollama Provider Tests (Network-free & Deterministic)

@pytest.mark.anyio
async def test_gateway_uses_prompt_builder(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "ollama")
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
    monkeypatch.setattr(settings, "ai_provider", "ollama")
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
    monkeypatch.setattr(settings, "ai_provider", "ollama")
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
    monkeypatch.setattr(settings, "ai_provider", "ollama")
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
    monkeypatch.setattr(settings, "ai_provider", "ollama")
    gateway = AIGateway()

    class FailingAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def post(self, *args, **kwargs):
            raise RuntimeError("AI service unavailable.")

    monkeypatch.setattr(
        "services.brain.gateway.httpx.AsyncClient",
        lambda timeout: FailingAsyncClient(),
    )

    messages = [
        Message(role="user", content="Hello"),
    ]

    result = await gateway.generate(messages)

    assert result == "I couldn't reach the AI service right now."


# Gemini Provider Tests (Network-free & Deterministic)

@pytest.mark.anyio
async def test_gateway_generate_returns_gemini_response(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    fake_interactions = FakeInteractions(FakeInteraction("Hello from Gemini."))
    fake_client = FakeGeminiClient(fake_interactions)

    gateway = AIGateway()
    gateway._gemini_client = fake_client

    messages = [
        Message(role="user", content="Hello ECHO"),
    ]

    response = await gateway.generate(messages)

    assert response == "Hello from Gemini."
    assert fake_interactions.last_model == settings.gemini_model
    assert fake_interactions.last_input is not None


@pytest.mark.anyio
async def test_gateway_gemini_handles_api_exception(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    fake_interactions = FakeInteractions(should_raise=True)
    fake_client = FakeGeminiClient(fake_interactions)

    gateway = AIGateway()
    gateway._gemini_client = fake_client

    messages = [
        Message(role="user", content="Hello ECHO"),
    ]

    response = await gateway.generate(messages)

    assert response == "I couldn't reach the AI service right now."


@pytest.mark.anyio
async def test_gateway_gemini_missing_api_key_handles_exception(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "")

    gateway = AIGateway()
    messages = [
        Message(role="user", content="Hello ECHO"),
    ]

    response = await gateway.generate(messages)

    assert response == "I couldn't reach the AI service right now."


def test_gateway_get_gemini_client_lazy_initialization(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "fake-test-key")
    created_keys = []

    class MockGenaiClient:
        def __init__(self, api_key: str) -> None:
            created_keys.append(api_key)

    monkeypatch.setattr("services.brain.gateway.genai.Client", MockGenaiClient)

    gateway = AIGateway()
    client1 = gateway._get_gemini_client()

    assert isinstance(client1, MockGenaiClient)
    assert created_keys == ["fake-test-key"]

    # Subsequent access reuses cached client
    client2 = gateway._get_gemini_client()
    assert client2 is client1
    assert len(created_keys) == 1


def test_gateway_get_gemini_client_missing_key_raises(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "")
    gateway = AIGateway()

    with pytest.raises(RuntimeError, match="Gemini API key is not configured"):
        gateway._get_gemini_client()


# Provider Selection & Routing Tests

@pytest.mark.anyio
async def test_gateway_routes_to_ollama_provider(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "ollama")
    gateway = AIGateway()

    called = {}

    async def fake_ollama(prompt: str) -> str:
        called["ollama"] = prompt
        return "ollama response"

    async def fake_gemini(prompt: str) -> str:
        called["gemini"] = prompt
        return "gemini response"

    monkeypatch.setattr(gateway, "_generate_ollama", fake_ollama)
    monkeypatch.setattr(gateway, "_generate_gemini", fake_gemini)

    messages = [Message(role="user", content="Routing test")]
    result = await gateway.generate(messages)

    assert result == "ollama response"
    assert "ollama" in called
    assert "gemini" not in called


@pytest.mark.anyio
async def test_gateway_routes_to_gemini_provider(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    gateway = AIGateway()

    called = {}

    async def fake_ollama(prompt: str) -> str:
        called["ollama"] = prompt
        return "ollama response"

    async def fake_gemini(prompt: str) -> str:
        called["gemini"] = prompt
        return "gemini response"

    monkeypatch.setattr(gateway, "_generate_ollama", fake_ollama)
    monkeypatch.setattr(gateway, "_generate_gemini", fake_gemini)

    messages = [Message(role="user", content="Routing test")]
    result = await gateway.generate(messages)

    assert result == "gemini response"
    assert "gemini" in called
    assert "ollama" not in called