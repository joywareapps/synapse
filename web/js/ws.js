/**
 * Reconnecting WebSocket client with exponential backoff.
 */
export class ReconnectingWS {
  constructor(path, onMessage, onStateChange) {
    this._path = path;
    this._onMessage = onMessage;
    this._onStateChange = onStateChange || (() => {});
    this._ws = null;
    this._delay = 1000;
    this._maxDelay = 30000;
    this._closed = false;
    this._connect();
  }

  _buildUrl() {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const host = window.location.host;
    return `${proto}://${host}${this._path}`;
  }

  _connect() {
    if (this._closed) return;
    const url = this._buildUrl();
    try {
      this._ws = new WebSocket(url);
    } catch (err) {
      this._scheduleReconnect();
      return;
    }

    this._ws.onopen = () => {
      this._delay = 1000;
      this._onStateChange('connected');
    };

    this._ws.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data);
        this._onMessage(data);
      } catch (_) {
        this._onMessage(evt.data);
      }
    };

    this._ws.onerror = () => {
      // onclose will fire after onerror
    };

    this._ws.onclose = () => {
      this._onStateChange('disconnected');
      this._scheduleReconnect();
    };
  }

  _scheduleReconnect() {
    if (this._closed) return;
    setTimeout(() => this._connect(), this._delay);
    this._delay = Math.min(this._delay * 2, this._maxDelay);
  }

  send(data) {
    if (this._ws && this._ws.readyState === WebSocket.OPEN) {
      this._ws.send(typeof data === 'string' ? data : JSON.stringify(data));
    }
  }

  close() {
    this._closed = true;
    if (this._ws) {
      this._ws.close();
      this._ws = null;
    }
  }
}
