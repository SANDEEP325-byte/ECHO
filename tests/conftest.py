"""Shared test fixtures and deterministic infrastructure for ECHO testing."""

from __future__ import annotations

import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from services.brain.brain import ECHOBrain
from services.coding.workspace import workspace_manager
from services.desktop.filesystem import FilesystemService
from services.desktop.policy import DesktopSecurityPolicy, desktop_security_policy
from services.memory.manager import MemoryManager
from services.security.pending_action_manager import PendingActionManager, pending_action_manager
from services.voice.audio_input import MockAudioInput
from services.voice.audio_output import MockAudioOutput
from services.voice.stt import MockSpeechRecognizer
from services.voice.tts import MockSpeechSynthesizer


@pytest.fixture
def isolated_workspace() -> Generator[Path, None, None]:
    """Provide an isolated temporary workspace directory and reset workspace_manager."""
    old_root = workspace_manager.root
    temp_dir = tempfile.TemporaryDirectory()
    workspace_path = Path(temp_dir.name).resolve()
    workspace_manager.set_root(workspace_path)
    desktop_security_policy.add_authorized_root(workspace_path)
    try:
        yield workspace_path
    finally:
        desktop_security_policy.remove_authorized_root(workspace_path)
        if old_root and old_root.exists():
            workspace_manager.set_root(old_root)
        else:
            workspace_manager.set_root(Path.cwd())
        temp_dir.cleanup()


@pytest.fixture
def clean_pending_actions() -> Generator[PendingActionManager, None, None]:
    """Provide an empty PendingActionManager, clearing state before and after each test."""
    pending_action_manager.clear()
    try:
        yield pending_action_manager
    finally:
        pending_action_manager.clear()


@pytest.fixture
def isolated_desktop_env(tmp_path: Path) -> dict[str, Any]:
    """Provide an isolated sandbox directory and DesktopSecurityPolicy."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir(exist_ok=True)

    workspace = sandbox / "workspace"
    workspace.mkdir(exist_ok=True)

    docs = sandbox / "docs"
    docs.mkdir(exist_ok=True)

    policy = DesktopSecurityPolicy(
        authorized_roots=[workspace, docs],
        include_default_roots=False,
    )
    service = FilesystemService(policy=policy)

    return {
        "sandbox": sandbox,
        "workspace": workspace,
        "docs": docs,
        "policy": policy,
        "service": service,
    }


class FakeAIGateway:
    """Deterministic, offline fake AI gateway."""

    def __init__(self, default_response: str = "This is a simulated AI response.") -> None:
        self.response = default_response
        self.last_messages: list[Any] | None = None
        self.last_tools: list[Any] | None = None
        self.call_count = 0

    async def generate(
        self,
        messages: list[Any],
        tool_result: Any = None,
        tools: list[Any] | None = None,
    ) -> str:
        self.last_messages = messages
        self.last_tools = tools
        self.call_count += 1
        return self.response


@pytest.fixture
def fake_gateway() -> FakeAIGateway:
    """Return a deterministic FakeAIGateway."""
    return FakeAIGateway()


@pytest.fixture
def mock_voice_harness() -> dict[str, Any]:
    """Provide deterministic mock voice components without physical hardware."""
    audio_in = MockAudioInput()
    audio_out = MockAudioOutput()
    stt = MockSpeechRecognizer()
    tts = MockSpeechSynthesizer()

    return {
        "audio_in": audio_in,
        "audio_out": audio_out,
        "stt": stt,
        "tts": tts,
    }


class MockBrowserPage:
    """Mock Playwright Page for offline browser testing."""

    def __init__(self, url: str = "about:blank") -> None:
        self.url = url
        self.closed = False
        self._content = "<html><body><h1>Example Domain</h1><p>Test content</p></body></html>"

    async def goto(self, url: str, **kwargs: Any) -> Any:
        self.url = url
        return None

    async def content(self) -> str:
        return self._content

    async def title(self) -> str:
        return "Example Title"

    async def inner_text(self, selector: str) -> str:
        return "Example Title Test content"

    async def click(self, selector: str, **kwargs: Any) -> None:
        pass

    async def fill(self, selector: str, text: str, **kwargs: Any) -> None:
        pass

    async def close(self) -> None:
        self.closed = True


class MockBrowserContext:
    """Mock Playwright BrowserContext for offline browser testing."""

    def __init__(self, page: MockBrowserPage | None = None) -> None:
        self.page = page or MockBrowserPage()
        self.closed = False

    async def new_page(self) -> MockBrowserPage:
        return self.page

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def mock_browser_env() -> dict[str, Any]:
    """Provide deterministic mock browser environment."""
    page = MockBrowserPage()
    context = MockBrowserContext(page=page)
    return {
        "page": page,
        "context": context,
    }


@pytest.fixture
def fresh_echo_brain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ECHOBrain:
    """Provide a fresh ECHOBrain instance with isolated memory directory."""
    from services.memory import database

    test_db = tmp_path / "test_memory.db"
    monkeypatch.setattr(database, "DB_PATH", test_db)
    database.initialize_database()

    mgr = MemoryManager()
    return ECHOBrain(memory_manager=mgr)
