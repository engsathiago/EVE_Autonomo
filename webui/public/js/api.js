/**
 * api.js — Wrapper de fetch com X-Agent-Token automático.
 * Trata 401 mostrando overlay de auth novamente.
 */

let _token = null;

export function setToken(tok) {
  _token = tok;
  try { sessionStorage.setItem('agent_token', tok); } catch (_) {}
}

export function getToken() {
  if (_token) return _token;
  try { _token = sessionStorage.getItem('agent_token'); } catch (_) {}
  return _token;
}

export function clearToken() {
  _token = null;
  try { sessionStorage.removeItem('agent_token'); } catch (_) {}
}

/**
 * @param {string} path — relativo a /api/v1/
 * @param {RequestInit} opts
 */
export async function api(path, opts = {}) {
  const tok = getToken();
  const headers = {
    'Content-Type': 'application/json',
    ...(tok ? { 'X-Agent-Token': tok } : {}),
    ...(opts.headers || {}),
  };
  const url = `/api/v1/${path.replace(/^\//, '')}`;
  const res = await fetch(url, { ...opts, headers });

  if (res.status === 401) {
    clearToken();
    window.dispatchEvent(new CustomEvent('agent:unauthorized'));
    throw new Error('Não autorizado');
  }

  return res;
}

export async function apiJson(path, opts = {}) {
  const res = await api(path, opts);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return res.json();
}

export async function apiPost(path, body) {
  return apiJson(path, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}
