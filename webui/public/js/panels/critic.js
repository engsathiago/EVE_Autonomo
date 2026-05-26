/**
 * Painel Crítico — fila de decisões + histórico com 3 personas.
 * ZERO innerHTML em conteúdo dinâmico (C7).
 */

import { apiJson } from '../api.js';

const $ = (id) => document.getElementById(id);

export function initCritic() {
  const list = $('critic-list');
  load(list);
  setInterval(() => load(list), 15000);
}

async function load(container) {
  try {
    const [queue, history] = await Promise.all([
      apiJson('critic/queue?limit=10'),
      apiJson('critic/history?limit=10'),
    ]);
    render(container, queue.items || [], history.items || []);
  } catch (e) {
    renderError(container, e.message);
  }
}

function render(container, queue, history) {
  container.textContent = '';

  if (queue.length > 0) {
    const hdr = document.createElement('div');
    hdr.className = 'item-meta';
    hdr.textContent = 'PENDENTES (' + queue.length + ')';
    container.appendChild(hdr);
    for (const ev of queue) container.appendChild(buildItem(ev, true));
  }

  if (history.length > 0) {
    const hdr = document.createElement('div');
    hdr.className = 'item-meta';
    hdr.style.marginTop = '8px';
    hdr.textContent = 'HISTÓRICO';
    container.appendChild(hdr);
    for (const ev of history) container.appendChild(buildItem(ev, false));
  }

  if (queue.length === 0 && history.length === 0) {
    const el = document.createElement('div');
    el.className = 'loading';
    el.textContent = 'Sem avaliações';
    container.appendChild(el);
  }
}

function buildItem(ev, isPending) {
  const item = document.createElement('div');
  item.className = 'critic-item';

  const title = document.createElement('div');
  title.className = 'item-title';

  const name = document.createElement('span');
  name.textContent = ev.tool_name || '?';
  title.appendChild(name);

  if (isPending) {
    const badge = document.createElement('span');
    badge.className = 'item-status active';
    badge.textContent = 'pendente';
    title.appendChild(badge);
  }
  item.appendChild(title);

  const meta = document.createElement('div');
  meta.className = 'item-meta';
  meta.textContent = (ev.context_summary || '').slice(0, 80);
  item.appendChild(meta);

  // Vereditos das 3 personas
  const verdicts = document.createElement('div');
  verdicts.className = 'critic-verdicts';

  for (const [label, v] of [
    ['TÉC', ev.technical_verdict],
    ['ADV', ev.devils_verdict],
    ['SIN', ev.final_verdict],
  ]) {
    if (!v) continue;
    const row = document.createElement('div');
    row.className = 'verdict-row';

    const lbl = document.createElement('span');
    lbl.className = 'dim';
    lbl.textContent = label + ':';
    row.appendChild(lbl);

    const val = document.createElement('span');
    val.className = v.approve ? 'verdict-approve' : 'verdict-reject';
    val.textContent = v.approve ? 'APROVADO' : 'REJEITADO';
    row.appendChild(val);

    const conf = document.createElement('span');
    conf.className = 'dim';
    conf.textContent = v.confidence !== undefined ? ' (' + (v.confidence * 100).toFixed(0) + '%)' : '';
    row.appendChild(conf);

    verdicts.appendChild(row);
  }
  item.appendChild(verdicts);

  return item;
}

function renderError(el, msg) {
  el.textContent = '';
  const d = document.createElement('div');
  d.className = 'panel-error';
  d.textContent = 'Erro: ' + msg;
  el.appendChild(d);
}
