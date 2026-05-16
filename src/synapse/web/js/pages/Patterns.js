import { html, useState, useEffect, useCallback } from '../app.js';
import { api } from '../api.js';

function PatternDetail({ name }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get(`/api/patterns/${encodeURIComponent(name)}`)
      .then((d) => { setDetail(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [name]);

  if (loading) return html`<div class="text-muted" style="font-size:12px">Loading...</div>`;
  if (!detail) return html`<div class="text-muted" style="font-size:12px">Could not load pattern detail.</div>`;

  return html`
    <div class="pattern-detail">
      <div><span class="text-muted">Duration:</span> ${detail.duration ?? '—'}s</div>
      ${detail.layers?.length > 0 && html`
        <div style="margin-top:8px">
          <span class="text-muted">Layers:</span>
          ${detail.layers.map((l) => html`
            <div style="margin-left:12px; margin-top:4px">
              <code>${l.name}</code>
              <span class="text-muted"> (${l.blend})</span>
              ${l.axes && html`
                <span class="text-muted"> — axes: ${Object.keys(l.axes).join(', ')}</span>
              `}
            </div>
          `)}
        </div>
      `}
      ${detail.steps?.length > 0 && html`
        <div style="margin-top:8px">
          <span class="text-muted">Steps:</span>
          ${detail.steps.map((s, i) => html`
            <div style="margin-left:12px; margin-top:4px">
              ${i + 1}. ${s.pattern_name || JSON.stringify(s)}
            </div>
          `)}
        </div>
      `}
    </div>
  `;
}

function PatternItem({ pattern, onPlay, onStop }) {
  const [expanded, setExpanded] = useState(false);
  const [playing, setPlaying] = useState(false);

  const handlePlay = async (e) => {
    e.stopPropagation();
    setPlaying(true);
    try {
      await onPlay(pattern.name);
    } finally {
      setPlaying(false);
    }
  };

  const handleStop = async (e) => {
    e.stopPropagation();
    await onStop();
  };

  return html`
    <div class="pattern-item">
      <div class="pattern-item-header" onClick=${() => setExpanded(!expanded)}>
        <div>
          <div class="pattern-name">${pattern.name}</div>
          ${pattern.description && html`<div class="pattern-desc">${pattern.description}</div>`}
        </div>
        <div class="pattern-actions">
          <span class="badge ${pattern.type === 'sequence' ? 'badge-accent' : 'badge-muted'}">${pattern.type || 'leaf'}</span>
          <button class="btn btn-sm btn-primary" onClick=${handlePlay} disabled=${playing}>
            ${playing ? '▶ Playing...' : '▶ Play'}
          </button>
          <button class="btn btn-sm btn-secondary" onClick=${handleStop}>■ Stop</button>
          <span class="text-muted" style="font-size:18px">${expanded ? '▲' : '▼'}</span>
        </div>
      </div>
      ${expanded && html`<${PatternDetail} name=${pattern.name} />`}
    </div>
  `;
}

export function Patterns() {
  const [patterns, setPatterns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState('');
  const [newName, setNewName] = useState('');
  const [newPeriod, setNewPeriod] = useState('4.0');
  const [creating, setCreating] = useState(false);
  const [instance, setInstance] = useState('primary');

  const showMsg = (m) => {
    setMsg(m);
    setTimeout(() => setMsg(''), 3000);
  };

  const fetchPatterns = useCallback(async () => {
    try {
      const data = await api.get('/api/patterns');
      setPatterns(data);
    } catch (_) {}
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchPatterns();
  }, [fetchPatterns]);

  const handlePlay = async (name) => {
    try {
      await api.post('/api/patterns/play', { name, instance });
      showMsg(`Playing "${name}"`);
    } catch (e) {
      showMsg(`Error: ${e?.detail || 'Failed to play'}`);
      throw e;
    }
  };

  const handleStop = async () => {
    try {
      await api.post('/api/patterns/stop', { instance });
      showMsg('Stopped');
    } catch (e) {
      showMsg(`Error: ${e?.detail || 'Failed to stop'}`);
    }
  };

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setCreating(true);
    try {
      await api.post('/api/patterns', {
        name: newName.trim(),
        base_period: parseFloat(newPeriod) || 4.0,
      });
      showMsg(`Created "${newName}"`);
      setNewName('');
      await fetchPatterns();
    } catch (e) {
      showMsg(`Error: ${e?.detail || 'Failed to create'}`);
    } finally {
      setCreating(false);
    }
  };

  return html`
    <div class="page-header">
      <div class="flex-between">
        <div>
          <div class="page-title">Patterns</div>
          <div class="page-subtitle">Browse, play and manage patterns</div>
        </div>
        <div class="flex-center gap-8">
          <label class="form-label" style="min-width:auto">Instance:</label>
          <input
            type="text"
            value=${instance}
            onInput=${(e) => setInstance(e.target.value)}
            style="width:100px"
          />
          <button class="btn btn-secondary btn-sm" onClick=${fetchPatterns}>Refresh</button>
        </div>
      </div>
    </div>

    ${msg && html`<div class=${msg.startsWith('Error') ? 'error-msg mb-16' : 'success-msg mb-16'}>${msg}</div>`}

    ${loading ? html`<div class="text-muted">Loading patterns...</div>` : html`
      ${patterns.length === 0 ? html`
        <div class="card">
          <div class="text-muted">No patterns found. Create one below or add pattern files to the patterns directory.</div>
        </div>
      ` : patterns.map((p) => html`
        <${PatternItem}
          key=${p.name}
          pattern=${p}
          onPlay=${handlePlay}
          onStop=${handleStop}
        />
      `)}
    `}

    <hr class="divider" />

    <div class="card">
      <div class="card-title">New Pattern</div>
      <div class="form-row">
        <label class="form-label">Name</label>
        <input
          type="text"
          placeholder="my-pattern"
          value=${newName}
          onInput=${(e) => setNewName(e.target.value)}
          style="flex:1"
          onKeyDown=${(e) => e.key === 'Enter' && handleCreate()}
        />
      </div>
      <div class="form-row">
        <label class="form-label">Base Period (s)</label>
        <input
          type="number"
          step="0.5"
          min="0.1"
          value=${newPeriod}
          onInput=${(e) => setNewPeriod(e.target.value)}
          style="width:100px"
        />
      </div>
      <button class="btn btn-primary" onClick=${handleCreate} disabled=${creating || !newName.trim()}>
        ${creating ? 'Creating...' : '+ Create Pattern'}
      </button>
    </div>
  `;
}
