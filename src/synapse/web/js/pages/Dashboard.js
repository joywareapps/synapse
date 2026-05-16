import { html, useState, useEffect, useCallback } from '../app.js';
import { api } from '../api.js';

export function Dashboard({ wsState, liveData }) {
  const [status, setStatus] = useState(null);
  const [volume, setVolume] = useState(50);
  const [volumePending, setVolumePending] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [msg, setMsg] = useState('');

  const fetchStatus = useCallback(async () => {
    try {
      const s = await api.get('/api/status');
      setStatus(s);
    } catch (e) {
      // ignore fetch errors — ws state covers connectivity
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const iv = setInterval(fetchStatus, 5000);
    return () => clearInterval(iv);
  }, [fetchStatus]);

  // Derive active pattern from liveData or status
  const instances = liveData?.instances || status?.instances || [];
  const sensors = liveData?.sensors || [];

  const handleVolumeChange = (e) => {
    setVolume(Number(e.target.value));
  };

  const handleVolumeCommit = async () => {
    setVolumePending(true);
    try {
      await api.post('/api/volume', { value: volume / 100 });
      setMsg('Volume set');
      setTimeout(() => setMsg(''), 2000);
    } catch (e) {
      setMsg('Error setting volume');
    } finally {
      setVolumePending(false);
    }
  };

  const handleEmergencyStop = async () => {
    setStopping(true);
    try {
      await api.post('/api/emergency-stop', {});
      setMsg('Emergency stop sent');
      setTimeout(() => setMsg(''), 3000);
    } catch (e) {
      setMsg('Error sending stop');
    } finally {
      setStopping(false);
    }
  };

  const handleStop = async (instanceId) => {
    try {
      await api.post('/api/patterns/stop', { instance: instanceId });
      fetchStatus();
    } catch (e) {
      setMsg('Error stopping pattern');
    }
  };

  const wsConnected = wsState === 'connected';

  return html`
    <div class="page-header">
      <div class="page-title">Dashboard</div>
      <div class="page-subtitle">Live status and controls</div>
    </div>

    ${msg && html`<div class=${msg.startsWith('Error') ? 'error-msg mb-16' : 'success-msg mb-16'}>${msg}</div>`}

    <!-- Connection status -->
    <div class="card">
      <div class="card-title">Connection</div>
      <div class="flex-center gap-8 mb-8">
        <div class=${`status-dot ${wsConnected ? 'connected' : 'disconnected'}`}></div>
        <span>WebSocket: ${wsConnected ? 'Connected' : 'Disconnected'}</span>
      </div>
      ${instances.map((inst) => html`
        <div class="flex-center gap-8" style="margin-top:6px">
          <div class=${`status-dot ${inst.connected ? 'connected' : 'disconnected'}`}></div>
          <span>${inst.id}: ${inst.connected ? 'Connected' : 'Disconnected'}</span>
          ${inst.active_pattern ? html`
            <span class="badge badge-accent" style="margin-left:8px">${inst.active_pattern}</span>
            <button class="btn btn-sm btn-secondary" onClick=${() => handleStop(inst.id)}>Stop</button>
          ` : html`
            <span class="badge badge-muted" style="margin-left:8px">Idle</span>
          `}
        </div>
      `)}
    </div>

    <!-- Volume control -->
    <div class="card">
      <div class="card-title">Volume</div>
      <div class="volume-slider-wrap">
        <span class="text-muted">0</span>
        <input
          type="range"
          class="volume-slider"
          min="0"
          max="100"
          value=${volume}
          onInput=${handleVolumeChange}
          onMouseUp=${handleVolumeCommit}
          onTouchEnd=${handleVolumeCommit}
        />
        <span class="text-muted">100</span>
        <span class="volume-value">${volume}%</span>
      </div>
    </div>

    <!-- Emergency stop -->
    <div class="card">
      <div class="card-title">Emergency Controls</div>
      <button
        class="btn-emergency"
        onClick=${handleEmergencyStop}
        disabled=${stopping}
      >
        ${stopping ? 'Stopping...' : '⚠ Emergency Stop'}
      </button>
    </div>

    <!-- Sensor summary -->
    ${sensors.length > 0 && html`
      <div class="card">
        <div class="card-title">Sensors</div>
        <div class="card-grid">
          ${sensors.map((s) => html`
            <div class="stat-card">
              <div class="stat-label">${s.name}</div>
              ${s.error
                ? html`<div class="text-danger" style="font-size:12px">${s.error}</div>`
                : html`
                    <div class="stat-value">
                      ${typeof s.value === 'number' ? (s.value * 100).toFixed(0) : '--'}
                      <span class="stat-unit">%</span>
                    </div>
                    <div class="progress-bar">
                      <div
                        class="progress-fill"
                        style=${`width:${typeof s.value === 'number' ? (s.value * 100).toFixed(0) : 0}%`}
                      ></div>
                    </div>
                  `}
            </div>
          `)}
        </div>
      </div>
    `}

    ${sensors.length === 0 && html`
      <div class="card">
        <div class="card-title">Sensors</div>
        <div class="text-muted">No sensors active. Configure sensors in synapse.yaml.</div>
      </div>
    `}
  `;
}
