/**
 * ECHO Voice Presentation & Speech Feedback Engine (Phase 10E & 10F)
 *
 * Coordinates audio feedback, speech synthesis vocalization, audio reactivity,
 * and mute/unmute states for the voice-first command center.
 *
 * Implements:
 * - 10E.1: Explicit speech playback lifecycle (START, PLAYING, PAUSED, COMPLETED, INTERRUPTED, ERROR)
 *          with generation token tracking to eliminate race conditions from delayed browser callbacks.
 * - 10E.2: Modular articulatory energy estimation and canonical viseme mapping ('aa', 'ee', 'oh', 'ch', 'rest').
 * - 10E.3: Voice presentation controls (pause, resume, stop/interrupt) and Jarvis-style pacing (rate: 1.05, pitch: 0.95).
 * - 10F.1: Spoken confirmation cues and result announcements.
 *
 * Note: Native browser SpeechSynthesis does not provide reliable direct PCM audio streams.
 * Articulatory energy and boundary visemes are deterministic timing-based estimates/simulations
 * driving the pluggable BaseAvatarRenderer without heavy external dependencies.
 */

class VoicePresentationEngine {
  constructor(avatarInstance, options = {}) {
    this.avatar = avatarInstance;
    this.isMuted = false;
    this.selectedVoice = null;
    this.amplitudeIntervalId = null;

    // Phase 10E.1: Explicit Lifecycle States
    this.STATES = {
      IDLE: 'idle',
      START: 'start',
      PLAYING: 'playing',
      PAUSED: 'paused',
      COMPLETED: 'completed',
      INTERRUPTED: 'interrupted',
      ERROR: 'error',
    };
    this.lifecycleState = this.STATES.IDLE;

    // Generation token to prevent stale callbacks from delayed browser speech events
    this._generationToken = 0;
    this.activeOnComplete = null;

    // Extensible Lifecycle Event Hooks
    this.listeners = {
      onSpeechStart: [],
      onSpeechEnd: [],
      onSpeechPause: [],
      onSpeechResume: [],
      onSpeechInterrupted: [],
      onViseme: [],
    };

    // Load persisted mute preference
    try {
      this.isMuted = localStorage.getItem('echo_voice_muted') === 'true';
    } catch {
      this.isMuted = false;
    }

    this.initVoices();
  }

  initVoices() {
    if (typeof window === 'undefined' || !window.speechSynthesis) return;

    const populateVoices = () => {
      const voices = window.speechSynthesis.getVoices();
      if (!voices || voices.length === 0) return;

      // Prefer natural English voices (e.g. Natural, Google, Microsoft David/Mark)
      const preferred =
        voices.find(
          (v) =>
            v.lang.startsWith('en') &&
            (v.name.includes('Natural') || v.name.includes('Google') || v.name.includes('David'))
        ) ||
        voices.find((v) => v.lang.startsWith('en')) ||
        voices[0];

      this.selectedVoice = preferred;
    };

    populateVoices();
    if (window.speechSynthesis.onvoiceschanged !== undefined) {
      window.speechSynthesis.onvoiceschanged = populateVoices;
    }
  }

  on(event, callback) {
    if (this.listeners[event]) {
      this.listeners[event].push(callback);
    }
  }

  emit(event, ...args) {
    if (this.listeners[event]) {
      this.listeners[event].forEach((cb) => {
        try {
          cb(...args);
        } catch (err) {
          console.error(`[VoicePresentationEngine] Hook error in "${event}":`, err);
        }
      });
    }
  }

  getState() {
    return this.lifecycleState;
  }

  isSpeaking() {
    return (
      this.lifecycleState === this.STATES.PLAYING ||
      this.lifecycleState === this.STATES.START
    );
  }

  isPaused() {
    return this.lifecycleState === this.STATES.PAUSED;
  }

  setMuted(muted) {
    this.isMuted = Boolean(muted);
    try {
      localStorage.setItem('echo_voice_muted', this.isMuted ? 'true' : 'false');
    } catch {
      // Ignored in private/sandboxed mode
    }

    if (this.isMuted) {
      this.stop('muted');
    }

    return this.isMuted;
  }

  toggleMute() {
    return this.setMuted(!this.isMuted);
  }

  getMuted() {
    return this.isMuted;
  }

  /**
   * Pause ongoing speech playback and freeze articulatory amplitude.
   */
  pause() {
    if (!this.isSpeaking() || typeof window === 'undefined' || !window.speechSynthesis) {
      return false;
    }

    try {
      window.speechSynthesis.pause();
      this.lifecycleState = this.STATES.PAUSED;
      this.stopAmplitudeSimulation();
      if (this.avatar) {
        this.avatar.setAudioAmplitude(0);
      }
      this.emit('onSpeechPause');
      return true;
    } catch (err) {
      console.warn('[VoicePresentationEngine] Pause failed:', err);
      return false;
    }
  }

