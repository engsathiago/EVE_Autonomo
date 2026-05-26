/**
 * Painel Traces — filtráveis, timeline expansível, virtualiza 500+ steps.
 * ZERO innerHTML em conteúdo dinâmico (C7).
 */

import { apiJson } from '../api.js';
import { ws } from '../ws.js';

const $ = (id) => document.getElementById(id);

const VIRTUAL_CHUNK = 40; // renderiza em lotes para não travar

export function initTraces() {
  const list = $('traces-list');
  let _items = [];
  let _rendered = 0;

  async function load() {
    try {
      const data = await apiJson('traces?limit=100');
      _items = data.items || [];
      _rendered = 0;
      list.textContent = '';
      renderChunk();
    } catch (e) {
      renderError(list, e.message);
    }
  }

  function renderChunk() {
    const end = Math.min(_rendered + VIRTUAL_CHUNK, _items.length);
    for (let i = _rendered; i < end; i++) {
      list.appendChild(buildTraceEl(_items[i]));
    }
    _rendered = end;
    if (_rendered < _items.length) {
      // Observa o último elemento para lazy-render
      const sentinel = document.createElement('div');
      sentinel.className = 'loading';
      sentinel.textContent = `… mais ${_items.length - _rendered} traces`;
      list.appendChild(sentinel);

      const obs = new IntersectionObserver((entries) => {
        if (entries[0].isIntersecting) {
          obs.disconnect();
          sentinel.remove();
          renderChunk();
        }
      }, { root: list });
      obs.observe(sentinel);
    }
  }

  // Atualiza em tempo real via WS
  ws.subscribe('traces', (type, data) => {
    if (type === 'step') load();
  });

  load();
  setInterval(load, 20000);
}

function buildTraceEl(t) {
  const item = document.createElement('div');
  item.className = 'trace-item';
  item.style.cursor = 'pointer';

  const title = document.createElement('div');
  title.className = 'item-title';

  const idSpan = document.createElement('span');
  idSpan.className = 'dim';
  idSpan.textContent = (t.id || '').slice(0, 8) + ' ';
  title.appendChild(idSpan);

  const content = document.createElement('span');
  content.textContent = (t.content || '').slice(0, 70);
  title.appendChild(content);

  const st = document.createElement('span');
  st.className = 'item-status ' + (t.status || '');
  st.textContent = t.status || '';
  title.appendChild(st);

  item.appendChild(title);

  const meta = document.createElement('div');
  meta.className = 'item-meta';
  meta.textContent = [t.tier, fmtDate(t.created_at)].filter(Boolean).join(' · ');
  item.appendChild(meta);

  // Steps expansíveis (carregados sob demanda)
  const stepsEl = document.createElement('div');
  stepsEl.className = 'trace-steps';
  item.appendChild(stepsEl);

  item.addEventListener('click', async () => {
    const expanded = stepsEl.classList.contains('expanded');
    if (expanded) {
      stepsEl.classList.remove('expanded');
      return;
    }
    if (stepsEl.childElementCount === 0) {
      stepsEl.textContent = '';
      const loading = document.createElement('div');
      loading.textContent = 'Carregando steps…';
      loading.className = 'loading';
      stepsEl.appendChild(loading);
      stepsEl.classList.add('expanded');
      try {
        const { apiJson: _apiJson } = await import('../api.js');
        const detail = await _apiJson('traces/' + t.id);
        stepsEl.textContent = '';
        for (const step of (detail.steps || [])) {
          const stepEl = document.createElement('div');
          stepEl.className = 'trace-step';
          stepEl.textContent = (step.status || '') + ' ' + (step.content || '').slice(0, 80);
          stepsEl.appendChild(stepEl);
        }
        if ((detail.steps || []).length === 0) {
          const empty = document.createElement('div');
          empty.className = 'trace-step';
          empty.textContent = 'Sem steps';
          stepsEl.appendChild(empty);
        }
      } catch (e) {
        stepsEl.textContent = '';
        const err = document.createElement('div');
        err.className = 'panel-error';
        err.textContent = 'Erro: ' + e.message;
        stepsEl.appendChild(err);
      }
    } else {
      stepsEl.classList.add('expanded');
    }
  });

  return item;
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
