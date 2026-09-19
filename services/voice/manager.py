"""Voice Manager (Phase 6A + 6B).

Orchestrates audio capture, silence detection, Speech-to-Text inference,
and ingestion into the ECHO Brain.

Architectural and Security Rules:
- Voice acts strictly as an input boundary adapter.
- Never directly invokes ToolRouter, ExecutionEngine, desktop tools, or browser tools.
- All transcribed input is dispatched via Request(source="voice") into ECHOBrain.process().
- Destructive commands strictly preserve existing SafetyEngine CONFIRM boundaries.
- Zero audio persistence to disk; zero temporary files; zero raw audio in logs or errors.
- Audio buffers are held in memory only for the minimum duration needed for inference,
  then released immediately.
"""

import asyncio
import time
from typing import Any

from packages.interfaces.pending_action import ConfirmationResult
from packages.interfaces.request import Request
from packages.interfaces.voice import (
    AudioInput,
    AudioOutput,
    BaseVAD,
    SpeechRecognizer,
    SpeechSynthesizer,
    VoiceProcessResult,
    VoiceSessionState,
    WakeDetector,
)
from services.logging.logger import logger  # type: ignore[attr-defined]
from services.voice.audio_input import MockAudioInput
from services.voice.audio_output import MockAudioOutput
from services.voice.confirmation import ConfirmationIntent, VoiceConfirmationValidator
from services.voice.errors import (
    AudioInputError,
    AudioOutputError,
    ModelUnavailableError,
    RecognitionError,
    SynthesisError,
    WakeDetectionError,
)
from services.voice.session import VoiceSessionController
from services.voice.stt import MockSpeechRecognizer
from services.voice.tts import MockSpeechSynthesizer
from services.voice.vad import EnergyVAD


