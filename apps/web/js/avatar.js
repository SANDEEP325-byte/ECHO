/**
 * ECHO Modular Avatar Core & Renderer System (Phase 10D.1 & 10D.3)
 *
 * Provides a modular, pluggable architecture for the futuristic avatar:
 * - BaseAvatarRenderer: Abstract interface for all current and future renderers
 *   (Holographic Core, 2D SVG, 3D WebGL / Three.js, skeletal rig).
 * - HolographicCoreRenderer: The default high-performance 60fps canvas visualizer.
 * - AvatarCore: Authoritative state controller coordinating states (IDLE, LISTENING,
 *   THINKING, SPEAKING, ALERT, ERROR, CONFIRMATION) and delegating to active renderer.
 */

/**
 * Abstract Base Class for Avatar Renderers.
 * Future 2D/3D character models inherit from this interface.
 */
class BaseAvatarRenderer {
  constructor(canvasElement) {
    this.canvas = canvasElement;
    this.ctx = canvasElement ? canvasElement.getContext('2d') : null;
  }

  init() {}
  destroy() {}
  render(state, timestamp, metrics) {}

  /**
   * Hook for phoneme / viseme timing data (Phase 10D.2+).
   */
  setViseme(viseme, weight = 1.0) {}

  /**
   * Hook for facial expressions (e.g. neutral, focused, alert).
   */
  setExpression(expression, intensity = 1.0) {}

  /**
   * Hook for body gestures or movement triggers.
   */
  triggerGesture(gesture) {}
}

/**
 * Default Holographic Reactor Core Visualizer (Canvas 2D / 60 FPS).
 */
class HolographicCoreRenderer extends BaseAvatarRenderer {
  constructor(canvasElement) {
    super(canvasElement);
    this.rotationAngle = 0;
    this.pulsePhase = 0;

    this.themeColors = {
      idle: { primary: '#00f0ff', secondary: '#0066ff', core: 'rgba(0, 240, 255, 0.4)' },
      listening: { primary: '#0077ff', secondary: '#00d4ff', core: 'rgba(0, 119, 255, 0.6)' },
      thinking: { primary: '#a855f7', secondary: '#00f0ff', core: 'rgba(168, 85, 247, 0.6)' },
      speaking: { primary: '#00ff88', secondary: '#00f0ff', core: 'rgba(0, 255, 136, 0.6)' },
      alert: { primary: '#ffb700', secondary: '#ff6600', core: 'rgba(255, 183, 0, 0.7)' },
      error: { primary: '#ff003c', secondary: '#990022', core: 'rgba(255, 0, 60, 0.7)' },
      confirmation: { primary: '#ffb700', secondary: '#ff003c', core: 'rgba(255, 183, 0, 0.7)' },
    };
  }

