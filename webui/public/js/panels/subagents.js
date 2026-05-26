/**
 * Painel Subagentes — health dos workers, fila, latência.
 * ZERO innerHTML em conteúdo dinâmico (C7).
 */

import { apiJson } from '../api.js';
import { ws } from '../ws.js';

const $ = (id) => document.getElementById(id);

export function initSubagents() {
  const info = $('subagents-info');
  load(info);

  ws.subscribe('health', (type, data) => { if (type === 'snapshot') render(info, data); });
  setInterval(() => load(info), 10000);
}

async function load(container) {
  try {
    const data = await apiJson('subagents');
    render(container, data);
  } catch (e) {
    renderError(container, e.message);
  }
}

function render(container, data) {
  container.textContent = '';

  function stat(label, value) {
    const row = document.createElement('div');
    row.className = 'subagent-stat';

    const lbl = document.createElement('span');
    lbl.className = 'item-meta';
    lbl.textContent = label;
    row.appendChild(lbl);

    const val = document.createElement('span');
    val.className = 'green';
    val.textContent = String(value ?? '—');
    row.appendChild(val);

    container.appendChild(row);
  }

  stat('Ativos', data.active ?? 0);
  stat('Capacidade', data.capacity ?? 0);

  const runs = data.recent_runs || [];
  if (runs.length > 0) {
    const hdr = document.createElement('div');
    hdr.className = 'item-meta';
    hdr.style.marginTop = '6px';
    hdr.textContent = 'EXECUÇÕES RECENTES';
    container.appendChild(hdr);

    for (const r of runs.slice(0, 8)) {
      const row = document.createElement('div');
      row.className = 'subagent-run';
      const parts = [
        (r.task_id || '').slice(0, 8),
        r.tier || '',
        r.status || '',
        r.error ? '[ERRO]' : '',
      ].filter(Boolean);
      row.textContent = parts.join(' · ');
      container.appendChild(row);
    }
  }
}

function renderError(el, msg) {
  el.textContent = '';
  const d = document.createElement('div');
  d.className = 'panel-error';
  d.textContent = 'Erro: ' + msg;
  el.appendChild(d);
}
