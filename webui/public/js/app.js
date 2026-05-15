/**
 * app.js — Boot + roteamento de tópicos WS.
 * Inicializa todos os painéis após autenticação.
 */

import { setToken, getToken, clearToken, apiJson } from './api.js';
import { ws } from './ws.js';
import { initChat } from './panels/chat.js';
import { initMissions } from './panels/missions.js';
import { initSkills } from './panels/skills.js';
import { initMemory } from './panels/memory.js';
import { initTraces } from './panels/traces.js';
import { initCritic } from './panels/critic.js';
import { initSubagents } from './panels/subagents.js';
import { initApprovals } from './panels/approvals.js';

const $ = (id) => document.getElementById(id);

// ── Auth ──────────────────────────────────────────────────────────────────

function showAuth(errorMsg) {
  $('app').classList.add('hidden');
  $('auth-overlay').classList.remove('hidden');
  if (errorMsg) {
    const el = $('auth-error');
    el.classList.remove('hidden');
    el.textContent = errorMsg;
  }
}

function showApp() {
  $('auth-overlay').classList.add('hidden');
  $('app').classList.remove('hidden');
}

async function tryConnect(tok) {
  setToken(tok);
  try {
    await apiJson('system/info');
    showApp();
    bootApp();
  } catch (e) {
    clearToken();
    showAuth('Token inválido ou servidor indisponível');
  }
}

$('token-submit').addEventListener('click', () => {
  const tok = $('token-input').value.trim();
  if (tok) tryConnect(tok);
});

$('token-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') $('token-submit').click();
});

window.addEventListener('agent:unauthorized', () => showAuth('Sessão expirada'));

// ── Inicialização ─────────────────────────────────────────────────────────

function bootApp() {
  // WS
  ws.onStatus(updateWsStatus);
  ws.connect();

  // Painéis
  initChat(ws);
  initMissions();
  initSkills();
  initMemory();
  initTraces();
  initCritic();
  initSubagents();
  initApprovals();

  // Métricas do topo
  loadMetrics();
  setInterval(loadMetrics, 30000);

  loadSystemInfo();
}

function updateWsStatus(status) {
  const el = $('m-ws-status');
  el.className = 'value ws-indicator ' + status;
  el.title = status;
}

async function loadMetrics() {
  try {
    const data = await apiJson('metrics/summary');
    setText('m-skills-7d', data.skills_created_7d ?? '—');
    setText('m-missions', data.missions_completed ?? '—');
    const rate = data.critic_approval_rate;
    setText('m-critic-rate', rate !== null && rate !== undefined ? (rate * 100).toFixed(0) + '%' : '—');
    const up = data.uptime_s;
    setText('m-uptime', up !== null && up !== undefined ? fmtUptime(up) : '—');
  } catch (_) {}
}

async function loadSystemInfo() {
  try {
    const data = await apiJson('system/info');
    setText('m-version', data.version ?? 'v?');
  } catch (_) {}
}

function setText(id, val) {
  const el = $(id);
  if (el) el.textContent = val;
}

function fmtUptime(s) {
  if (s < 60) return s + 's';
  if (s < 3600) return Math.floor(s / 60) + 'm';
  if (s < 86400) return Math.floor(s / 3600) + 'h';
  return Math.floor(s / 86400) + 'd';
}

// ── Arranque ──────────────────────────────────────────────────────────────
// Tenta usar token existente na sessão
const stored = getToken();
if (stored) {
  tryConnect(stored);
} else {
  // Suporte a ?token= na URL (gerado por `agent web open`)
  const urlToken = new URLSearchParams(window.location.search).get('token');
  if (urlToken) {
    // Remove token da URL sem recarregar a página
    history.replaceState({}, '', window.location.pathname);
    tryConnect(urlToken);
  } else {
    showAuth();
  }
}