  render(state, timestamp, metrics = {}) {
    if (!this.ctx || !this.canvas) return;

    const width = this.canvas.width;
    const height = this.canvas.height;
    const centerX = width / 2;
    const centerY = height / 2;
    const colors = this.themeColors[state] || this.themeColors.idle;
    const audioAmp = metrics.audioAmplitude || 0;

    this.ctx.clearRect(0, 0, width, height);

    let speed = 0.015;
    let pulseSpeed = 0.04;
    let coreRadiusMultiplier = 1.0;

    if (state === 'listening') {
      speed = 0.03;
      pulseSpeed = 0.08;
      coreRadiusMultiplier = 1.1 + audioAmp * 0.4;
    } else if (state === 'thinking') {
      speed = 0.06;
      pulseSpeed = 0.12;
      coreRadiusMultiplier = 1.0 + Math.sin(timestamp * 0.01) * 0.15;
    } else if (state === 'speaking') {
      speed = 0.025;
      pulseSpeed = 0.07;
      coreRadiusMultiplier = 1.15 + audioAmp * 0.5 + Math.sin(timestamp * 0.008) * 0.1;
    } else if (state === 'alert' || state === 'confirmation') {
      speed = 0.04;
      pulseSpeed = 0.15;
      coreRadiusMultiplier = 1.2 + Math.sin(timestamp * 0.015) * 0.1;
    } else if (state === 'error') {
      speed = 0.01;
      coreRadiusMultiplier = 0.95;
    }

    this.rotationAngle += speed;
    this.pulsePhase += pulseSpeed;

    const baseRadius = 70 * coreRadiusMultiplier;
    const pulseOffset = Math.sin(this.pulsePhase) * 6;

    // 1. Outer Orbiting Energy Particles
    this.drawParticles(centerX, centerY, baseRadius + 60, colors.primary);

    // 2. Segmented Outer Gyro Ring
    this.drawSegmentedRing(centerX, centerY, baseRadius + 45, 12, this.rotationAngle, colors.primary);

    // 3. Counter-Rotating Inner Tech Ring
    this.drawSegmentedRing(centerX, centerY, baseRadius + 25, 8, -this.rotationAngle * 1.5, colors.secondary);

    // 4. Oscillating Waveform Nodes
    this.drawWaveformNodes(centerX, centerY, baseRadius + 10, colors.primary, audioAmp);

    // 5. Central Glowing Core
    const gradient = this.ctx.createRadialGradient(
      centerX, centerY, 5,
      centerX, centerY, baseRadius + pulseOffset
    );
    gradient.addColorStop(0, '#ffffff');
    gradient.addColorStop(0.3, colors.primary);
    gradient.addColorStop(0.7, colors.core);
    gradient.addColorStop(1, 'rgba(0, 0, 0, 0)');

    this.ctx.beginPath();
    this.ctx.arc(centerX, centerY, baseRadius + pulseOffset, 0, Math.PI * 2);
    this.ctx.fillStyle = gradient;
    this.ctx.fill();

    // 6. Central Singularity Node
    this.ctx.beginPath();
    this.ctx.arc(centerX, centerY, 16 + Math.abs(pulseOffset * 0.5), 0, Math.PI * 2);
    this.ctx.fillStyle = '#ffffff';
    this.ctx.shadowColor = colors.primary;
    this.ctx.shadowBlur = 20;
    this.ctx.fill();
    this.ctx.shadowBlur = 0;
  }

  drawSegmentedRing(cx, cy, radius, segments, angle, color) {
    const step = (Math.PI * 2) / segments;
    const arcLen = step * 0.6;

    this.ctx.save();
    this.ctx.strokeStyle = color;
    this.ctx.lineWidth = 2.5;

    for (let i = 0; i < segments; i++) {
      const startAngle = angle + i * step;
      this.ctx.beginPath();
      this.ctx.arc(cx, cy, radius, startAngle, startAngle + arcLen);
      this.ctx.stroke();
    }
    this.ctx.restore();
  }

  drawWaveformNodes(cx, cy, radius, color, audioAmp = 0) {
    const count = 16;
    this.ctx.save();
    this.ctx.fillStyle = color;

    for (let i = 0; i < count; i++) {
      const angle = (Math.PI * 2 / count) * i + (this.rotationAngle * 0.5);
      const wave = Math.sin(this.pulsePhase + i) * (5 + audioAmp * 15);
      const r = radius + wave;
      const x = cx + Math.cos(angle) * r;
      const y = cy + Math.sin(angle) * r;

      this.ctx.beginPath();
      this.ctx.arc(x, y, 2.5 + audioAmp * 2, 0, Math.PI * 2);
      this.ctx.fill();
    }
    this.ctx.restore();
  }

  drawParticles(cx, cy, maxRadius, color) {
    const particleCount = 8;
    this.ctx.save();
    this.ctx.fillStyle = color;
    this.ctx.globalAlpha = 0.5;

    for (let i = 0; i < particleCount; i++) {
      const angle = (Math.PI * 2 / particleCount) * i - (this.rotationAngle * 0.8);
      const dist = maxRadius + Math.cos(this.pulsePhase * 0.5 + i) * 12;
      const x = cx + Math.cos(angle) * dist;
      const y = cy + Math.sin(angle) * dist;

      this.ctx.beginPath();
      this.ctx.arc(x, y, 2, 0, Math.PI * 2);
      this.ctx.fill();
    }
    this.ctx.restore();
  }
}

