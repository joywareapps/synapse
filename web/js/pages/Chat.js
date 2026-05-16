import { html, useState, useEffect, useRef, useCallback } from '../app.js';
import { api } from '../api.js';
import { ReconnectingWS } from '../ws.js';

function ToolCallBlock({ call }) {
  return html`
    <details class="tool-call-block">
      <summary>Tool: ${call.name || call.function?.name || 'unknown'}</summary>
      <pre>${JSON.stringify(call.arguments || call.function?.arguments || call, null, 2)}</pre>
    </details>
  `;
}

function ChatMessage({ msg }) {
  const isUser = msg.role === 'user';
  const isAssistant = msg.role === 'assistant';
  const isToolCall = msg.role === 'tool' || msg.type === 'tool_call';

  if (isToolCall || (msg.tool_calls && msg.tool_calls.length > 0)) {
    return html`
      <div style="align-self:flex-start; width:100%; max-width:100%">
        ${(msg.tool_calls || []).map((tc, i) => html`<${ToolCallBlock} key=${i} call=${tc} />`)}
        ${isToolCall && html`<${ToolCallBlock} call=${msg} />`}
      </div>
    `;
  }

  const content = msg.content || '';

  return html`
    <div class=${`chat-message ${isUser ? 'user' : 'assistant'}`}>
      ${content}
    </div>
  `;
}

