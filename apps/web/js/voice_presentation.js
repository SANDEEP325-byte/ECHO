/**
 * ECHO Voice Presentation & Speech Feedback Engine (Phase 10D.2)
 *
 * Coordinates audio feedback, speech synthesis vocalization, audio reactivity,
 * and mute/unmute states for the voice-first command center.
 * Uses 100% offline, native Web Speech APIs (₹0 cost, zero heavy dependencies).
 */

class VoicePresentationEngine {
  constructor(avatarInstance, options = {}) {
    this.avatar = avatarInstance;
    this.isMuted = false;
    this.queue = [];
    this.isSpeaking = false;
    this.selectedVoice = null;
    this.amplitudeIntervalId = null;

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
      const preferred = voices.find(v =>
        v.lang.startsWith('en') && (v.name.includes('Natural') || v.name.includes('Google') || v.name.includes('David'))
      ) || voices.find(v => v.lang.startsWith('en')) || voices[0];

      this.selectedVoice = preferred;
    };

    populateVoices();
    if (window.speechSynthesis.onvoiceschanged !== undefined) {
      window.speechSynthesis.onvoiceschanged = populateVoices;
    }
  }

  setMuted(muted) {
    this.isMuted = Boolean(muted);
    try {
      localStorage.setItem('echo_voice_muted', this.isMuted ? 'true' : 'false');
    } catch {
      // Ignored in private/sandboxed mode
    }

    if (this.isMuted && typeof window !== 'undefined' && window.speechSynthesis) {
      window.speechSynthesis.cancel();
      this.stopAmplitudeSimulation();
      this.isSpeaking = false;
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
   * Vocalize an ECHO assistant response.
   * @param {string} text - Response text to speak
   * @param {Function} onComplete - Callback when speaking finishes
   */
  speak(text, onComplete = null) {
    if (!text || this.isMuted || typeof window === 'undefined' || !window.speechSynthesis) {
      if (onComplete) onComplete();
      return;
    }

    // Clean markdown/code snippets for clean voice presentation
    const cleanText = this.sanitizeForSpeech(text);
    if (!cleanText) {
      if (onComplete) onComplete();
      return;
    }

    // Cancel any active speech to avoid lag
    window.speechSynthesis.cancel();

    const utterance = new SpeechSynthesisUtterance(cleanText);
    if (this.selectedVoice) {
      utterance.voice = this.selectedVoice;
    }
    utterance.rate = 1.05; // Slightly brisk, authoritative Jarvis pacing
    utterance.pitch = 0.95;

    utterance.onstart = () => {
      this.isSpeaking = true;
      this.startAmplitudeSimulation();
      if (this.avatar) {
        this.avatar.setState(this.avatar.STATES.SPEAKING);
      }
    };

    // Boundary hook: word/syllable timing for future phoneme lip-sync
    utterance.onboundary = (event) => {
      if (this.avatar && event.name === 'word') {
        const spokenWord = cleanText.substring(event.charIndex, event.charIndex + event.charLength);
        // Stub hook for future phoneme alignment
        this.avatar.setViseme(spokenWord.toLowerCase(), 1.0);
      }
    };

    utterance.onend = () => {
      this.isSpeaking = false;
      this.stopAmplitudeSimulation();
      if (this.avatar) {
        this.avatar.setAudioAmplitude(0);
        this.avatar.setState(this.avatar.STATES.IDLE);
      }
      if (onComplete) onComplete();
    };

    utterance.onerror = (err) => {
      console.warn('[VoicePresentationEngine] Speech error:', err);
      this.isSpeaking = false;
      this.stopAmplitudeSimulation();
      if (this.avatar) {
        this.avatar.setAudioAmplitude(0);
      }
      if (onComplete) onComplete();
    };

    try {
      window.speechSynthesis.speak(utterance);
    } catch (err) {
      console.warn('[VoicePresentationEngine] Speak invocation failed:', err);
      if (onComplete) onComplete();
    }
  }

  /**
   * Strip code blocks and technical noise for natural vocalization.
   */
  sanitizeForSpeech(text) {
    return text
      .replace(/```[\s\S]*?```/g, 'Code block executed.')
      .replace(/`([^`]+)`/g, '$1')
      .replace(/https?:\/\/\S+/g, 'link')
      .replace(/\[([^\]]+)\]\([^\)]+\)/g, '$1')
      .replace(/[*_#~]/g, '')
      .trim();
  }

  /**
   * Simulate audio waveform amplitude modulation while speaking.
   */
  startAmplitudeSimulation() {
    this.stopAmplitudeSimulation();
    this.amplitudeIntervalId = setInterval(() => {
      if (this.isSpeaking && this.avatar) {
        // Dynamic harmonic amplitude [0.25 - 0.85]
        const amp = 0.35 + Math.sin(Date.now() * 0.012) * 0.25 + (Math.random() * 0.25);
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
