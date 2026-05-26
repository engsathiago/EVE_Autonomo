/**
 * ws.js — Cliente WebSocket multiplexado com reconnect exponencial.
 * Um único WS para todos os tópicos.
 */

import { getToken } from './api.js';

const RECONNECT_BASE_MS = 500;
const RECONNECT_MAX_MS = 30000;
const PING_INTERVAL_MS = 20000;

class WsClient {
  constructor() {
    this._ws = null;
    this._handlers = {}; // topic -> Set<fn>
    this._reconnectDelay = RECONNECT_BASE_MS;
    this._reconnecting = false;
    this._destroyed = false;
    this._pingTimer = null;
    this._subscriptions = new Set();
    this._statusListeners = new Set();
  }

  onStatus(fn) { this._statusListeners.add(fn); }

  _emitStatus(s) {
    for (const fn of this._statusListeners) fn(s);
  }

  connect() {
    if (this._destroyed) return;
    const tok = getToken();
    if (!tok) return;
    const url = `ws://127.0.0.1:8080/api/v1/stream?token=${encodeURIComponent(tok)}`;
    this._emitStatus('connecting');
    const ws = new WebSocket(url);

    ws.onopen = () => {
      this._ws = ws;
      this._reconnectDelay = RECONNECT_BASE_MS;
      this._emitStatus('connected');
      // Re-assina tópicos após reconexão
      for (const topic of this._subscriptions) {
        this._sendRaw({ op: 'subscribe', topic });
      }
      this._startPing();
    };

    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      // Resposta ao ping do servidor
      if (msg.op === 'ping') {
        this._sendRaw({ op: 'pong' });
        return;
      }
      const { topic, type, data } = msg;
      const key = topic || '_';
      const handlers = this._handlers[key];
      if (handlers) for (const fn of handlers) fn(type, data);
    };

    ws.onclose = (ev) => {
      this._ws = null;
      this._stopPing();
      if (!this._destroyed) {
        this._emitStatus('disconnected');
        this._scheduleReconnect();
      }
    };

    ws.onerror = () => {
      // onclose vai disparar após onerror
    };
  }

  _startPing() {
    this._stopPing();
    this._pingTimer = setInterval(() => {
      // Servidor faz ping; cliente só responde. Nada a fazer aqui além de manter heartbeat.
    }, PING_INTERVAL_MS);
  }

  _stopPing() {
    if (this._pingTimer) { clearInterval(this._pingTimer); this._pingTimer = null; }
  }

  _scheduleReconnect() {
    if (this._destroyed) return;
    setTimeout(() => this.connect(), this._reconnectDelay);
    this._reconnectDelay = Math.min(this._reconnectDelay * 2, RECONNECT_MAX_MS);
  }

  _sendRaw(obj) {
    if (this._ws && this._ws.readyState === WebSocket.OPEN) {
      this._ws.send(JSON.stringify(obj));
    }
  }

  subscribe(topic, fn) {
    if (!this._handlers[topic]) this._handlers[topic] = new Set();
    this._handlers[topic].add(fn);
    this._subscriptions.add(topic);
    this._sendRaw({ op: 'subscribe', topic });
  }

  unsubscribe(topic, fn) {
    if (this._handlers[topic]) {
      this._handlers[topic].delete(fn);
      if (this._handlers[topic].size === 0) {
        delete this._handlers[topic];
        this._subscriptions.delete(topic);
        this._sendRaw({ op: 'unsubscribe', topic });
      }
    }
  }

  sendChat(text) {
    this._sendRaw({ op: 'chat.send', text });
  }

  destroy() {
    this._destroyed = true;
    this._stopPing();
    if (this._ws) this._ws.close();
  }
}

export const ws = new WsClient();
