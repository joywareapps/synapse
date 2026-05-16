import { html, useState, useEffect, useCallback } from '../app.js';
import { api } from '../api.js';

function AxisRow({ axis, liveValue, onSetValue }) {
  const [editing, setEditing] = useState(false);
  const [inputVal, setInputVal] = useState('');
  const [saving, setSaving] = useState(false);

  const pct = typeof liveValue === 'number'
    ? Math.max(0, Math.min(100, ((liveValue - axis.limit_min) / (axis.limit_max - axis.limit_min || 1)) * 100))
    : null;

  const displayValue = typeof liveValue === 'number'
    ? liveValue.toFixed(3)
    : '—';

  const handleClick = () => {
    if (!axis.tcode_id || !axis.enabled) return;
    setInputVal(typeof liveValue === 'number' ? liveValue.toFixed(3) : '0.5');
    setEditing(true);
  };

  const handleConfirm = async () => {
    const val = parseFloat(inputVal);
    if (isNaN(val) || val < 0 || val > 1) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await api.post(`/api/axes/${axis.tcode_id}/value`, { value: val });
      if (onSetValue) onSetValue(axis.tcode_id, val);
    } catch (_) {}
    setSaving(false);
    setEditing(false);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') handleConfirm();
    if (e.key === 'Escape') setEditing(false);
  };

  return html`
    <tr onClick=${editing ? undefined : handleClick} style=${!editing && axis.tcode_id && axis.enabled ? 'cursor:pointer' : ''}>
      <td>
        <code class="mono" style="font-size:12px">${axis.tcode_id || '—'}</code>
      </td>
      <td>${axis.name}</td>
      <td>
        ${editing ? html`
          <div class="inline-edit" onClick=${(e) => e.stopPropagation()}>
            <input
              type="number"
              step="0.01"
              min="0"
              max="1"
              value=${inputVal}
              onInput=${(e) => setInputVal(e.target.value)}
              onKeyDown=${handleKeyDown}
              style="width:80px"
              autoFocus
            />
            <button class="btn btn-sm btn-primary" onClick=${handleConfirm} disabled=${saving}>
              ${saving ? '...' : 'Set'}
            </button>
            <button class="btn btn-sm btn-secondary" onClick=${() => setEditing(false)}>×</button>
          </div>
        ` : html`<span>${displayValue}</span>`}
      </td>
      <td class="text-muted">${axis.limit_min}</td>
      <td class="text-muted">${axis.limit_max}</td>
      <td class="axis-bar-cell">
        ${pct !== null ? html`
          <div class="axis-bar" style="width:80px">
            <div class="axis-bar-fill" style=${`width:${pct.toFixed(1)}%`}></div>
          </div>
        ` : html`<span class="text-muted" style="font-size:11px">—</span>`}
      </td>
      <td>
        ${axis.enabled
          ? html`<span class="badge badge-success">enabled</span>`
          : html`<span class="badge badge-muted">disabled</span>`}
      </td>
    </tr>
  `;
}

export function Axes({ liveData }) {
  const [axes, setAxes] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchAxes = useCallback(async () => {
    try {
      const data = await api.get('/api/axes');
      setAxes(data);
    } catch (_) {}
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchAxes();
  }, [fetchAxes]);

  // WS payload sends axes as {tcode_id: float}
  const liveValues = liveData?.axes || {};

  const handleSetValue = (tcodeId, val) => {
    setAxes((prev) =>
      prev.map((a) => a.tcode_id === tcodeId ? { ...a, _live: val } : a)
    );
  };

  return html`
    <div class="page-header">
      <div class="flex-between">
        <div>
          <div class="page-title">Axes</div>
          <div class="page-subtitle">TCode axis definitions and live values. Click a row to set a value.</div>
        </div>
        <button class="btn btn-secondary btn-sm" onClick=${fetchAxes}>Refresh</button>
      </div>
    </div>

    <div class="card" style="padding:0; overflow:hidden">
      ${loading ? html`<div style="padding:20px" class="text-muted">Loading axes...</div>` : html`
        <table class="data-table">
          <thead>
            <tr>
              <th>TCode ID</th>
              <th>Name</th>
              <th>Value</th>
              <th>Min</th>
              <th>Max</th>
              <th>Level</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            ${axes.map((axis) => {
              const liveVal = liveValues[axis.tcode_id] ?? axis.current_value ?? axis._live;
              return html`<${AxisRow}
                key=${axis.tcode_id || axis.name}
                axis=${axis}
                liveValue=${liveVal}
                onSetValue=${handleSetValue}
              />`;
            })}
          </tbody>
        </table>
        ${axes.length === 0 && html`
          <div style="padding:20px" class="text-muted">No axes found. Load an INI file to configure axes.</div>
        `}
      `}
    </div>
  `;
}