  /**
   * Resume paused speech playback and restart articulatory amplitude.
   */
  resume() {
    if (!this.isPaused() || typeof window === 'undefined' || !window.speechSynthesis) {
      return false;
    }

    try {
      window.speechSynthesis.resume();
      this.lifecycleState = this.STATES.PLAYING;
      this.startAmplitudeSimulation();
      this.emit('onSpeechResume');
      return true;
    } catch (err) {
      console.warn('[VoicePresentationEngine] Resume failed:', err);
      return false;
    }
  }

  /**
   * Stop or interrupt speech output cleanly, resetting all articulation and amplitude.
   * Invalidates generation token so delayed browser callbacks cannot corrupt state.
   * @param {string} reason - Interruption reason ('user_interrupted', 'user_input', 'stopped', 'muted')
   */
  stop(reason = 'stopped') {
    // Invalidate current token so queued/delayed callbacks are ignored
    const previousToken = this._generationToken;
    this._generationToken++;

    if (typeof window !== 'undefined' && window.speechSynthesis) {
      try {
        window.speechSynthesis.cancel();
      } catch (err) {
        console.warn('[VoicePresentationEngine] Cancel failed:', err);
      }
    }

    this.stopAmplitudeSimulation();

    if (this.avatar) {
      this.avatar.setAudioAmplitude(0);
      this.avatar.resetArticulation();
      // If currently speaking, return avatar to IDLE
      if (this.avatar.getState() === this.avatar.STATES.SPEAKING) {
        this.avatar.setState(this.avatar.STATES.IDLE);
      }
    }

    const wasSpeakingOrPaused =
      this.lifecycleState === this.STATES.PLAYING ||
      this.lifecycleState === this.STATES.START ||
      this.lifecycleState === this.STATES.PAUSED;

    const isInterruption =
      reason === 'user_interrupted' ||
      reason === 'user_input' ||
      reason === 'interrupted' ||
      reason === 'new_utterance';

    this.lifecycleState = isInterruption ? this.STATES.INTERRUPTED : this.STATES.IDLE;

    if (wasSpeakingOrPaused && isInterruption) {
      this.emit('onSpeechInterrupted', { reason, token: previousToken });
    }

    this.emit('onSpeechEnd', { reason, token: previousToken, interrupted: isInterruption });

    if (this.activeOnComplete) {
      const cb = this.activeOnComplete;
      this.activeOnComplete = null;
      try {
        cb({ interrupted: isInterruption, reason });
      } catch {
        // Safe callback execution
      }
    }
  }

