/**
 * Painel Skills — lista com origem, tier, score do Crítico, uso.
 * ZERO innerHTML em conteúdo dinâmico (C7).
 */

import { apiJson } from '../api.js';

const $ = (id) => document.getElementById(id);

export function initSkills() {
  const list = $('skills-list');
  load(list);
  setInterval(() => load(list), 30000);
}

async function load(container) {
  renderLoading(container);
  try {
    const data = await apiJson('skills?limit=100');
    renderSkills(container, data.items || []);
  } catch (e) {
    renderError(container, e.message);
  }
}

function renderSkills(container, items) {
  container.textContent = '';
  if (items.length === 0) {
    const el = document.createElement('div');
    el.className = 'loading';
    el.textContent = 'Nenhuma skill';
    container.appendChild(el);
    return;
  }
  for (const s of items) {
    const item = document.createElement('div');
    item.className = 'list-item';

    const title = document.createElement('div');
    title.className = 'item-title';

    const name = document.createElement('span');
    name.textContent = s.name;
    title.appendChild(name);

    const origin = document.createElement('span');
    origin.className = 'item-status ' + (s.origin || 'manual');
    origin.textContent = s.origin || 'manual';
    title.appendChild(origin);

    item.appendChild(title);

    const meta = document.createElement('div');
    meta.className = 'item-meta';

    const parts = [];
    if (s.uses !== undefined) parts.push('usos:' + s.uses);
    if (s.score !== null && s.score !== undefined) parts.push('score:' + s.score.toFixed(2));
    if (s.status) parts.push(s.status);
    meta.textContent = parts.join(' · ');
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