/**
 * Authoritative Avatar State Controller.
 */
class AvatarCore {
  constructor(canvasElement, options = {}) {
    this.canvas = canvasElement;

    // Canonical Avatar States
    this.STATES = {
      IDLE: 'idle',
      LISTENING: 'listening',
      THINKING: 'thinking',
      SPEAKING: 'speaking',
      ALERT: 'alert',
      ERROR: 'error',
      CONFIRMATION: 'confirmation',
    };

    this.currentState = this.STATES.IDLE;
    this.audioAmplitude = 0;
    this.animationFrameId = null;

    // Modular Renderer Selection (Defaults to HolographicCoreRenderer)
    this.renderer = options.renderer || new HolographicCoreRenderer(this.canvas);
    this.renderer.init();

    // Extensible Hooks
    this.hooks = {
      onStateChange: [],
      onVisemeUpdate: [],
      onExpressionUpdate: [],
      onGestureTrigger: [],
    };

    if (this.canvas) {
      this.startRenderLoop();
    }
  }

  /**
   * Swap the active avatar renderer (e.g. to a 3D or SVG driver in future phases).
   * @param {BaseAvatarRenderer} newRenderer
   */
  setRenderer(newRenderer) {
    if (this.renderer && typeof this.renderer.destroy === 'function') {
      this.renderer.destroy();
    }
    this.renderer = newRenderer;
    if (this.renderer && typeof this.renderer.init === 'function') {
      this.renderer.init();
    }
  }

  getRenderer() {
    return this.renderer;
  }

  setState(newState) {
    if (!Object.values(this.STATES).includes(newState)) {
      console.warn(`[AvatarCore] Unknown state "${newState}", defaulting to IDLE.`);
      newState = this.STATES.IDLE;
    }

    const oldState = this.currentState;
    this.currentState = newState;

    this.hooks.onStateChange.forEach(callback => {
      try {
        callback(oldState, newState);
      } catch (err) {
        console.error('[AvatarCore] Hook error onStateChange:', err);
      }
    });
  }

  getState() {
    return this.currentState;
  }

  setAudioAmplitude(level) {
    this.audioAmplitude = Math.max(0, Math.min(1, level));
  }

  getAudioAmplitude() {
    return this.audioAmplitude;
  }

  setViseme(viseme, weight = 1.0) {
    if (this.renderer) {
      this.renderer.setViseme(viseme, weight);
    }
    this.hooks.onVisemeUpdate.forEach(cb => cb(viseme, weight));
  }

  setExpression(expression, intensity = 1.0) {
    if (this.renderer) {
      this.renderer.setExpression(expression, intensity);
    }
    this.hooks.onExpressionUpdate.forEach(cb => cb(expression, intensity));
  }

  triggerGesture(gesture) {
    if (this.renderer) {
      this.renderer.triggerGesture(gesture);
    }
    this.hooks.onGestureTrigger.forEach(cb => cb(gesture));
  }

  on(event, callback) {
    if (this.hooks[event]) {
      this.hooks[event].push(callback);
    }
  }

  startRenderLoop() {
    const render = (timestamp) => {
      if (this.renderer) {
        this.renderer.render(this.currentState, timestamp, {
          audioAmplitude: this.audioAmplitude,
        });
      }
      this.animationFrameId = requestAnimationFrame(render);
    };
    this.animationFrameId = requestAnimationFrame(render);
  }

  stopRenderLoop() {
    if (this.animationFrameId) {
      cancelAnimationFrame(this.animationFrameId);
      this.animationFrameId = null;
    }
  }
}

if (typeof window !== 'undefined') {
  window.BaseAvatarRenderer = BaseAvatarRenderer;
  window.HolographicCoreRenderer = HolographicCoreRenderer;
  window.AvatarCore = AvatarCore;
}