  /**
   * Vocalize text using the native Web Speech API with generation token tracking.
   * @param {string} text - Clean text to speak
   * @param {Function} onComplete - Callback invoked upon speech completion or interruption
   * @param {Object} options - Optional overrides (rate, pitch, priority)
   */
  speak(text, onComplete = null, options = {}) {
    if (!text || this.isMuted || typeof window === 'undefined' || !window.speechSynthesis) {
      if (onComplete) onComplete({ interrupted: false, reason: 'skipped_or_muted' });
      return;
    }

    // Clean markdown, symbols, and technical formatting for natural Jarvis delivery
    const cleanText = this.sanitizeForSpeech(text);
    if (!cleanText) {
      if (onComplete) onComplete({ interrupted: false, reason: 'empty_text' });
      return;
    }

    // Stop ongoing speech cleanly before starting new utterance
    this.stop('new_utterance');

    // Issue unique generation token for this utterance
    const currentToken = ++this._generationToken;
    this.activeOnComplete = onComplete;
    this.lifecycleState = this.STATES.START;

    const utterance = new SpeechSynthesisUtterance(cleanText);
    if (this.selectedVoice) {
      utterance.voice = this.selectedVoice;
    }

    // 10E.3: Jarvis pacing (authoritative 1.05 rate, 0.95 pitch)
    utterance.rate = options.rate !== undefined ? options.rate : 1.05;
    utterance.pitch = options.pitch !== undefined ? options.pitch : 0.95;

    utterance.onstart = () => {
      // Guard against stale callback from cancelled utterance
      if (currentToken !== this._generationToken) return;

      this.lifecycleState = this.STATES.PLAYING;
      this.startAmplitudeSimulation();

      if (this.avatar) {
        this.avatar.setState(this.avatar.STATES.SPEAKING);
      }

      this.emit('onSpeechStart', { text: cleanText, token: currentToken });
    };

    // 10E.2: Syllable / boundary timing hook driving canonical visemes
    utterance.onboundary = (event) => {
      if (currentToken !== this._generationToken) return;

      if (this.avatar && event.name === 'word') {
        const spokenWord = cleanText
          .substring(event.charIndex, event.charIndex + (event.charLength || 4))
          .trim()
          .toLowerCase();

        const viseme = this.classifyWordViseme(spokenWord);
        this.avatar.setViseme(viseme, 0.85);
        this.emit('onViseme', { word: spokenWord, viseme, charIndex: event.charIndex });
      }
    };

    utterance.onend = () => {
      if (currentToken !== this._generationToken) return;

      this.lifecycleState = this.STATES.COMPLETED;
      this.stopAmplitudeSimulation();

      if (this.avatar) {
        this.avatar.setAudioAmplitude(0);
        this.avatar.resetArticulation();
        if (this.avatar.getState() === this.avatar.STATES.SPEAKING) {
          this.avatar.setState(this.avatar.STATES.IDLE);
        }
      }

      this.emit('onSpeechEnd', { reason: 'completed', token: currentToken, interrupted: false });

      if (this.activeOnComplete) {
        const cb = this.activeOnComplete;
        this.activeOnComplete = null;
        try {
          cb({ interrupted: false, reason: 'completed' });
        } catch {
          // Safe callback execution
        }
      }
    };

    utterance.onerror = (err) => {
      if (currentToken !== this._generationToken) return;

      // Ignore intentional cancellations
      if (err.error === 'canceled' || err.error === 'interrupted') {
        return;
      }

      console.warn('[VoicePresentationEngine] Speech error:', err);
      this.lifecycleState = this.STATES.ERROR;
      this.stopAmplitudeSimulation();

      if (this.avatar) {
        this.avatar.setAudioAmplitude(0);
        this.avatar.resetArticulation();
        if (this.avatar.getState() === this.avatar.STATES.SPEAKING) {
          this.avatar.setState(this.avatar.STATES.IDLE);
        }
      }

      this.emit('onSpeechEnd', { reason: 'error', error: err.error, token: currentToken });

      if (this.activeOnComplete) {
        const cb = this.activeOnComplete;
        this.activeOnComplete = null;
        try {
          cb({ interrupted: true, reason: 'error', error: err.error });
        } catch {
          // Safe callback execution
        }
      }
    };

    try {
      window.speechSynthesis.speak(utterance);
    } catch (err) {
      console.warn('[VoicePresentationEngine] Speak invocation failed:', err);
      this.lifecycleState = this.STATES.ERROR;
      if (onComplete) onComplete({ interrupted: true, reason: 'invocation_failed' });
    }
  }

  /**
   * Conservative heuristic mapping from boundary words to canonical visemes:
   * 'aa' (wide/open), 'ee' (stretched), 'oh' (rounded), 'ch' (fricative/closed), 'rest'.
   */
  classifyWordViseme(word) {
    if (!word || word.length === 0) return 'rest';

    // Fricative / dental / plosive consonant beginnings
    if (/^(ch|sh|th|st|pr|tr|cr|cl|sp|sc|wh|j)/.test(word)) {
      return 'ch';
    }

    // Dominant vowel classification
    if (/[aeiouy]/.test(word)) {
      if (/a|ar|ah|au|aw/.test(word)) return 'aa';
      if (/o|u|ow|oo/.test(word)) return 'oh';
      if (/e|i|ee|ea|y/.test(word)) return 'ee';
    }

    // Short consonant cluster
    if (/^[bcdfghjklmnpqrstvwxyz]+$/.test(word)) {
      return 'ch';
    }

    return 'aa';
  }

  /**
   * Strip code blocks and format punctuation for natural conversational pauses.
   */
  sanitizeForSpeech(text) {
    return text
      .replace(/```[\s\S]*?```/g, 'Code block executed.')
      .replace(/`([^`]+)`/g, '$1')
      .replace(/https?:\/\/\S+/g, 'link')
      .replace(/\[([^\]]+)\]\([^\)]+\)/g, '$1')
      .replace(/[*_#~]/g, '')
      .replace(/--/g, '—')
      .replace(/\s+/g, ' ')
      .trim();
  }

  /**
   * Simulate audio waveform amplitude modulation while speaking.
   * Treated explicitly as an estimated articulation simulation, not raw PCM stream.
   */
  startAmplitudeSimulation() {
    this.stopAmplitudeSimulation();
    this.amplitudeIntervalId = setInterval(() => {
      if (this.isSpeaking() && this.avatar) {
        // Dynamic harmonic amplitude [0.25 - 0.85]
        const amp = 0.35 + Math.sin(Date.now() * 0.012) * 0.25 + Math.random() * 0.25;
        this.avatar.setAudioAmplitude(amp);
      }
    }, 50);
  }

  stopAmplitudeSimulation() {
    if (this.amplitudeIntervalId) {
      clearInterval(this.amplitudeIntervalId);
      this.amplitudeIntervalId = null;
    }
    if (this.avatar) {
      this.avatar.setAudioAmplitude(0);
    }
  }
}

if (typeof window !== 'undefined') {
  window.VoicePresentationEngine = VoicePresentationEngine;
}
