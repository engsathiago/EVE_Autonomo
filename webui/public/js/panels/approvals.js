/**
 * Painel Aprovações — pendentes do Telegram com botões aprovar/rejeitar.
 * ZERO innerHTML em conteúdo dinâmico (C7).
 */

import { apiJson, apiPost } from '../api.js';
import { ws } from '../ws.js';

const $ = (id) => document.getElementById(id);

export function initApprovals() {
  const list = $('approvals-list');
  load(list);

  ws.subscribe('approvals', (type, data) => {
    if (type === 'new') load(list);
  });
  setInterval(() => load(list), 15000);
}

async function load(container) {
  try {
    const data = await apiJson('approvals?limit=20');
    render(container, data.items || []);
  } catch (e) {
    renderError(container, e.message);
  }
}

function render(container, items) {
  container.textContent = '';
  if (items.length === 0) {
    const el = document.createElement('div');
    el.className = 'loading';
    el.textContent = 'Sem aprovações pendentes';
    container.appendChild(el);
    return;
  }

  for (const ap of items) {
    const item = document.createElement('div');
    item.className = 'approval-item';

    const title = document.createElement('div');
    title.className = 'item-title';
    title.textContent = ap.tool_name || ap.id;
    item.appendChild(title);

    const ctx = document.createElement('div');
    ctx.className = 'item-meta';
    ctx.textContent = (ap.context || '').slice(0, 100);
    item.appendChild(ctx);

    const exp = document.createElement('div');
    exp.className = 'item-meta';
    exp.textContent = ap.expires_at ? 'expira: ' + fmtDate(ap.expires_at) : '';
    item.appendChild(exp);

    const actions = document.createElement('div');
    actions.className = 'approval-actions';

    const approveBtn = document.createElement('button');
    approveBtn.className = 'btn-approve';
    approveBtn.textContent = 'APROVAR';
    approveBtn.addEventListener('click', () => decide(ap.id, 'approve', container));
    actions.appendChild(approveBtn);

    const rejectBtn = document.createElement('button');
    rejectBtn.className = 'btn-reject';
    rejectBtn.textContent = 'REJEITAR';
    rejectBtn.addEventListener('click', () => decide(ap.id, 'reject', container));
    actions.appendChild(rejectBtn);

    item.appendChild(actions);
    container.appendChild(item);
  }
}

async function decide(id, decision, container) {
  try {
    await apiPost('approvals/' + id, { decision });
    // Reload após decisão
    const data = await apiJson('approvals?limit=20');
    render(container, data.items || []);
  } catch (e) {
    renderError(container, e.message);
  }
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
