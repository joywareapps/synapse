/**
 * Synapse Web UI — no-build Preact SPA
 * Uses esm.sh CDN for Preact + HTM; hash-based routing.
 */
import { h, render, createContext } from 'https://esm.sh/preact@10';
import { useState, useEffect, useCallback, useRef, useContext, useReducer } from 'https://esm.sh/preact@10/hooks';
import htm from 'https://esm.sh/htm@3';

export { h, createContext, useState, useEffect, useCallback, useRef, useContext, useReducer };
export const html = htm.bind(h);

import { ReconnectingWS } from './ws.js';
import { Dashboard } from './pages/Dashboard.js';
import { Axes } from './pages/Axes.js';
import { Patterns } from './pages/Patterns.js';
import { Sensors } from './pages/Sensors.js';
import { Settings } from './pages/Settings.js';
import { Chat } from './pages/Chat.js';

const ROUTES = [
  { hash: '#/', label: 'Dashboard', icon: '⊞', Component: Dashboard },
  { hash: '#/axes', label: 'Axes', icon: '↕', Component: Axes },
  { hash: '#/patterns', label: 'Patterns', icon: '♪', Component: Patterns },
  { hash: '#/sensors', label: 'Sensors', icon: '◉', Component: Sensors },
  { hash: '#/chat', label: 'Chat', icon: '✦', Component: Chat },
  { hash: '#/settings', label: 'Settings', icon: '⚙', Component: Settings },
];

function getHash() {
  const h = window.location.hash || '#/';
  return h.endsWith('/') && h.length > 2 ? h.slice(0, -1) : h;
}

function navigate(hash) {
  window.location.hash = hash;
}

function App() {
  const [hash, setHash] = useState(getHash);
  const [wsState, setWsState] = useState('disconnected');
  const [liveData, setLiveData] = useState(null);
  const wsRef = useRef(null);

  useEffect(() => {
    const handler = () => setHash(getHash());
    window.addEventListener('hashchange', handler);
    return () => window.removeEventListener('hashchange', handler);
  }, []);

  useEffect(() => {
    const ws = new ReconnectingWS('/ws', setLiveData, setWsState);
    wsRef.current = ws;
    return () => ws.close();
  }, []);

  const route = ROUTES.find((r) => r.hash === hash) || ROUTES[0];
  const { Component } = route;

  return html`
    <div class="layout">
      <nav class="nav">
        <div class="nav-brand">Synapse</div>
        <div class="nav-links">
          ${ROUTES.map((r) => html`
            <button
              class=${`nav-link ${hash === r.hash ? 'active' : ''}`}
              onClick=${() => navigate(r.hash)}
            >
              <span class="nav-icon">${r.icon}</span>
              ${r.label}
            </button>
          `)}
        </div>
        <div class="nav-footer">
          <div class="connection-indicator">
            <div class=${`status-dot ${wsState === 'connected' ? 'connected' : 'disconnected'}`}></div>
            <span>${wsState === 'connected' ? 'Live' : 'Offline'}</span>
          </div>
        </div>
      </nav>
      <main class="main-content">
        <${Component} wsState=${wsState} liveData=${liveData} navigate=${navigate} />
      </main>
    </div>
  `;
}

render(h(App, null), document.getElementById('app'));
