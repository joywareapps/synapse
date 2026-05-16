import { html, useState, useEffect, useCallback } from '../app.js';
import { api } from '../api.js';

function sensorStatus(sensor) {
  if (sensor.error) return 'error';
  if (!sensor.timestamp) return 'idle';
  const age = Date.now() / 1000 - sensor.timestamp;
  if (age > 10) return 'stale';
  return 'ok';
}

function SensorCard({ sensor }) {
  const status = sensorStatus(sensor);
  const pct = typeof sensor.value === 'number'
    ? Math.max(0, Math.min(100, sensor.value * 100)).toFixed(1)
    : null;

  const fillClass = status === 'error' ? 'danger' : status === 'stale' ? 'warning' : '';

  return html`
    <div class=${`sensor-card ${status === 'error' ? 'error' : status === 'stale' ? 'stale' : ''}`}>
      <div class="sensor-name">${sensor.name}</div>
      <div class="flex-center gap-8 mb-8">
        <div class=${`status-dot ${status === 'ok' ? 'connected' : status === 'stale' ? 'stale' : status === 'error' ? 'disconnected' : 'idle'}`}></div>
        <span class="text-muted" style="font-size:11px">${status}</span>
      </div>
      ${sensor.error ? html`
        <div class="error-msg">${sensor.error}</div>
      ` : html`
        <div class="sensor-value-large">
          ${pct !== null ? pct : '—'}
          <span class="stat-unit">%</span>
        </div>
        <div class="progress-bar">
          <div class=${`progress-fill ${fillClass}`} style=${`width:${pct || 0}%`}></div>
        </div>
      `}
      ${sensor.raw && Object.keys(sensor.raw).length > 0 && html`
        <div class="sensor-raw-fields">
          ${Object.entries(sensor.raw).map(([k, v]) => html`
            <div><span class="text-accent">${k}:</span> ${JSON.stringify(v)}</div>
          `)}
        </div>
      `}
      ${sensor.timestamp && html`
        <div class="text-muted mt-8" style="font-size:10px">
          Updated ${Math.round(Date.now() / 1000 - sensor.timestamp)}s ago
        </div>
      `}
    </div>
  `;
}

export function Sensors({ liveData }) {
  const [sensors, setSensors] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchSensors = useCallback(async () => {
    try {
      const data = await api.get('/api/sensors');
      setSensors(data);
    } catch (_) {}
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchSensors();
    const iv = setInterval(fetchSensors, 3000);
    return () => clearInterval(iv);
  }, [fetchSensors]);

  // Prefer live WS data when available
  const displaySensors = liveData?.sensors?.length > 0 ? liveData.sensors : sensors;

  return html`
    <div class="page-header">
      <div class="flex-between">
        <div>
          <div class="page-title">Sensors</div>
          <div class="page-subtitle">Live sensor readings</div>
        </div>
        <button class="btn btn-secondary btn-sm" onClick=${fetchSensors}>Refresh</button>
      </div>
    </div>

    ${loading && displaySensors.length === 0
      ? html`<div class="text-muted">Loading sensors...</div>`
      : displaySensors.length === 0
        ? html`
          <div class="card">
            <div class="text-muted">No sensors configured. Enable sensors in synapse.yaml (as5311 or heart_rate).</div>
          </div>
        `
        : html`
          <div class="card-grid">
            ${displaySensors.map((s) => html`<${SensorCard} key=${s.name} sensor=${s} />`)}
          </div>
        `}
  `;
}
