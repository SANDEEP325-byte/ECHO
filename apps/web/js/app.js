/**
 * ECHO Jarvis Command Center — Main Application Controller (Phase 10C.2)
 *
 * Coordinates the holographic AvatarCore, GatewayClient, HUD telemetry,
 * voice interaction deck, transcript feed, and security authorization modals.
 */

document.addEventListener('DOMContentLoaded', () => {
  // DOM Element References
  const canvasEl = document.getElementById('avatar-canvas');
  const avatarStateLabel = document.getElementById('avatar-state-label');
  const subsystemAvatarIndicator = document.getElementById('subsystem-avatar-indicator');
  const gatewayStatusEl = document.getElementById('gateway-status');
  const sessionIdDisplay = document.getElementById('session-id-display');
  const clockDisplay = document.getElementById('clock-display');

  const voiceToggleBtn = document.getElementById('btn-voice-toggle');
  const voiceButtonLabel = document.getElementById('voice-button-label');
  const voiceGuidanceText = document.getElementById('voice-guidance');

  const transcriptFeed = document.getElementById('transcript-feed');
  const btnClearLog = document.getElementById('btn-clear-log');
  const btnExportLog = document.getElementById('btn-export-log');
  const commandForm = document.getElementById('command-form');
  const commandInput = document.getElementById('command-input');

  // Mute Toggle Elements
  const btnMuteToggle = document.getElementById('btn-mute-toggle');
  const muteStatusLabel = document.getElementById('mute-status-label');

  // Confirmation Modal Elements
  const modalEl = document.getElementById('confirmation-modal');
  const modalActionIdEl = document.getElementById('modal-action-id');
  const modalToolNameEl = document.getElementById('modal-tool-name');
  const modalRiskLevelEl = document.getElementById('modal-risk-level');
  const modalDescEl = document.getElementById('modal-description-text');
  const modalParamsEl = document.getElementById('modal-params-content');
  const btnConfirmAction = document.getElementById('btn-confirm-action');
  const btnAbortAction = document.getElementById('btn-abort-action');
  const modalStatusBadge = document.getElementById('modal-status-badge');
  const modalTimerCountdown = document.getElementById('modal-timer-countdown');
  const modalExecutionNotice = document.getElementById('modal-execution-notice');
  const modalExecutionMessage = document.getElementById('modal-execution-message');

  let activePendingActionId = null;
  let actionExpiresAt = null;
  let actionExecutionLocked = false;
  let countdownTimerInterval = null;
  let isListening = false;
  let speechRecognition = null;
  let hasConnectedOnce = false;

  // Canonical Voice Confirmation Vocabulary (Phase 10F Security)
  const AUTHORIZE_PHRASES = ['authorize', 'confirm', 'proceed', 'yes', 'approve'];
  const CANCEL_PHRASES = ['abort', 'cancel', 'deny', 'no', 'reject', 'stop'];

  /**
   * Deterministic, conservative intent classifier for voice authorization.
   * Ambiguous or uncertain utterances are strictly rejected to prevent unintended execution.
   * @param {string} rawTranscript
   * @returns {'authorize' | 'abort' | 'ambiguous'}
   */
  function classifyConfirmationIntent(rawTranscript) {
    if (!rawTranscript || typeof rawTranscript !== 'string') return 'ambiguous';
    const normalized = rawTranscript.toLowerCase().replace(/[^\w\s]/g, ' ').trim();
    const tokens = normalized.split(/\s+/).filter(Boolean);

    const hasAuth = tokens.some(t => AUTHORIZE_PHRASES.includes(t));
    const hasCancel = tokens.some(t => CANCEL_PHRASES.includes(t));

    if (hasAuth && !hasCancel) return 'authorize';
    if (hasCancel && !hasAuth) return 'abort';
    return 'ambiguous';
  }

  // 1. Initialize Avatar Core (10D.1) & Voice Presentation Engine (10D.2/10E.1)
  const avatar = new AvatarCore(canvasEl);
  const voiceEngine = (typeof VoicePresentationEngine !== 'undefined')
    ? new VoicePresentationEngine(avatar)
    : null;

  // Hook state changes to HUD UI indicators
  avatar.on('onStateChange', (oldState, newState) => {
    updateAvatarStateBadge(newState);
  });

  // Mute State Display & Sync
  function updateMuteDisplay() {
    if (!voiceEngine || !muteStatusLabel) return;
    const muted = voiceEngine.getMuted();
    if (muted) {
      muteStatusLabel.textContent = 'MUTED';
      muteStatusLabel.className = 'telemetry-value status-offline';
    } else {
      muteStatusLabel.textContent = 'UNMUTED';
      muteStatusLabel.className = 'telemetry-value status-active';
    }
  }

  if (btnMuteToggle) {
    btnMuteToggle.addEventListener('click', () => {
      if (voiceEngine) {
        voiceEngine.toggleMute();
        updateMuteDisplay();
      }
    });
    updateMuteDisplay();
  }

  // 2. Initialize Gateway WebSocket Client (10C.1 / 10C.2 / 10C.3)
  const gateway = new GatewayClient();

  gateway.on('open', () => {
    gatewayStatusEl.textContent = 'ONLINE';
    gatewayStatusEl.className = 'telemetry-value status-active';
    appendLogEntry('SYSTEM', 'Gateway connection established to /ws/live.', 'system-entry');

    // 10C.3 / 10F.2: Re-sync state with server upon reconnection.
    // Restores any active, unexpired pending confirmation bound to this session.
    if (hasConnectedOnce) {
      gateway.queryState();
    }
    hasConnectedOnce = true;
  });

  gateway.on('close', () => {
    gatewayStatusEl.textContent = 'RECONNECTING...';
    gatewayStatusEl.className = 'telemetry-value status-offline';
    avatar.setState(avatar.STATES.ERROR);
  });

  gateway.on('any', (data) => {
    if (data.session_id) {
      sessionIdDisplay.textContent = data.session_id;
    }
  });

  // 3. Register Gateway Event Handlers
  gateway.on('idle', (payload) => {
    // Only return to IDLE if no confirmation is currently pending
    if (!activePendingActionId || modalEl.classList.contains('hidden')) {
      avatar.setState(avatar.STATES.IDLE);
    }
    setVoiceButtonState(false);
  });

  gateway.on('listening', (payload) => {
    avatar.setState(avatar.STATES.LISTENING);
    if (payload && payload.transcript_partial) {
      voiceGuidanceText.textContent = `"${payload.transcript_partial}"`;
    }
  });

  gateway.on('thinking', (payload) => {
    avatar.setState(avatar.STATES.THINKING);
    setVoiceButtonState(false);
    if (payload && payload.user_input) {
      appendLogEntry('USER', payload.user_input, 'user-entry');
    }
  });

  gateway.on('speaking', (payload) => {
    avatar.setState(avatar.STATES.SPEAKING);
    if (payload && payload.response_text) {
      appendLogEntry('ECHO', payload.response_text, 'assistant-entry');
      if (voiceEngine) {
        voiceEngine.speak(payload.response_text);
      }
    }
  });

  gateway.on('alert', (payload) => {
    if (payload && payload.title !== 'pong') {
      appendLogEntry('ALERT', `${payload.title}: ${payload.message}`, 'system-entry');
      avatar.setState(avatar.STATES.ALERT);
    }
  });

  gateway.on('error', (payload) => {
    avatar.setState(avatar.STATES.ERROR);
    appendLogEntry('ERROR', `${payload.code}: ${payload.message}`, 'error-entry');
  });

  gateway.on('confirmation_required', (payload) => {
    avatar.setState(avatar.STATES.CONFIRMATION);
    showConfirmationModal(payload);
  });

  gateway.on('action_result', (payload) => {
    handleActionResult(payload);
  });

  // Connect to live gateway
  gateway.connect();

  // 4. Voice-First Push-to-Talk Logic (Phase 10E.3 / 10F.1)
  setupSpeechRecognition();

  voiceToggleBtn.addEventListener('click', () => {
    toggleVoiceCapture();
  });

  function setupSpeechRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
      speechRecognition = new SpeechRecognition();
      speechRecognition.continuous = false;
      speechRecognition.interimResults = true;
      speechRecognition.lang = 'en-US';

      speechRecognition.onstart = () => {
        isListening = true;
        setVoiceButtonState(true);
        // Phase 10E.3: Starting voice capture immediately interrupts assistant speech
        if (voiceEngine && voiceEngine.isSpeaking()) {
          voiceEngine.stop('user_interrupted');
        }
        if (!activePendingActionId || modalEl.classList.contains('hidden')) {
          avatar.setState(avatar.STATES.LISTENING);
        }
      };

      speechRecognition.onresult = (event) => {
        let interimTranscript = '';
        let finalTranscript = '';

        for (let i = event.resultIndex; i < event.results.length; i++) {
          const transcript = event.results[i][0].transcript;
          if (event.results[i].isFinal) {
            finalTranscript += transcript;
          } else {
            interimTranscript += transcript;
          }
        }

        if (interimTranscript) {
          voiceGuidanceText.textContent = `Hearing: "${interimTranscript}"`;
        }

        if (finalTranscript) {
          handleVoiceTranscriptComplete(finalTranscript.trim());
        }
      };

      speechRecognition.onerror = (err) => {
        console.warn('[SpeechRecognition] Error:', err.error);
        isListening = false;
        setVoiceButtonState(false);
        if (!activePendingActionId || modalEl.classList.contains('hidden')) {
          avatar.setState(avatar.STATES.IDLE);
        }
      };

      speechRecognition.onend = () => {
        isListening = false;
        setVoiceButtonState(false);
      };
    }
  }

  function toggleVoiceCapture() {
    if (!isListening) {
      // Phase 10E.3: Starting user voice capture interrupts assistant speech
      if (voiceEngine && voiceEngine.isSpeaking()) {
        voiceEngine.stop('user_interrupted');
      }

      if (speechRecognition) {
        try {
          speechRecognition.start();
        } catch (err) {
          console.warn('SpeechRecognition start failed, prompting text:', err);
          promptDirectVoiceFallback();
        }
      } else {
        promptDirectVoiceFallback();
      }
    } else {
      if (speechRecognition) {
        try {
          speechRecognition.stop();
        } catch (err) {
          console.warn('SpeechRecognition stop error:', err);
        }
      }
      isListening = false;
      setVoiceButtonState(false);
      if (!activePendingActionId || modalEl.classList.contains('hidden')) {
        avatar.setState(avatar.STATES.IDLE);
      }
    }
  }

  function promptDirectVoiceFallback() {
    isListening = true;
    setVoiceButtonState(true);
    if (!activePendingActionId || modalEl.classList.contains('hidden')) {
      avatar.setState(avatar.STATES.LISTENING);
    }
    voiceGuidanceText.textContent = 'Listening (Type or speak query)...';
    commandInput.focus();
  }

  function handleVoiceTranscriptComplete(spokenText) {
    if (!spokenText) return;
    voiceGuidanceText.textContent = `Transcribed: "${spokenText}"`;
    isListening = false;
    setVoiceButtonState(false);

    // Phase 10F.1: Check if a confirmation modal is open and awaiting authorization
    if (activePendingActionId && !modalEl.classList.contains('hidden') && !actionExecutionLocked) {
      const intent = classifyConfirmationIntent(spokenText);
      if (intent === 'authorize') {
        handleConfirmAction();
        return;
      }
      if (intent === 'abort') {
        handleAbortAction();
        return;
      }
      // Ambiguous speech MUST NOT execute an action
      appendLogEntry(
        'SECURITY',
        `Ambiguous voice cue received: "${spokenText}". Explicit cue required ("authorize" or "abort").`,
        'error-entry'
      );
      if (voiceEngine) {
        voiceEngine.speak('Ambiguous cue. Please say authorize or abort.');
      }
      return;
    }

    // Phase 10E.3: New user input interrupts assistant speech
    if (voiceEngine && voiceEngine.isSpeaking()) {
      voiceEngine.stop('user_input');
    }

    // Dispatch voice input through gateway to ECHOBrain
    gateway.sendUserInput(spokenText);
  }

  function setVoiceButtonState(listening) {
    if (listening) {
      voiceToggleBtn.classList.add('active-listening');
      voiceButtonLabel.textContent = 'LISTENING...';
    } else {
      voiceToggleBtn.classList.remove('active-listening');
      voiceButtonLabel.textContent = 'VOICE ACTIVATION';
      voiceGuidanceText.textContent = 'Voice-first command interface • Tap or send audio prompt';
    }
  }

  // 5. Diagnostic Text Form & Quick Prompts
  commandForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = (commandInput.value || '').trim();
    if (!text) return;

    // Phase 10E.3: Submitting new input immediately halts ongoing assistant speech
    if (voiceEngine && voiceEngine.isSpeaking()) {
      voiceEngine.stop('user_input');
    }

    commandInput.value = '';
    gateway.sendUserInput(text);
  });

  document.querySelectorAll('.chip-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const promptText = btn.getAttribute('data-prompt');
      if (promptText) {
        if (voiceEngine && voiceEngine.isSpeaking()) {
          voiceEngine.stop('user_input');
        }
        gateway.sendUserInput(promptText);
      }
    });
  });

  btnClearLog.addEventListener('click', () => {
    transcriptFeed.replaceChildren();
    appendLogEntry('SYSTEM', 'Comm log cleared.', 'system-entry');
    if (voiceEngine && voiceEngine.isSpeaking()) {
      voiceEngine.stop('cleared');
    }
  });

  if (btnExportLog) {
    btnExportLog.addEventListener('click', () => {
      const entries = Array.from(transcriptFeed.querySelectorAll('.feed-entry'));
      const logLines = entries.map(e => {
        const time = e.querySelector('.entry-timestamp')?.textContent || '';
        const bubble = e.querySelector('.entry-bubble')?.textContent || '';
        return `${time} ${bubble}`;
      }).join('\n');

      const blob = new Blob([logLines], { type: 'text/plain;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `echo-comm-log-${new Date().toISOString().slice(0, 10)}.txt`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    });
  }

  // 6. Security Confirmation Modal Handlers (Phase 10F.1 / 10F.2 / 10F.3)
  function clearConfirmationCountdown() {
    if (countdownTimerInterval) {
      clearInterval(countdownTimerInterval);
      countdownTimerInterval = null;
    }
  }

  function showConfirmationModal(payload) {
    clearConfirmationCountdown();
    actionExecutionLocked = false;
    activePendingActionId = payload.action_id || null;
    actionExpiresAt = typeof payload.expires_at === 'number' ? payload.expires_at : null;

    // Reset controls & badges
    btnConfirmAction.disabled = false;
    btnAbortAction.disabled = false;
    if (modalExecutionNotice) {
      modalExecutionNotice.classList.add('hidden');
    }
    if (modalStatusBadge) {
      modalStatusBadge.textContent = 'PENDING';
      modalStatusBadge.className = 'status-tag tag-pending';
    }

    // Populate data strictly using textContent to prevent HTML injection
    modalActionIdEl.textContent = payload.action_id || 'act_unknown';
    modalToolNameEl.textContent = payload.tool_name || 'operation';
    modalRiskLevelEl.textContent = payload.risk_level || 'SENSITIVE';
    modalDescEl.textContent = payload.safe_description || 'Action requires authorization.';

    try {
      modalParamsEl.textContent = JSON.stringify(payload.parameters || {}, null, 2);
    } catch {
      modalParamsEl.textContent = '{}';
    }

    // Authoritative countdown derived from backend-supplied expires_at (Phase 10F.2)
    if (actionExpiresAt && actionExpiresAt > 0) {
      const updateTimer = () => {
        const nowSec = Date.now() / 1000;
        const remaining = Math.max(0, Math.ceil(actionExpiresAt - nowSec));
        const mins = Math.floor(remaining / 60);
        const secs = remaining % 60;
        if (modalTimerCountdown) {
          modalTimerCountdown.textContent = `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
          if (remaining <= 10) {
            modalTimerCountdown.classList.add('timer-urgent');
          } else {
            modalTimerCountdown.classList.remove('timer-urgent');
          }
        }

        if (remaining <= 0) {
          clearConfirmationCountdown();
          actionExecutionLocked = true;
          if (modalStatusBadge) {
            modalStatusBadge.textContent = 'EXPIRED';
            modalStatusBadge.className = 'status-tag tag-expired';
          }
          btnConfirmAction.disabled = true;
          btnAbortAction.disabled = true;

          // Stop voice recognition if listening for confirmation
          if (speechRecognition && isListening) {
            try { speechRecognition.stop(); } catch {}
          }

          if (voiceEngine) {
            voiceEngine.speak('The authorization request expired.');
          }
          avatar.setState(avatar.STATES.ALERT);
        }
      };

      updateTimer();
      countdownTimerInterval = setInterval(updateTimer, 500);
    } else {
      if (modalTimerCountdown) {
        modalTimerCountdown.textContent = '--:--';
        modalTimerCountdown.classList.remove('timer-urgent');
      }
    }

    modalEl.classList.remove('hidden');

    // Safe sequencing (Phase 10F.1): Speak prompt cue first, then enable speech recognition
    // after playback completes so assistant speech cannot trigger self-confirmation.
    if (voiceEngine) {
      const safeDesc = payload.safe_description || (payload.tool_name ? `Operation ${payload.tool_name}` : 'Action requires authorization.');
      const promptCue = `Security authorization required. ${safeDesc}. Say authorize or abort.`;

      if (voiceEngine.isSpeaking()) {
        voiceEngine.stop('new_utterance');
      }

      voiceEngine.speak(promptCue, (res) => {
        if (
          !res.interrupted &&
          activePendingActionId === payload.action_id &&
          !actionExecutionLocked &&
          !modalEl.classList.contains('hidden')
        ) {
          startConfirmationVoiceListening();
        }
      });
    }
  }

  function startConfirmationVoiceListening() {
    if (speechRecognition && !isListening && !actionExecutionLocked) {
      try {
        speechRecognition.start();
        voiceGuidanceText.textContent = 'Awaiting voice decision: say "authorize" or "abort"...';
      } catch (err) {
        console.warn('[SpeechRecognition] Confirmation listening start failed:', err);
      }
    }
  }

  function hideConfirmationModal() {
    clearConfirmationCountdown();
    activePendingActionId = null;
    actionExpiresAt = null;
    actionExecutionLocked = false;
    modalEl.classList.add('hidden');
    if (modalExecutionNotice) {
      modalExecutionNotice.classList.add('hidden');
    }
  }

  function handleConfirmAction() {
    if (!activePendingActionId || actionExecutionLocked) return;
    actionExecutionLocked = true;

    // Backend-aligned local expiry check
    if (actionExpiresAt && (Date.now() / 1000) >= actionExpiresAt) {
      clearConfirmationCountdown();
      if (modalStatusBadge) {
        modalStatusBadge.textContent = 'EXPIRED';
        modalStatusBadge.className = 'status-tag tag-expired';
      }
      btnConfirmAction.disabled = true;
      btnAbortAction.disabled = true;
      if (voiceEngine) {
        voiceEngine.speak('The authorization request expired.');
      }
      return;
    }

    // Duplicate UI Protection: Disable controls and show executing notice
    btnConfirmAction.disabled = true;
    btnAbortAction.disabled = true;
    if (modalStatusBadge) {
      modalStatusBadge.textContent = 'EXECUTING';
      modalStatusBadge.className = 'status-tag tag-executing';
    }
    if (modalExecutionNotice && modalExecutionMessage) {
      modalExecutionMessage.textContent = 'AUTHORIZING & EXECUTING ACTION...';
      modalExecutionNotice.classList.remove('hidden');
    }

    // Stop recognition if active
    if (speechRecognition && isListening) {
      try { speechRecognition.stop(); } catch {}
    }

    // Transition avatar to THINKING during backend execution
    avatar.setState(avatar.STATES.THINKING);

    // Backend PendingActionManager is authoritative
    gateway.confirmAction(activePendingActionId);
  }

  function handleAbortAction() {
    if (!activePendingActionId || actionExecutionLocked) return;
    actionExecutionLocked = true;

    btnConfirmAction.disabled = true;
    btnAbortAction.disabled = true;
    if (modalStatusBadge) {
      modalStatusBadge.textContent = 'ABORTING';
      modalStatusBadge.className = 'status-tag tag-aborted';
    }
    if (modalExecutionNotice && modalExecutionMessage) {
      modalExecutionMessage.textContent = 'CANCELLING ACTION...';
      modalExecutionNotice.classList.remove('hidden');
    }

    if (speechRecognition && isListening) {
      try { speechRecognition.stop(); } catch {}
    }

    avatar.setState(avatar.STATES.ALERT);

    gateway.cancelAction(activePendingActionId);
  }

  function handleActionResult(payload) {
    clearConfirmationCountdown();
    actionExecutionLocked = true;

    const status = (payload.status || (payload.success ? 'SUCCESS' : 'FAILED')).toUpperCase();

    let badgeClass = 'tag-failed';
    let spokenResult = 'Action authorization failed or the action could not be completed.';

    switch (status) {
      case 'SUCCESS':
        badgeClass = 'tag-success';
        spokenResult = 'Action authorized and executed successfully.';
        break;
      case 'ABORTED':
        badgeClass = 'tag-aborted';
        spokenResult = 'Action cancelled.';
        break;
      case 'EXPIRED':
        badgeClass = 'tag-expired';
        spokenResult = 'The authorization request expired.';
        break;
      case 'ALREADY_PROCESSED':
        badgeClass = 'tag-aborted';
        spokenResult = 'This authorization request has already been processed.';
        break;
      case 'AUTHORIZATION_FAILED':
      case 'FAILED':
      default:
        badgeClass = 'tag-failed';
        spokenResult = 'Action authorization failed or the action could not be completed.';
        break;
    }

    if (modalStatusBadge) {
      modalStatusBadge.textContent = status;
      modalStatusBadge.className = `status-tag ${badgeClass}`;
    }
    if (modalExecutionMessage) {
      modalExecutionMessage.textContent = `RESULT: ${status}`;
    }

    const logStatus = payload.success ? 'SUCCESS' : status;
    appendLogEntry('EXECUTION', `Action ${logStatus}: ${payload.message || ''}`, 'system-entry');

    // Avatar enters SPEAKING for result voice feedback, then returns to IDLE
    if (voiceEngine) {
      avatar.setState(avatar.STATES.SPEAKING);
      voiceEngine.speak(spokenResult, () => {
        avatar.setState(payload.success ? avatar.STATES.IDLE : avatar.STATES.ALERT);
      });
    } else {
      avatar.setState(payload.success ? avatar.STATES.IDLE : avatar.STATES.ALERT);
    }

    // Keep modal visible briefly (1.5s) for user visual feedback before closing
    setTimeout(() => {
      hideConfirmationModal();
    }, 1500);
  }

  btnConfirmAction.addEventListener('click', handleConfirmAction);
  btnAbortAction.addEventListener('click', handleAbortAction);

  // 7. Safe DOM Rendering for Transcript Log
  function appendLogEntry(sender, message, cssClass) {
    const entryDiv = document.createElement('div');
    entryDiv.className = `feed-entry ${cssClass}`;

    const timestampSpan = document.createElement('span');
    timestampSpan.className = 'entry-timestamp';
    const now = new Date();
    const timeStr = now.toTimeString().split(' ')[0];
    timestampSpan.textContent = `[${timeStr}] ${sender}`;

    const bubbleDiv = document.createElement('div');
    bubbleDiv.className = 'entry-bubble';
    // STRICT: Use textContent to prevent XSS / raw HTML injection
    bubbleDiv.textContent = message;

    entryDiv.appendChild(timestampSpan);
    entryDiv.appendChild(bubbleDiv);
    transcriptFeed.appendChild(entryDiv);

    // Auto-scroll to bottom
    transcriptFeed.scrollTop = transcriptFeed.scrollHeight;
  }

  // 8. State Badge Synchronization
  function updateAvatarStateBadge(state) {
    avatarStateLabel.className = 'state-badge';
    avatarStateLabel.textContent = state.toUpperCase();
    subsystemAvatarIndicator.textContent = state.toUpperCase();

    switch (state) {
      case avatar.STATES.LISTENING:
        avatarStateLabel.classList.add('badge-listening');
        break;
      case avatar.STATES.THINKING:
        avatarStateLabel.classList.add('badge-thinking');
        break;
      case avatar.STATES.SPEAKING:
        avatarStateLabel.classList.add('badge-speaking');
        break;
      case avatar.STATES.ALERT:
      case avatar.STATES.CONFIRMATION:
        avatarStateLabel.classList.add('badge-alert');
        break;
      case avatar.STATES.ERROR:
        avatarStateLabel.classList.add('badge-error');
        break;
      case avatar.STATES.IDLE:
      default:
        avatarStateLabel.classList.add('badge-idle');
        break;
    }
  }

  // 9. Real-Time Military Clock
  function updateClock() {
    const now = new Date();
    clockDisplay.textContent = now.toISOString().slice(11, 19);
  }
  setInterval(updateClock, 1000);
  updateClock();

  // 10. Keyboard Accessibility & Dual Confirmation Navigation (10C.3 / 10F.1)
  window.addEventListener('keydown', (e) => {
    const isModalOpen = activePendingActionId && !modalEl.classList.contains('hidden');

    if (isModalOpen && !actionExecutionLocked) {
      if (e.key === 'Enter') {
        e.preventDefault();
        handleConfirmAction();
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        handleAbortAction();
        return;
      }
    }

    // Ignore global hotkeys if user is currently typing in an input or textarea
    const activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : '';
    if (activeTag === 'input' || activeTag === 'textarea') {
      return;
    }

    if (e.code === 'Space' || e.key.toLowerCase() === 'v') {
      e.preventDefault();
      toggleVoiceCapture();
      return;
    }

    if (e.key.toLowerCase() === 'm') {
      e.preventDefault();
      if (voiceEngine) {
        voiceEngine.toggleMute();
        updateMuteDisplay();
      }
    }
  });
});
