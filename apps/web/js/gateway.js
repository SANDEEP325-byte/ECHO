/**
 * ECHO Live Interface Gateway WebSocket Client (Phase 10C.1 / 10C.2)
 *
 * Connects the Command Center UI to the local /ws/live event gateway.
 * Dispatches canonical actions through ECHOBrain and handles state streaming.
 */

class GatewayClient {
  constructor(options = {}) {
    this.sessionId = options.sessionId || null;
    this.reconnectAttempts = 0;
    this.maxReconnectDelay = 5000;
    this.ws = null;
    this.isManualClose = false;
    this.pingIntervalId = null;

    this.listeners = {
      open: [],
      close: [],
      error: [],
      idle: [],
      listening: [],
      thinking: [],
      speaking: [],
      alert: [],
      confirmation_required: [],
      action_result: [],
      any: [],
    };
  }

  /**
   * Determine WebSocket URL based on current browser window location.
   */
  getWebSocketUrl() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    let url = `${protocol}//${host}/ws/live`;
    if (this.sessionId) {
      url += `?session_id=${encodeURIComponent(this.sessionId)}`;
    }
    return url;
  }

  /**
   * Connect to the local WebSocket gateway.
   */
  connect() {
    this.isManualClose = false;
    const url = this.getWebSocketUrl();

    try {
      this.ws = new WebSocket(url);
    } catch (err) {
      console.error('[GatewayClient] Failed to create WebSocket:', err);
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.reconnectAttempts = 0;
      this.startHeartbeat();
      this.emit('open');
    };

    this.ws.onclose = (event) => {
      this.stopHeartbeat();
      this.emit('close', event);
      if (!this.isManualClose) {
        this.scheduleReconnect();
      }
    };

    this.ws.onerror = (err) => {
      this.emit('error', err);
    };

    this.ws.onmessage = (event) => {
      this.handleIncomingMessage(event.data);
    };
  }

  /**
   * Parse and dispatch incoming server event.
   */
  handleIncomingMessage(rawText) {
    try {
      const data = JSON.parse(rawText);

      // Cache assigned session_id from server handshake
      if (data.session_id && !this.sessionId) {
        this.sessionId = data.session_id;
      }

      const eventType = data.event_type;
      this.emit('any', data);

      if (eventType && this.listeners[eventType]) {
        this.emit(eventType, data.payload, data);
      }
    } catch (err) {
      console.error('[GatewayClient] Failed to parse message JSON:', err);
    }
  }

  /**
   * Send JSON payload to gateway if connected.
   */
  send(messageObj) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.warn('[GatewayClient] WebSocket not open; cannot send:', messageObj);
      return false;
    }

    try {
      this.ws.send(JSON.stringify(messageObj));
      return true;
    } catch (err) {
      console.error('[GatewayClient] Send error:', err);
      return false;
    }
  }

  /**
   * Send user conversational input to ECHOBrain.
   * @param {string} text - User prompt
   */
  sendUserInput(text) {
    return this.send({
      action: 'user_input',
      user_input: text,
      session_id: this.sessionId,
    });
  }

  /**
   * Authorize a pending high-risk action through ECHOBrain.confirm_action.
   * @param {string} actionId - Target pending action ID
   */
  confirmAction(actionId) {
    return this.send({
      action: 'confirm_action',
      action_id: actionId,
      session_id: this.sessionId,
    });
  }

  /**
   * Cancel a pending action through ECHOBrain.cancel_action.
   * @param {string} actionId - Target pending action ID
   */
  cancelAction(actionId) {
    return this.send({
      action: 'cancel_action',
      action_id: actionId,
      session_id: this.sessionId,
    });
  }

  /**
   * Request state synchronization from live gateway.
   */
  queryState() {
    return this.send({
      action: 'state_query',
      session_id: this.sessionId,
    });
  }

  /**
   * Send heartbeat ping.
   */
  ping() {
    return this.send({ action: 'ping' });
  }

  startHeartbeat() {
    this.stopHeartbeat();
    this.pingIntervalId = setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ping();
      }
    }, 25000);
  }

  stopHeartbeat() {
    if (this.pingIntervalId) {
      clearInterval(this.pingIntervalId);
      this.pingIntervalId = null;
    }
  }

  scheduleReconnect() {
    this.reconnectAttempts++;
    const delay = Math.min(1000 * Math.pow(1.5, this.reconnectAttempts), this.maxReconnectDelay);
    console.log(`[GatewayClient] Reconnecting in ${Math.round(delay)}ms (attempt ${this.reconnectAttempts})...`);
    setTimeout(() => {
      if (!this.isManualClose) {
        this.connect();
      }
    }, delay);
  }

  disconnect() {
    this.isManualClose = true;
    this.stopHeartbeat();
    if (this.ws) {
      this.ws.close();
    }
  }

  on(event, callback) {
    if (this.listeners[event]) {
      this.listeners[event].push(callback);
    }
  }

  emit(event, ...args) {
    if (this.listeners[event]) {
      this.listeners[event].forEach(cb => {
        try {
          cb(...args);
        } catch (err) {
          console.error(`[GatewayClient] Error in "${event}" listener:`, err);
        }
      });
    }
  }
}

if (typeof window !== 'undefined') {
  window.GatewayClient = GatewayClient;
}
