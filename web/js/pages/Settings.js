import { html, useState, useEffect, useCallback } from '../app.js';
import { api } from '../api.js';

function ConfigValue({ v }) {
  if (v === null || v === undefined) return html`<span class="text-muted">null</span>`;
  if (typeof v === 'boolean') return html`<span class=${v ? 'text-success' : 'text-danger'}>${String(v)}</span>`;
  if (typeof v === 'number') return html`<span class="text-warning">${v}</span>`;
  if (typeof v === 'string') return html`<span class="text-accent">"${v}"</span>`;
  return html`<span>${JSON.stringify(v)}</span>`;
}

function ConfigSection({ data, depth }) {
  if (!data || typeof data !== 'object') return html`<${ConfigValue} v=${data} />`;
  return html`
    <div style=${`margin-left:${depth * 16}px`}>
      ${Object.entries(data).map(([k, v]) => html`
        <div style="margin:2px 0" class="mono" style="font-size:12px; line-height:1.8">
          <span class="text-accent">${k}:</span>${' '}
          ${v !== null && typeof v === 'object'
            ? html`<${ConfigSection} data=${v} depth=${depth + 1} />`
            : html`<${ConfigValue} v=${v} />`}
        </div>
      `)}
    </div>
  `;
}

function HealthCheck() {
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(false);

  const run = async () => {
    setLoading(true);
    try {
      const d = await api.get('/api/setup/check');
      setHealth(d);
    } catch (e) {
      setHealth({ error: String(e?.detail || e) });
    } finally {
      setLoading(false);
    }
  };

  return html`
    <div class="card">
      <div class="flex-between mb-16">
        <div class="card-title mb-0">Health Check</div>
        <button class="btn btn-secondary btn-sm" onClick=${run} disabled=${loading}>
          ${loading ? 'Checking...' : 'Run Check'}
        </button>
      </div>
      ${health && html`
        ${health.error && html`<div class="error-msg">${health.error}</div>`}
        ${health.restim && html`
          <div class="health-section">
            <div class="card-title">Restim</div>
            ${health.restim.map((inst) => html`
              <div class="health-row">
                <div class=${`status-dot ${inst.tcode_reachable && inst.rest_reachable ? 'connected' : 'disconnected'}`}></div>
                <span class="mono">${inst.id}</span>
                <span class="text-muted">TCode ${inst.tcode_reachable ? '✓' : '✗'} REST ${inst.rest_reachable ? '✓' : '✗'}</span>
              </div>
            `)}
          </div>
        `}
        ${health.ini && html`
          <div class="health-section">
            <div class="card-title">INI</div>
            <div class="health-row">
              <div class=${`status-dot ${health.ini.exists ? 'connected' : 'disconnected'}`}></div>
              <span class="mono">${health.ini.path}</span>
              <span class=${`badge ${health.ini.exists ? 'badge-success' : 'badge-danger'}`}>
                ${health.ini.exists ? 'found' : 'not found'}
              </span>
            </div>
          </div>
        `}
        ${health.llm_providers?.length > 0 && html`
          <div class="health-section">
            <div class="card-title">LLM Providers</div>
            ${health.llm_providers.map((p) => html`
              <div class="health-row">
                <div class=${`status-dot ${p.reachable ? 'connected' : 'disconnected'}`}></div>
                <span>${p.name}</span>
                ${p.models?.length > 0 && html`
                  <span class="text-muted text-sm">${p.models.join(', ')}</span>
                `}
              </div>
            `)}
          </div>
        `}
      `}
    </div>
  `;
}

export function Settings() {
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [reloading, setReloading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [msg, setMsg] = useState('');
  const [fileInputKey, setFileInputKey] = useState(0);

  const showMsg = (m) => {
    setMsg(m);
    setTimeout(() => setMsg(''), 4000);
  };

  const fetchConfig = useCallback(async () => {
    try {
      const d = await api.get('/api/config');
      setConfig(d);
    } catch (_) {}
    setLoading(false);
  }, []);

  useEffect(() => { fetchConfig(); }, [fetchConfig]);

  const handleReloadIni = async () => {
    setReloading(true);
    try {
      const res = await api.post('/api/config/reload-ini', {});
      showMsg(`INI reloaded — ${res.axis_count} axes`);
      await fetchConfig();
    } catch (e) {
      showMsg(`Error: ${e?.detail || 'Failed to reload INI'}`);
    } finally {
      setReloading(false);
    }
  };

  const handleUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    const fd = new FormData();
    fd.append('file', file);
    try {
      const res = await api.upload('/api/config/upload-ini', fd);
      showMsg(`Uploaded — ${res.axis_count} axes loaded`);
      setFileInputKey((k) => k + 1);
    } catch (er) {
      showMsg(`Error: ${er?.detail || 'Upload failed'}`);
    } finally {
      setUploading(false);
    }
  };

  return html`
    <div class="page-header">
      <div class="page-title">Settings</div>
      <div class="page-subtitle">Configuration and diagnostics</div>
    </div>

    ${msg && html`<div class=${msg.startsWith('Error') ? 'error-msg mb-16' : 'success-msg mb-16'}>${msg}</div>`}

    <div class="card">
      <div class="flex-between mb-16">
        <div class="card-title mb-0">INI File</div>
        <div class="flex-center gap-8">
          <button class="btn btn-secondary btn-sm" onClick=${handleReloadIni} disabled=${reloading}>
            ${reloading ? 'Reloading...' : 'Reload from disk'}
          </button>
        </div>
      </div>
      <div class="form-group">
        <label>Upload new restim.ini</label>
        <input
          key=${fileInputKey}
          type="file"
          accept=".ini"
          onInput=${handleUpload}
          disabled=${uploading}
          style="width:100%"
        />
        ${uploading && html`<div class="text-muted mt-8" style="font-size:12px">Uploading...</div>`}
      </div>
    </div>

    <${HealthCheck} />

    <div class="card">
      <div class="flex-between mb-16">
        <div class="card-title mb-0">Current Config</div>
        <button class="btn btn-secondary btn-sm" onClick=${fetchConfig}>Refresh</button>
      </div>
      ${loading
        ? html`<div class="text-muted">Loading config...</div>`
        : config
          ? html`<div class="config-tree"><${ConfigSection} data=${config} depth=${0} /></div>`
          : html`<div class="error-msg">Could not load config</div>`}
    </div>
  `;
}
