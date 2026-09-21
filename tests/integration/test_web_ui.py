"""Integration tests for ECHO Phase 10C & 10D: Command Center UI & Avatar Foundation.

Verifies:
- Phase 10C.1: Live Gateway integration and event compatibility
- Phase 10C.2: Command Center UI static assets, HUD panels, and safe DOM rendering
- Phase 10C.3: UI state synchronization, dual confirmation (screen + voice), comm log export,
  reconnection resilience, and keyboard accessibility
- Phase 10D.1: Modular AvatarCore state controller, canvas reactor, and 60fps render loop
- Phase 10D.2: Voice presentation engine, speech synthesis vocalization, audio reactivity,
  and mute/unmute persistence
- Phase 10D.3: Modular avatar renderer architecture with pluggable BaseAvatarRenderer
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from services.api.main import WEB_DIR, app


def test_hud_static_mount_serves_html() -> None:
    """Verify /hud endpoint serves index.html with appropriate title and HUD elements."""
    with TestClient(app) as client:
        response = client.get("/hud/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        content = response.text
        assert "ECHO — Jarvis Command Center" in content
        assert "avatar-canvas" in content
        assert "confirmation-modal" in content
        assert "transcript-feed" in content
        assert "btn-voice-toggle" in content
        assert "btn-mute-toggle" in content
        assert "btn-export-log" in content
        assert "/hud/js/voice_presentation.js" in content
        assert 'aria-live="polite"' in content


def test_hud_static_assets_served() -> None:
    """Verify CSS and JavaScript assets are accessible under /hud."""
    with TestClient(app) as client:
        # CSS files
        resp_css = client.get("/hud/css/hud.css")
        assert resp_css.status_code == 200
        assert "hud-container" in resp_css.text
        assert "btn-telemetry-toggle" in resp_css.text

        resp_avatar_css = client.get("/hud/css/avatar.css")
        assert resp_avatar_css.status_code == 200
        assert "avatar-stage" in resp_avatar_css.text

        # JS files
        resp_avatar_js = client.get("/hud/js/avatar.js")
        assert resp_avatar_js.status_code == 200
        assert "class AvatarCore" in resp_avatar_js.text

        resp_voice_js = client.get("/hud/js/voice_presentation.js")
        assert resp_voice_js.status_code == 200
        assert "class VoicePresentationEngine" in resp_voice_js.text

        resp_gateway_js = client.get("/hud/js/gateway.js")
        assert resp_gateway_js.status_code == 200
        assert "class GatewayClient" in resp_gateway_js.text

        resp_app_js = client.get("/hud/js/app.js")
        assert resp_app_js.status_code == 200
        assert "DOMContentLoaded" in resp_app_js.text


def test_root_endpoint_content_negotiation() -> None:
    """Verify GET / returns HTML for browser navigation and JSON for API callers."""
    with TestClient(app) as client:
        # 1. API client request (JSON)
        resp_json = client.get("/", headers={"accept": "application/json"})
        assert resp_json.status_code == 200
        data = resp_json.json()
        assert data["status"] == "running"
        assert "name" in data

        # 2. Browser request (HTML)
        resp_html = client.get("/", headers={"accept": "text/html,application/xhtml+xml"})
        assert resp_html.status_code == 200
        assert "text/html" in resp_html.headers.get("content-type", "")
        assert "ECHO — Jarvis Command Center" in resp_html.text


def test_web_code_security_and_safe_dom_rendering() -> None:
    """Verify frontend code contains no secret leakage and uses safe DOM methods."""
    app_js = (WEB_DIR / "js" / "app.js").read_text(encoding="utf-8")
    index_html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    voice_js = (WEB_DIR / "js" / "voice_presentation.js").read_text(encoding="utf-8")

    # Verify no raw innerHTML assignment
    assert ".innerHTML" not in app_js, "app.js must not use innerHTML to prevent XSS"
    assert ".innerHTML" not in voice_js, "voice_presentation.js must not use innerHTML"

    # Verify safe DOM property usage
    assert ".textContent" in app_js
    assert "document.createElement" in app_js

    # Verify no API keys or internal filesystem secrets hardcoded
    assert "AIza" not in app_js
    assert "AIza" not in index_html
    assert "AIza" not in voice_js
    assert "gemini_api_key" not in app_js
    assert "gemini_api_key" not in index_html


def test_avatar_core_hooks_and_contracts() -> None:
    """Verify AvatarCore in avatar.js defines all required states and extensible hooks."""
    avatar_js = (WEB_DIR / "js" / "avatar.js").read_text(encoding="utf-8")

    # Canonical states supported
    for state in ["IDLE", "LISTENING", "THINKING", "SPEAKING", "ALERT", "ERROR", "CONFIRMATION"]:
        assert f"{state}:" in avatar_js or f"'{state.lower()}'" in avatar_js

    # Extensible hooks present
    assert "onStateChange" in avatar_js
    assert "onVisemeUpdate" in avatar_js
    assert "onExpressionUpdate" in avatar_js
    assert "onGestureTrigger" in avatar_js

    # Methods present
    assert "setState" in avatar_js
    assert "setViseme" in avatar_js
    assert "setExpression" in avatar_js
    assert "triggerGesture" in avatar_js
    assert "setAudioAmplitude" in avatar_js


def test_pluggable_avatar_renderer_architecture() -> None:
    """Verify Phase 10D.3: AvatarCore uses pluggable BaseAvatarRenderer architecture."""
    avatar_js = (WEB_DIR / "js" / "avatar.js").read_text(encoding="utf-8")

    # Base class exists and specifies the renderer interface
    assert "class BaseAvatarRenderer" in avatar_js
    assert "init()" in avatar_js
    assert "destroy()" in avatar_js
    assert "render(state, timestamp, metrics" in avatar_js

    # Default holographic renderer inherits from BaseAvatarRenderer
    assert "class HolographicCoreRenderer extends BaseAvatarRenderer" in avatar_js

    # AvatarCore supports hot-swapping renderers
    assert "setRenderer(newRenderer)" in avatar_js
    assert "getRenderer()" in avatar_js


def test_voice_presentation_engine_contract() -> None:
    """Verify Phase 10D.2: VoicePresentationEngine defines speech synthesis & reactivity."""
    voice_js = (WEB_DIR / "js" / "voice_presentation.js").read_text(encoding="utf-8")

    assert "class VoicePresentationEngine" in voice_js
    assert "speak(" in voice_js
    assert "sanitizeForSpeech(" in voice_js
    assert "setMuted(" in voice_js
    assert "toggleMute()" in voice_js
    assert "getMuted()" in voice_js
    assert "startAmplitudeSimulation()" in voice_js
    assert "stopAmplitudeSimulation()" in voice_js
    assert "echo_voice_muted" in voice_js, "Must persist mute status to localStorage"


def test_keyboard_accessibility_and_dual_confirmation() -> None:
    """Verify Phase 10C.3: Keyboard shortcuts and dual voice/screen confirmation flow."""
    app_js = (WEB_DIR / "js" / "app.js").read_text(encoding="utf-8")

    # Hotkeys defined
    assert "keydown" in app_js
    assert "Enter" in app_js
    assert "Escape" in app_js
    assert "handleConfirmAction()" in app_js
    assert "handleAbortAction()" in app_js

    # Voice confirmation trigger checks
    assert "authorize" in app_js
    assert "abort" in app_js


def test_reconnection_resilience_and_state_sync() -> None:
    """Verify Phase 10C.3: Gateway reconnection resilience and state synchronization."""
    gateway_js = (WEB_DIR / "js" / "gateway.js").read_text(encoding="utf-8")
    app_js = (WEB_DIR / "js" / "app.js").read_text(encoding="utf-8")

    # Gateway client provides queryState
    assert "queryState()" in gateway_js
    assert "state_query" in gateway_js

    # App.js triggers state query upon reconnect
    assert "gateway.queryState()" in app_js


def test_comm_log_export_logic() -> None:
    """Verify Phase 10C.3: Comm log export creates formatted text blob."""
    app_js = (WEB_DIR / "js" / "app.js").read_text(encoding="utf-8")

    assert "btnExportLog" in app_js
    assert "new Blob(" in app_js
    assert "echo-comm-log-" in app_js


def test_confirmation_modal_structure() -> None:
    """Verify confirmation modal elements match Phase 10C.1 & 10F.1 event schemas."""
    index_html = (WEB_DIR / "index.html").read_text(encoding="utf-8")

    assert 'id="confirmation-modal"' in index_html
    assert 'id="modal-action-id"' in index_html
    assert 'id="modal-tool-name"' in index_html
    assert 'id="modal-risk-level"' in index_html
    assert 'id="modal-description-text"' in index_html
    assert 'id="modal-params-content"' in index_html
    assert 'id="btn-confirm-action"' in index_html
    assert 'id="btn-abort-action"' in index_html
    # Phase 10F.1 enhancements
    assert 'id="modal-status-badge"' in index_html
    assert 'id="modal-timer-countdown"' in index_html
    assert 'id="modal-execution-notice"' in index_html
    assert "spinner-glyph" in index_html


def test_phase_10e_articulation_and_visemes() -> None:
    """Verify Phase 10E.2: Modular articulation & viseme foundation with canonical categories."""
    avatar_js = (WEB_DIR / "js" / "avatar.js").read_text(encoding="utf-8")

    # Canonical visual categories defined and handled
    for viseme in ["aa", "ee", "oh", "ch", "rest"]:
        assert f"'{viseme}'" in avatar_js or f'"{viseme}"' in avatar_js

    # setViseme and resetArticulation methods present across classes
    assert "setViseme(viseme, weight = 1.0)" in avatar_js
    assert "resetArticulation()" in avatar_js

    # BaseAvatarRenderer and HolographicCoreRenderer contracts
    assert "this.currentViseme = 'rest';" in avatar_js
    assert "apertureWidth" in avatar_js or "targetAperture" in avatar_js

    # Explicit technical limitation documented: estimated articulation, not real PCM audio
    assert "estimate" in avatar_js.lower() or "simulat" in avatar_js.lower()


def test_phase_10e_voice_presentation_lifecycle() -> None:
    """Verify Phase 10E.1: Explicit speech playback lifecycle and generation token protection."""
    voice_js = (WEB_DIR / "js" / "voice_presentation.js").read_text(encoding="utf-8")

    # Required states
    for state in ["START", "PLAYING", "PAUSED", "COMPLETED", "INTERRUPTED", "ERROR"]:
        assert f"{state}:" in voice_js

    # Lifecycle methods
    assert "pause()" in voice_js
    assert "resume()" in voice_js
    assert "stop(reason = 'stopped')" in voice_js
    assert "isSpeaking()" in voice_js
    assert "isPaused()" in voice_js

    # Lifecycle callbacks / hooks
    assert "onSpeechStart" in voice_js
    assert "onSpeechEnd" in voice_js
    assert "onSpeechPause" in voice_js
    assert "onSpeechResume" in voice_js
    assert "onSpeechInterrupted" in voice_js
    assert "onViseme" in voice_js

    # Generation token protection against delayed browser speech events
    assert "_generationToken" in voice_js

    # Explicit documentation of browser audio amplitude limitation
    assert "PCM" in voice_js or "amplitude" in voice_js


def test_phase_10e_speech_interruption_and_pacing() -> None:
    """Verify Phase 10E.3: Speech controls, PTT interruption, and Jarvis pacing."""
    voice_js = (WEB_DIR / "js" / "voice_presentation.js").read_text(encoding="utf-8")
    app_js = (WEB_DIR / "js" / "app.js").read_text(encoding="utf-8")

    # Jarvis-style pacing parameters
    assert "rate = 1.05" in voice_js or "1.05" in voice_js
    assert "pitch = 0.95" in voice_js or "0.95" in voice_js

    # Interruption on voice capture start
    assert "user_interrupted" in app_js
    # Interruption on user input submission
    assert "user_input" in app_js


def test_phase_10f_dual_voice_confirmation_and_duplicate_protection() -> None:
    """Verify Phase 10F.1: Dual confirmation vocabulary, countdown, and duplicate UI suppression."""
    app_js = (WEB_DIR / "js" / "app.js").read_text(encoding="utf-8")
    hud_css = (WEB_DIR / "css" / "hud.css").read_text(encoding="utf-8")

    # Vocabulary arrays
    for auth_word in ["authorize", "confirm", "proceed", "yes", "approve"]:
        assert auth_word in app_js
    for cancel_word in ["abort", "cancel", "deny", "no", "reject", "stop"]:
        assert cancel_word in app_js

    # Conservative classification function
    assert "classifyConfirmationIntent" in app_js

    # Expiration countdown derived from expires_at
    assert "expires_at" in app_js
    assert "actionExpiresAt" in app_js

    # Duplicate UI suppression: controls disabled on confirm/abort
    assert "actionExecutionLocked" in app_js
    assert "btnConfirmAction.disabled = true" in app_js
    assert "btnAbortAction.disabled = true" in app_js

    # Modal CSS styles
    assert ".tag-pending" in hud_css
    assert ".tag-executing" in hud_css
    assert ".tag-success" in hud_css
    assert ".tag-aborted" in hud_css
    assert ".tag-expired" in hud_css
    assert ".timer-countdown" in hud_css
    assert ".execution-notice" in hud_css
