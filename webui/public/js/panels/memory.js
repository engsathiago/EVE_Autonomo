/**
 * Painel Memória — busca semântica com top-K e similaridade.
 * ZERO innerHTML em conteúdo dinâmico (C7).
 */

import { apiPost } from '../api.js';

const $ = (id) => document.getElementById(id);

export function initMemory() {
  const results = $('memory-results');
  const queryEl = $('memory-query');
  const searchBtn = $('memory-search');

  async function search() {
    const q = queryEl.value.trim();
    if (!q) return;
    renderLoading(results);
    try {
      const data = await apiPost('memory/search', { query: q, k: 10 });
      renderResults(results, data.items || []);
    } catch (e) {
      renderError(results, e.message);
    }
  }

  searchBtn.addEventListener('click', search);
  queryEl.addEventListener('keydown', (e) => { if (e.key === 'Enter') search(); });

  // Carrega resultados recentes ao inicializar
  (async () => {
    renderLoading(results);
    try {
      const data = await apiPost('memory/search', { query: 'agente missão skill', k: 5 });
      renderResults(results, data.items || []);
    } catch (_) {
      results.textContent = '';
    }
  })();
}

function renderResults(container, items) {
  container.textContent = '';
  if (items.length === 0) {
    const el = document.createElement('div');
    el.className = 'loading';
    el.textContent = 'Sem resultados';
    container.appendChild(el);
    return;
  }
  for (const r of items) {
    const item = document.createElement('div');
    item.className = 'memory-result';

    const sim = document.createElement('div');
    sim.className = 'memory-similarity';
    sim.textContent = 'similaridade: ' + (r.similarity ?? '?') + ' · ' + (r.kind || '');
    item.appendChild(sim);

    const content = document.createElement('div');
    content.className = 'memory-content';
    content.textContent = r.content || '';
    item.appendChild(content);

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