export function Chat() {
  const [providers, setProviders] = useState([]);
  const [selectedModel, setSelectedModel] = useState('');
  const [selectedProvider, setSelectedProvider] = useState('');
  const [profileName, setProfileName] = useState('');
  const [message, setMessage] = useState('');
  const [history, setHistory] = useState([]);
  const [sending, setSending] = useState(false);
  const [loopRunning, setLoopRunning] = useState(false);
  const [loopMode, setLoopMode] = useState('observe');
  const [loopInterval, setLoopInterval] = useState(30);
  const [loopTicks, setLoopTicks] = useState(0);
  const [agentWs, setAgentWs] = useState(null);
  const [msg, setMsg] = useState('');
  const messagesEndRef = useRef(null);

  const showMsg = (m) => { setMsg(m); setTimeout(() => setMsg(''), 4000); };

  // Fetch providers
  useEffect(() => {
    api.get('/api/agent/providers')
      .then((ps) => {
        setProviders(ps);
        if (ps.length > 0) {
          setSelectedProvider(ps[0].base_url);
          const models = ps[0].tool_capable_models?.length > 0
            ? ps[0].tool_capable_models
            : ps[0].models || [];
          setSelectedModel(models[0] || '');
        }
      })
      .catch(() => {});

    // Fetch existing history
    api.get('/api/agent/history')
      .then((h) => setHistory(h))
      .catch(() => {});

    // Fetch loop status
    api.get('/api/agent/loop/status')
      .then((s) => {
        setLoopRunning(s.running);
        setLoopTicks(s.tick_count || 0);
        if (s.mode) setLoopMode(s.mode);
        if (s.interval_s) setLoopInterval(s.interval_s);
      })
      .catch(() => {});
  }, []);

  // Scroll to bottom when history changes
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [history]);

  // Connect to /ws/agent for streaming
  useEffect(() => {
    const ws = new ReconnectingWS('/ws/agent', (data) => {
      if (data?.type === 'message' || data?.role) {
        setHistory((prev) => [...prev, data]);
      } else if (data?.type === 'loop_tick') {
        setLoopTicks((t) => t + 1);
      } else if (data?.type === 'loop_status') {
        setLoopRunning(data.running);
      }
    });
    setAgentWs(ws);
    return () => ws.close();
  }, []);

  const handleSend = async () => {
    if (!message.trim() || sending) return;
    const userMsg = message.trim();
    setMessage('');
    setSending(true);

    // Optimistically add user message
    setHistory((prev) => [...prev, { role: 'user', content: userMsg }]);

    try {
      const resp = await api.post('/api/agent/chat', {
        message: userMsg,
        profile_name: profileName || undefined,
      });
      if (resp.response) {
        setHistory((prev) => [...prev, { role: 'assistant', content: resp.response }]);
      }
    } catch (e) {
      showMsg(`Error: ${e?.detail || 'Send failed'}`);
    } finally {
      setSending(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleClear = async () => {
    try {
      await api.delete('/api/agent/history');
      setHistory([]);
      showMsg('History cleared');
    } catch (_) {}
  };

  const handleLoopToggle = async () => {
    if (loopRunning) {
      try {
        await api.post('/api/agent/loop/stop', {});
        setLoopRunning(false);
        showMsg('Loop stopped');
      } catch (e) {
        showMsg(`Error: ${e?.detail || 'Failed'}`);
      }
    } else {
      try {
        await api.post('/api/agent/loop/start', {
          model: selectedModel,
          provider_url: selectedProvider,
          interval_s: loopInterval,
          mode: loopMode,
          profile_name: profileName || undefined,
        });
        setLoopRunning(true);
        showMsg('Loop started');
      } catch (e) {
        showMsg(`Error: ${e?.detail || 'Failed to start loop'}`);
      }
    }
  };

  const allModels = providers.flatMap((p) =>
    (p.tool_capable_models?.length ? p.tool_capable_models : p.models || [])
      .map((m) => ({ provider: p.base_url, model: m }))
  );

  return html`
    <div class="page-header">
      <div class="page-title">Chat</div>
      <div class="page-subtitle">Agent conversation and autonomous loop</div>
    </div>

    ${msg && html`<div class=${msg.startsWith('Error') ? 'error-msg mb-16' : 'success-msg mb-16'}>${msg}</div>`}

    <!-- Configuration -->
    <div class="card">
      <div class="card-title">Agent Config</div>
      <div class="form-row">
        <label class="form-label">Model</label>
        ${allModels.length > 0 ? html`
          <select
            value=${selectedModel}
            onChange=${(e) => {
              const opt = allModels.find((m) => m.model === e.target.value);
              setSelectedModel(e.target.value);
              if (opt) setSelectedProvider(opt.provider);
            }}
          >
            ${allModels.map(({ model }) => html`<option value=${model}>${model}</option>`)}
          </select>
        ` : html`
          <input
            type="text"
            placeholder="No models found — enter manually"
            value=${selectedModel}
            onInput=${(e) => setSelectedModel(e.target.value)}
            style="flex:1"
          />
        `}
      </div>
      <div class="form-row">
        <label class="form-label">Profile</label>
        <input
          type="text"
          placeholder="optional profile name"
          value=${profileName}
          onInput=${(e) => setProfileName(e.target.value)}
          style="flex:1"
        />
      </div>
    </div>

    <!-- Loop controls -->
    <div class="card">
      <div class="card-title">Autonomous Loop</div>
      <div class="loop-controls">
        <div class="flex-center gap-8">
          <div class=${`status-dot ${loopRunning ? 'connected' : 'idle'}`}></div>
          <span class="badge ${loopRunning ? 'badge-success' : 'badge-muted'}">
            ${loopRunning ? 'Running' : 'Stopped'}
          </span>
          ${loopRunning && html`<span class="text-muted">Tick ${loopTicks}</span>`}
        </div>
        <div class="flex-center gap-8">
          <label class="text-muted" style="font-size:12px">Mode:</label>
          <select value=${loopMode} onChange=${(e) => setLoopMode(e.target.value)}>
            <option value="observe">Observe</option>
            <option value="act">Act</option>
          </select>
        </div>
        <div class="flex-center gap-8">
          <label class="text-muted" style="font-size:12px">Interval:</label>
          <input
            type="number"
            min="5"
            max="3600"
            value=${loopInterval}
            onInput=${(e) => setLoopInterval(Number(e.target.value))}
            style="width:70px"
          />
          <span class="text-muted" style="font-size:12px">s</span>
        </div>
        <button
          class=${`btn ${loopRunning ? 'btn-danger' : 'btn-primary'}`}
          onClick=${handleLoopToggle}
        >
          ${loopRunning ? '■ Stop Loop' : '▶ Start Loop'}
        </button>
      </div>
    </div>

    <!-- Chat messages -->
    <div class="chat-container">
      <div class="chat-messages">
        ${history.length === 0 && html`
          <div class="text-muted" style="text-align:center; margin:auto">
            No messages yet. Start the conversation below.
          </div>
        `}
        ${history.map((m, i) => html`<${ChatMessage} key=${i} msg=${m} />`)}
        <div ref=${messagesEndRef}></div>
      </div>
      <div class="flex-between mb-8">
        <span class="text-muted" style="font-size:12px">${history.length} messages</span>
        <button class="btn btn-secondary btn-sm" onClick=${handleClear}>Clear history</button>
      </div>
      <div class="chat-input-row">
        <textarea
          class="chat-input"
          placeholder="Type a message... (Enter to send, Shift+Enter for newline)"
          value=${message}
          onInput=${(e) => setMessage(e.target.value)}
          onKeyDown=${handleKeyDown}
          rows="2"
        ></textarea>
        <button
          class="btn btn-primary"
          onClick=${handleSend}
          disabled=${sending || !message.trim()}
        >
          ${sending ? '...' : 'Send'}
        </button>
      </div>
    </div>
  `;
}
