import { html, useState, useEffect, useCallback } from '../app.js';
import { api } from '../api.js';

export function Dashboard({ wsState, liveData }) {
  const [status, setStatus] = useState(null);
  const [volume, setVolume] = useState(50);
  const [volumePending, setVolumePending] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [restimBusy, setRestimBusy] = useState(false);
  const [msg, setMsg] = useState('');

  const showMsg = (m) => { setMsg(m); setTimeout(() => setMsg(''), 3000); };

  const fetchStatus = useCallback(async () => {
    try {
      const s = await api.get('/api/status');
      setStatus(s);
    } catch (_) {}
  }, []);

  useEffect(() => {
    fetchStatus();
    const iv = setInterval(fetchStatus, 5000);
    return () => clearInterval(iv);
  }, [fetchStatus]);

  // WS now includes instances; fall back to REST poll
  const instances = liveData?.instances || status?.instances || [];
  const sensors = liveData?.sensors || [];

  const handleVolumeCommit = async (e) => {
    const val = Number(e.target.value);
    setVolume(val);
    setVolumePending(true);
    try {
      await api.post('/api/volume', { value: val / 100 });
    } catch (_) {
      showMsg('Error setting volume');
    } finally {
      setVolumePending(false);
    }
  };

  const handleEmergencyStop = async () => {
    setStopping(true);
    try {
      await api.post('/api/emergency-stop', {});
      showMsg('Emergency stop sent');
    } catch (_) {
      showMsg('Error sending stop');
    } finally {
      setStopping(false);
    }
  };

  const handlePatternStop = async (instanceId) => {
    try {
      await api.post('/api/patterns/stop', { instance: instanceId });
      fetchStatus();
    } catch (_) {
      showMsg('Error stopping pattern');
    }
  };

  const handleRestimStart = async () => {
    setRestimBusy(true);
    try {
      await api.post('/api/restim/start', {});
      showMsg('Restim started');
    } catch (_) {
      showMsg('Error starting Restim');
    } finally {
      setRestimBusy(false);
    }
  };

  const handleRestimStop = async () => {
    setRestimBusy(true);
    try {
      await api.post('/api/restim/stop', {});
      showMsg('Restim stopped');
    } catch (_) {
      showMsg('Error stopping Restim');
    } finally {
      setRestimBusy(false);
    }
  };

  const wsConnected = wsState === 'connected';

  return html`
    <div class="page-header">
      <div class="page-title">Dashboard</div>
      <div class="page-subtitle">Live status and controls</div>
    </div>

    ${msg && html`<div class=${msg.startsWith('Error') ? 'error-msg mb-16' : 'success-msg mb-16'}>${msg}</div>`}

    <!-- Instance status + Restim controls -->
    <div class="card">
      <div class="card-title">Restim</div>
      ${instances.length === 0 && html`
        <div class="flex-center gap-8 mb-12">
          <div class=${`status-dot ${wsConnected ? 'connected' : 'disconnected'}`}></div>
          <span class="text-muted">Waiting for connection…</span>
        </div>
      `}
      ${instances.map((inst) => html`
        <div style="margin-bottom:12px">
          <div class="flex-between" style="margin-bottom:8px">
            <div class="flex-center gap-8">
              <div class=${`status-dot ${inst.connected ? 'connected' : 'disconnected'}`}></div>
              <span style="font-weight:500">${inst.id}</span>
              ${inst.restim_playing
                ? html`<span class="badge badge-success">playing</span>`
                : html`<span class="badge badge-muted">stopped</span>`}
              ${inst.active_pattern && html`
                <span class="badge badge-accent">${inst.active_pattern}</span>
                <button class="btn btn-sm btn-secondary" onClick=${() => handlePatternStop(inst.id)}>■ Stop pattern</button>
              `}
            </div>
          </div>
          <div class="flex-center gap-8">
            <button
              class="btn btn-success btn-sm"
              onClick=${handleRestimStart}
              disabled=${restimBusy || inst.restim_playing}
            >▶ Start Restim</button>
            <button
              class="btn btn-danger btn-sm"
              onClick=${handleRestimStop}
              disabled=${restimBusy || !inst.restim_playing}
            >■ Stop Restim</button>
            ${inst.restim_error && html`
              <span class="text-danger" style="font-size:11px">${inst.restim_error}</span>
            `}
          </div>
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
          onInput=${(e) => setVolume(Number(e.target.value))}
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
      <button class="btn-emergency" onClick=${handleEmergencyStop} disabled=${stopping}>
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
                      <div class="progress-fill" style=${`width:${typeof s.value === 'number' ? (s.value * 100).toFixed(0) : 0}%`}></div>
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
