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

  let activePendingActionId = null;
  let isListening = false;
  let speechRecognition = null;
  let hasConnectedOnce = false;

  // 1. Initialize Avatar Core (10D.1) & Voice Presentation Engine (10D.2)
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

    // 10C.3: Re-sync state with server upon reconnection
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
    avatar.setState(avatar.STATES.IDLE);
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
    if (voiceEngine) {
      const cue = `Security authorization required. ${payload.safe_description || 'Action requires confirmation.'} Say authorize or abort.`;
      voiceEngine.speak(cue);
    }
  });

  gateway.on('action_result', (payload) => {
    hideConfirmationModal();
    const statusMsg = payload.success ? 'Action executed successfully.' : 'Action failed or cancelled.';
    appendLogEntry('EXECUTION', `${statusMsg} (${payload.status}): ${payload.message || ''}`, 'system-entry');
    if (voiceEngine) {
      voiceEngine.speak(statusMsg);
    }
  });

  // Connect to live gateway
  gateway.connect();

  // 4. Voice-First Push-to-Talk Logic
  // Uses Browser Web Speech API if supported as client-side speech input
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
        avatar.setState(avatar.STATES.LISTENING);
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
        avatar.setState(avatar.STATES.IDLE);
      };

      speechRecognition.onend = () => {
        isListening = false;
        setVoiceButtonState(false);
      };
    }
  }

  function toggleVoiceCapture() {
    if (!isListening) {
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
        speechRecognition.stop();
      }
      isListening = false;
      setVoiceButtonState(false);
      avatar.setState(avatar.STATES.IDLE);
    }
  }

  function promptDirectVoiceFallback() {
    isListening = true;
    setVoiceButtonState(true);
    avatar.setState(avatar.STATES.LISTENING);
    voiceGuidanceText.textContent = 'Listening (Type or speak query)...';
    commandInput.focus();
  }

  function handleVoiceTranscriptComplete(spokenText) {
    if (!spokenText) return;
    voiceGuidanceText.textContent = `Transcribed: "${spokenText}"`;
    isListening = false;
    setVoiceButtonState(false);

    // Check if a confirmation modal is open and user said "authorize" or "cancel"
    if (activePendingActionId && !modalEl.classList.contains('hidden')) {
      const lower = spokenText.toLowerCase();
      if (lower.includes('authorize') || lower.includes('confirm') || lower.includes('yes')) {
        handleConfirmAction();
        return;
      }
      if (lower.includes('cancel') || lower.includes('abort') || lower.includes('no')) {
        handleAbortAction();
        return;
      }
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

    commandInput.value = '';
    gateway.sendUserInput(text);
  });

  document.querySelectorAll('.chip-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const promptText = btn.getAttribute('data-prompt');
      if (promptText) {
        gateway.sendUserInput(promptText);
      }
    });
  });

  btnClearLog.addEventListener('click', () => {
    transcriptFeed.replaceChildren();
    appendLogEntry('SYSTEM', 'Comm log cleared.', 'system-entry');
    if (typeof window !== 'undefined' && window.speechSynthesis) {
      window.speechSynthesis.cancel();
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

  // 6. Security Confirmation Modal Handlers
  function showConfirmationModal(payload) {
    activePendingActionId = payload.action_id;
    modalActionIdEl.textContent = payload.action_id || 'act_unknown';
    modalToolNameEl.textContent = payload.tool_name || 'operation';
    modalRiskLevelEl.textContent = payload.risk_level || 'SENSITIVE';
    modalDescEl.textContent = payload.safe_description || 'Action requires authorization.';

    try {
      modalParamsEl.textContent = JSON.stringify(payload.parameters || {}, null, 2);
    } catch {
      modalParamsEl.textContent = '{}';
    }

    modalEl.classList.remove('hidden');
  }

  function hideConfirmationModal() {
    activePendingActionId = null;
    modalEl.classList.add('hidden');
  }

  function handleConfirmAction() {
    if (!activePendingActionId) return;
    gateway.confirmAction(activePendingActionId);
    hideConfirmationModal();
  }

  function handleAbortAction() {
    if (!activePendingActionId) return;
    gateway.cancelAction(activePendingActionId);
    hideConfirmationModal();
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

  // 10. Keyboard Accessibility & Dual Confirmation Navigation (10C.3)
  window.addEventListener('keydown', (e) => {
    const isModalOpen = activePendingActionId && !modalEl.classList.contains('hidden');

    if (isModalOpen) {
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
