/**
 * Painel Missões — lista paginada com filtro por status.
 * ZERO innerHTML em conteúdo dinâmico (C7).
 */

import { apiJson } from '../api.js';

const $ = (id) => document.getElementById(id);

export function initMissions() {
  const list = $('missions-list');
  const filter = $('missions-filter');

  async function load() {
    const status = filter.value;
    renderLoading(list);
    try {
      const param = status ? `?status=${encodeURIComponent(status)}&limit=50` : '?limit=50';
      const data = await apiJson('missions' + param);
      renderMissions(list, data.items || []);
    } catch (e) {
      renderError(list, e.message);
    }
  }

  filter.addEventListener('change', load);
  load();
  setInterval(load, 15000);
}

function renderMissions(container, items) {
  container.textContent = '';
  if (items.length === 0) {
    const el = document.createElement('div');
    el.className = 'loading';
    el.textContent = 'Nenhuma missão';
    container.appendChild(el);
    return;
  }
  for (const m of items) {
    const item = document.createElement('div');
    item.className = 'list-item';

    const title = document.createElement('div');
    title.className = 'item-title';

    const name = document.createElement('span');
    name.textContent = m.title || m.objective?.slice(0, 60) || m.id;
    title.appendChild(name);

    const status = document.createElement('span');
    status.className = 'item-status ' + (m.status || '');
    status.textContent = m.status || '';
    title.appendChild(status);

    item.appendChild(title);

    const meta = document.createElement('div');
    meta.className = 'item-meta';
    meta.textContent = fmtDate(m.created_at);
    item.appendChild(meta);

    container.appendChild(item);
  }
}

function renderLoading(el) {
  el.textContent = '';
  const d = document.createElement('div');
  d.className = 'loading';
  d.textContent = 'Carregando…';
  el.appendChild(d);
}

function renderError(el, msg) {
  el.textContent = '';
  const d = document.createElement('div');
  d.className = 'panel-error';
  d.textContent = 'Erro: ' + msg;
  el.appendChild(d);
}

function fmtDate(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
  } catch { return iso; }
}