class VoiceManager:
    """Central manager for ECHO voice capture, Brain cognitive ingestion, and TTS response."""

    def __init__(
        self,
        audio_input: AudioInput | None = None,
        speech_recognizer: SpeechRecognizer | None = None,
        vad: BaseVAD | None = None,
        audio_output: AudioOutput | None = None,
        speech_synthesizer: SpeechSynthesizer | None = None,
        wake_detector: WakeDetector | None = None,
        brain: Any | None = None,
    ) -> None:
        self.audio_input: AudioInput = audio_input or MockAudioInput()
        self.speech_recognizer: SpeechRecognizer = speech_recognizer or MockSpeechRecognizer()
        self.vad: BaseVAD = vad or EnergyVAD()
        self.audio_output: AudioOutput = audio_output or MockAudioOutput()
        self.speech_synthesizer: SpeechSynthesizer = speech_synthesizer or MockSpeechSynthesizer()
        self.wake_detector: WakeDetector | None = wake_detector
        self._brain = brain

    @property
    def brain(self) -> Any:
        """Lazily retrieve ECHOBrain singleton if not explicitly injected."""
        if self._brain is None:
            from services.brain.brain import ECHOBrain

            self._brain = ECHOBrain()
        return self._brain

    async def process_audio_bytes(
        self,
        audio_bytes: bytes,
        session_id: str | None = None,
    ) -> VoiceProcessResult:
        """Process pre-buffered in-memory audio bytes through STT and Brain execution.

        Guarantees:
        - Audio is never saved to disk or temporary files.
        - In-memory reference is dropped immediately after transcription.
        - Dispatches Request(source="voice") into ECHOBrain.process().
        """
        controller = VoiceSessionController(session_id=session_id)
        start_time = time.time()

        try:
            controller.start_listening()
            controller.start_processing()

            if not audio_bytes:
                controller.complete(transcription="")
                return VoiceProcessResult(
                    success=True,
                    session_id=controller.session_id,
                    transcription="",
                    brain_response="No speech detected.",
                    duration_seconds=time.time() - start_time,
                    state=VoiceSessionState.COMPLETED,
                )

            # 1. Transcribe audio
            logger.info(
                "Transcribing audio payload (%d bytes) for session %s...",
                len(audio_bytes),
                controller.session_id,
            )
            recognition = self.speech_recognizer.transcribe(audio_bytes)

            # 2. Release raw audio reference immediately to enforce minimum in-memory lifetime
            del audio_bytes

            if recognition.is_empty or not recognition.text.strip():
                controller.complete(transcription="")
                return VoiceProcessResult(
                    success=True,
                    session_id=controller.session_id,
                    transcription="",
                    brain_response="Could not understand audio.",
                    duration_seconds=time.time() - start_time,
                    state=VoiceSessionState.COMPLETED,
                )

            transcription_text = recognition.text.strip()
            logger.info(
                "Voice transcription received for session %s: '%s'",
                controller.session_id,
                transcription_text,
            )

            # 3. Ingest into ECHOBrain as a canonical Request with source="voice"
            # VoiceManager NEVER calls tools directly. It enters the standard cognitive cycle:
            # Think -> Remember -> Plan -> Act -> Verify
            req = Request(
                user_input=transcription_text,
                source="voice",
                session_id=controller.session_id,
            )

            brain_resp = await self.brain.process(req)

            # Check if this request requires confirmation
            requires_confirm = bool(
                req.context.get("requires_confirmation")
                or (
                    hasattr(req, "result")
                    and req.result
                    and getattr(req.result, "requires_confirmation", False)
                )
            )
            pending_action_id = req.context.get("pending_action_id")
            if not pending_action_id and hasattr(req, "result") and req.result:
                pending_act = getattr(req.result, "pending_action", None)
                if isinstance(pending_act, dict):
                    pending_action_id = pending_act.get("action_id")

            if requires_confirm and pending_action_id:
                # Format safe human-readable confirmation prompt without raw arguments
                pending_act = (
                    getattr(req.result, "pending_action", None) if hasattr(req, "result") else None
                )
                tool_name = pending_act.get("tool", "") if isinstance(pending_act, dict) else ""
                args = pending_act.get("arguments", {}) if isinstance(pending_act, dict) else {}
                safe_prompt = VoiceConfirmationValidator.format_safe_prompt(tool_name, args)

                controller.request_confirmation(pending_action_id)
                return VoiceProcessResult(
                    success=True,
                    session_id=controller.session_id,
                    transcription=transcription_text,
                    brain_response=brain_resp,
                    duration_seconds=time.time() - start_time,
                    state=VoiceSessionState.WAITING_CONFIRMATION,
                    requires_confirmation=True,
                    pending_action_id=pending_action_id,
                    confirmation_prompt=safe_prompt,
                )

            controller.complete(transcription=transcription_text)
            return VoiceProcessResult(
                success=True,
                session_id=controller.session_id,
                transcription=transcription_text,
                brain_response=brain_resp,
                duration_seconds=time.time() - start_time,
                state=VoiceSessionState.COMPLETED,
            )

        except ModelUnavailableError as exc:
            controller.fail(str(exc))
            logger.warning("Voice processing aborted: STT model unavailable: %s", exc.message)
            return VoiceProcessResult(
                success=False,
                session_id=controller.session_id,
                transcription="",
                brain_response=None,
                duration_seconds=time.time() - start_time,
                state=VoiceSessionState.ERROR,
                error=exc.message,
            )
        except RecognitionError as exc:
            controller.fail(str(exc))
            logger.error("Voice recognition failed: %s", exc.message)
            return VoiceProcessResult(
                success=False,
                session_id=controller.session_id,
                transcription="",
                brain_response=None,
                duration_seconds=time.time() - start_time,
                state=VoiceSessionState.ERROR,
                error=exc.message,
            )
        except Exception as exc:  # noqa: BLE001
            err_msg = f"Voice processing error: {exc}"
            controller.fail(err_msg)
            logger.error(err_msg)
            return VoiceProcessResult(
                success=False,
                session_id=controller.session_id,
                transcription="",
                brain_response=None,
                duration_seconds=time.time() - start_time,
                state=VoiceSessionState.ERROR,
                error=err_msg,
            )

    async def capture_and_process(
        self,
        session_id: str | None = None,
        max_duration_seconds: float = 15.0,
        sample_rate: int = 16000,
    ) -> VoiceProcessResult:
        """Capture live audio from AudioInput under strict bounded limits and process."""
        controller = VoiceSessionController(
            session_id=session_id,
            max_duration_seconds=max_duration_seconds,
        )
        start_time = time.time()
        self.vad.reset()

        try:
            controller.start_listening()
            self.audio_input.start_recording(sample_rate=sample_rate)

            # Stream chunks from audio input until silence timeout or max duration cap
            while self.audio_input.is_recording and not controller.is_expired():
                chunk = self.audio_input.read_chunk()
                if chunk is not None:
                    self.vad.is_speech(chunk.data, sample_rate=sample_rate)
                    if hasattr(self.vad, "is_silence_timeout") and self.vad.is_silence_timeout():
                        logger.info("Silence detected after speech; stopping recording stream.")
                        break
                else:
                    # Brief pause if queue empty
                    await asyncio.sleep(0.01)

            # Stop capture and retrieve in-memory bytes
            raw_audio = self.audio_input.stop_recording()

            # Delegate to process_audio_bytes
            return await self.process_audio_bytes(raw_audio, session_id=controller.session_id)

        except AudioInputError as exc:
            controller.fail(str(exc))
            logger.error("Audio capture failed: %s", exc.message)
            return VoiceProcessResult(
                success=False,
                session_id=controller.session_id,
                transcription="",
                brain_response=None,
                duration_seconds=time.time() - start_time,
                state=VoiceSessionState.ERROR,
                error=exc.message,
            )
        except Exception as exc:  # noqa: BLE001
            err_msg = f"Audio capture error: {exc}"
            controller.fail(err_msg)
            logger.error(err_msg)
            return VoiceProcessResult(
                success=False,
                session_id=controller.session_id,
                transcription="",
                brain_response=None,
                duration_seconds=time.time() - start_time,
                state=VoiceSessionState.ERROR,
                error=err_msg,
            )

    async def speak(self, text: str, session_id: str | None = None) -> bool:
        """Synthesize and play speech audio without persisting files to disk.

        Guarantees:
        - Audio is generated in memory only; zero disk files or temporary files.
        - Enforces max text length and audio output bounds.
        - Releases raw audio buffer immediately after playback.
        - Failures return False and log structured errors without crashing the host.
        """
        if not text or not text.strip():
            return False

        logger.info("Synthesizing voice response for text (%d chars)...", len(text))
        controller = VoiceSessionController(session_id=session_id) if session_id else None

        try:
            if controller:
                controller.start_speaking()

            # 1. Synthesize audio in-memory
            audio = self.speech_synthesizer.synthesize(text)
            if not audio.data:
                logger.warning("Speech synthesis returned empty audio data.")
                if controller:
                    controller.complete()
                return False

            # 2. Play audio through output hardware/sink
            raw_audio = audio.data
            logger.info(
                "Playing synthesized voice output (%d bytes, %.2fs)...",
                len(raw_audio),
                audio.duration_seconds,
            )
            self.audio_output.play(
                raw_audio, sample_rate=audio.sample_rate, channels=audio.channels
            )

            # 3. Release audio reference immediately
            del raw_audio
            del audio

            if controller:
                controller.complete()
            return True

        except (ModelUnavailableError, SynthesisError, AudioOutputError) as exc:
            logger.error("Speech playback error: %s", exc.message)
            if controller:
                controller.fail(exc.message)
            return False
        except Exception as exc:  # noqa: BLE001
            err_msg = f"Unexpected voice output error: {exc}"
            logger.error(err_msg)
            if controller:
                controller.fail(err_msg)
            return False

    async def listen_for_wake_word(
        self,
        timeout_seconds: float = 10.0,
        sample_rate: int = 16000,
    ) -> bool:
        """Listen for wake event in a strictly bounded loop.

        Guarantees:
        - Hard timeout bounded by timeout_seconds; never loops indefinitely.
        - Discards audio chunks immediately after inspection.
        - Wake event only returns True to trigger a session; never executes tools.
        """
        if self.wake_detector is None:
            logger.debug("No wake detector configured; wake listening skipped.")
            return False

        if not self.wake_detector.is_available():
            logger.warning("Configured wake detector is not available locally.")
            return False

        start_time = time.time()
        self.wake_detector.reset()

        try:
            self.audio_input.start_recording(sample_rate=sample_rate)
            while self.audio_input.is_recording and (time.time() - start_time) < timeout_seconds:
                chunk = self.audio_input.read_chunk()
                if chunk is not None:
                    detected = self.wake_detector.detect(chunk.data, sample_rate=sample_rate)
                    if detected:
                        logger.info("Wake event detected after %.2fs", time.time() - start_time)
                        return True
                else:
                    await asyncio.sleep(0.01)
            return False
        except (ModelUnavailableError, WakeDetectionError, AudioInputError) as exc:
            logger.error("Wake listening failed: %s", exc.message)
            return False
        except Exception as exc:  # noqa: BLE001
            logger.error("Unexpected wake listening error: %s", exc)
            return False
        finally:
            if self.audio_input.is_recording:
                self.audio_input.stop_recording()

    async def listen_for_confirmation(
        self,
        session_id: str | None = None,
        timeout_seconds: float = 10.0,
        sample_rate: int = 16000,
    ) -> str:
        """Capture user confirmation utterance in a strictly bounded window.

        Enforces:
        - Bounded duration (timeout_seconds)
        - VAD silence detection
        - Immediate deletion of raw audio buffer (zero disk files)
        - Untrusted transcription text returned for validation
        """
        start_time = time.time()
        self.vad.reset()

        try:
            self.audio_input.start_recording(sample_rate=sample_rate)
            while self.audio_input.is_recording and (time.time() - start_time) < timeout_seconds:
                chunk = self.audio_input.read_chunk()
                if chunk is not None:
                    self.vad.is_speech(chunk.data, sample_rate=sample_rate)
                    if hasattr(self.vad, "is_silence_timeout") and self.vad.is_silence_timeout():
                        logger.info(
                            "Silence detected during confirmation listen; stopping recording."
                        )
                        break
                else:
                    await asyncio.sleep(0.01)

            raw_audio = self.audio_input.stop_recording()
            if not raw_audio:
                return ""

            rec = self.speech_recognizer.transcribe(raw_audio)
            del raw_audio
            return rec.text.strip()
        except Exception as exc:  # noqa: BLE001
            logger.error("Error during confirmation listening: %s", exc)
            return ""
        finally:
            if self.audio_input.is_recording:
                self.audio_input.stop_recording()

    async def resolve_voice_confirmation(
        self,
        session_id: str,
        pending_action_id: str,
        user_utterance: str,
        speak_outcome: bool = True,
    ) -> tuple[ConfirmationIntent, ConfirmationResult | None, str]:
        """Validate intent and dispatch confirmation to Brain without direct tool execution.

        Enforces:
        - Strict closed-set matching via VoiceConfirmationValidator (zero fuzzy matching)
        - Execution resumes strictly through ECHOBrain.confirm_action -> ExecutionEngine
        - Cancellation handled via ECHOBrain.cancel_action
        - Ambiguous utterances NEVER execute any tool
        - No tool or engine is ever directly imported or invoked
        """
        intent = VoiceConfirmationValidator.validate(user_utterance)

        if intent == ConfirmationIntent.CONFIRM:
            # Reuses ECHOBrain.confirm_action -> ExecutionEngine.resume_pending_action
            action = self.brain.get_pending_action(pending_action_id)
            tool_name = action.tool_name if action else ""
            confirm_res = self.brain.confirm_action(pending_action_id, session_id=session_id)
            if not tool_name and confirm_res.pending_action:
                tool_name = confirm_res.pending_action.get("tool_name", "")

            msg = VoiceConfirmationValidator.format_safe_vocal_result(
                tool_name=tool_name,
                result=confirm_res.result,
                success=confirm_res.success,
                error_message=confirm_res.message,
            )
            if speak_outcome:
                await self.speak(msg, session_id=session_id)
            return intent, confirm_res, msg

        if intent == ConfirmationIntent.CANCEL:
            # Reuses ECHOBrain.cancel_action -> ExecutionEngine.cancel_pending_action
            cancel_res = self.brain.cancel_action(pending_action_id, session_id=session_id)
            msg = "Action cancelled."
            if speak_outcome:
                await self.speak(msg, session_id=session_id)
            return intent, cancel_res, msg

        # AMBIGUOUS: Never execute tools on ambiguity!
        msg = "Confirmation unclear. Action was not executed. Please say yes to confirm or no to cancel."
        if speak_outcome:
            await self.speak(msg, session_id=session_id)
        return intent, None, msg

    async def process_voice_interaction(
        self,
        speak_response: bool = True,
        session_id: str | None = None,
        max_duration_seconds: float = 15.0,
        handle_confirmation_flow: bool = True,
    ) -> VoiceProcessResult:
        """Coordinate full voice interaction: capture, STT, Brain execution, and optional TTS.

        Voice remains strictly an input/output adapter. All commands enter ECHOBrain.process()
        as Request(source='voice'), preserving existing Brain -> Planner -> SafetyEngine boundaries.
        """
        # 1. Capture and process speech through Brain
        result = await self.capture_and_process(
            session_id=session_id,
            max_duration_seconds=max_duration_seconds,
        )

        # 2. Check if the interaction requires human confirmation
        if result.requires_confirmation and result.pending_action_id and handle_confirmation_flow:
            # Vocalize safe human-readable prompt without raw dicts, IDs, or secrets
            prompt_to_speak = (
                result.confirmation_prompt
                or "This action requires confirmation before proceeding. Say yes to confirm or no to cancel."
            )
            if speak_response:
                await self.speak(prompt_to_speak, session_id=result.session_id)

            # Bounded listen specifically for confirmation response
            confirm_utterance = await self.listen_for_confirmation(session_id=result.session_id)
            if not confirm_utterance:
                timeout_msg = "Confirmation timed out. Action not executed."
                if speak_response:
                    await self.speak(timeout_msg, session_id=result.session_id)
                result.state = VoiceSessionState.COMPLETED
                result.brain_response = timeout_msg
                return result

            # Resolve confirmation through canonical Brain APIs
            _intent, confirm_res, outcome_msg = await self.resolve_voice_confirmation(
                session_id=result.session_id,
                pending_action_id=result.pending_action_id,
                user_utterance=confirm_utterance,
                speak_outcome=speak_response,
            )
            result.confirmation_result = confirm_res
            result.brain_response = outcome_msg
            result.state = VoiceSessionState.COMPLETED
            return result

        # 3. Standard response vocalization
        if speak_response and result.success and result.brain_response:
            await self.speak(result.brain_response, session_id=result.session_id)

        return result


voice_manager = VoiceManager()
