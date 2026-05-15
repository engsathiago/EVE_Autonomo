/**
 * Painel Chat — input + stream de resposta via WebSocket.
 * ZERO innerHTML em conteúdo dinâmico (C7).
 */

const $ = (id) => document.getElementById(id);

export function initChat(ws) {
  const messages = $('chat-messages');
  const input = $('chat-input');
  const sendBtn = $('chat-send');

  let currentAgentMsg = null;
  let currentAgentText = null;

  function addMessage(role, text) {
    const wrap = document.createElement('div');
    wrap.className = 'chat-msg ' + role;

    const roleEl = document.createElement('div');
    roleEl.className = 'role';
    roleEl.textContent = role === 'user' ? 'VOCÊ' : 'AGENTE';
    wrap.appendChild(roleEl);

    const textEl = document.createElement('div');
    textEl.className = 'text';
    textEl.textContent = text;
    wrap.appendChild(textEl);

    messages.appendChild(wrap);
    messages.scrollTop = messages.scrollHeight;
    return textEl;
  }

  function send() {
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    addMessage('user', text);

    // Inicia mensagem do agente vazia
    currentAgentMsg = document.createElement('div');
    currentAgentMsg.className = 'chat-msg agent';

    const roleEl = document.createElement('div');
    roleEl.className = 'role';
    roleEl.textContent = 'AGENTE';
    currentAgentMsg.appendChild(roleEl);

    currentAgentText = document.createElement('div');
    currentAgentText.className = 'text';
    currentAgentText.textContent = '…';
    currentAgentMsg.appendChild(currentAgentText);

    messages.appendChild(currentAgentMsg);
    messages.scrollTop = messages.scrollHeight;

    ws.sendChat(text);
  }

  ws.subscribe('chat', (type, data) => {
    if (type === 'token') {
      if (currentAgentText) {
        const current = currentAgentText.textContent;
        currentAgentText.textContent = current === '…' ? data : current + data;
        messages.scrollTop = messages.scrollHeight;
      }
    } else if (type === 'done') {
      currentAgentMsg = null;
      currentAgentText = null;
    } else if (type === 'error') {
      if (currentAgentText) {
        currentAgentText.textContent = '[ERRO] ' + String(data);
        currentAgentMsg = null;
        currentAgentText = null;
      }
    }
  });

  sendBtn.addEventListener('click', send);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') send(); });
}
