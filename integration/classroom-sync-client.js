/**
 * Classroom Sync browser integration helper.
 * Usage: import { joinStudent, ClassroomSyncClient } from './classroom-sync-client.js';
 * This module is framework-agnostic; connect it to your existing Three.js actions.
 */
const root = value => value.replace(/\/+$/, '');

async function post(baseUrl, path, payload, adminKey) {
  const res = await fetch(root(baseUrl) + path, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(adminKey ? { Authorization: `Bearer ${adminKey}` } : {})
    },
    body: JSON.stringify(payload)
  });
  const json = await res.json();
  if (!res.ok) throw new Error(json.error || `HTTP ${res.status}`);
  return json;
}

export function createClassroom(baseUrl, { title, groupCount, adminKey }) {
  // Call from an authenticated teacher-only interface. Never commit adminKey to JS files.
  return post(baseUrl, '/api/classrooms', { title, groupCount }, adminKey);
}
export function joinStudent(baseUrl, { inviteCode, displayName }) {
  return post(baseUrl, '/api/join', { inviteCode, displayName });
}
export function joinTeacher(baseUrl, { classroomId, groupId, teacherToken }) {
  return post(baseUrl, '/api/teacher-join', { classroomId, groupId, teacherToken });
}

export class ClassroomSyncClient {
  constructor({ baseUrl, sessionToken, onSnapshot, onOperation, onPresence, onStatus, onError }) {
    this.baseUrl = root(baseUrl);
    this.sessionToken = sessionToken;
    this.onSnapshot = onSnapshot || (() => {});
    this.onOperation = onOperation || (() => {});
    this.onPresence = onPresence || (() => {});
    this.onStatus = onStatus || (() => {});
    this.onError = onError || (() => {});
    this.socket = null;
    this.closedByUser = false;
    this.retryCount = 0;
    this.retryTimer = null;
    this.ready = false;
  }

  connect() {
    this.closedByUser = false;
    const wsUrl = this.baseUrl.replace(/^https:/, 'wss:').replace(/^http:/, 'ws:') + '/ws';
    this.onStatus('connecting');
    const ws = new WebSocket(wsUrl);
    this.socket = ws;
    this.ready = false;
    ws.onopen = () => ws.send(JSON.stringify({ type: 'auth', token: this.sessionToken }));
    ws.onmessage = event => {
      let msg;
      try { msg = JSON.parse(event.data); } catch (e) { this.onError(e); return; }
      if (msg.type === 'snapshot') {
        this.ready = true;
        this.retryCount = 0;
        this.onStatus('connected');
        this.onSnapshot(msg); // authoritative replacement, including after reconnection
      } else if (msg.type === 'op') {
        this.onOperation(msg);
      } else if (msg.type === 'presence') {
        this.onPresence(msg);
      } else if (msg.type === 'error') {
        this.onError(new Error(msg.message));
      }
    };
    ws.onerror = () => this.onError(new Error('WebSocket network error'));
    ws.onclose = () => {
      this.ready = false;
      this.onStatus('disconnected');
      if (!this.closedByUser && this.socket === ws) {
        const delay = Math.min(1000 * 2 ** this.retryCount++, 10000);
        this.retryTimer = setTimeout(() => this.connect(), delay);
      }
    };
  }

  sendOp(action, data) {
    if (!this.ready || !this.socket || this.socket.readyState !== WebSocket.OPEN) {
      throw new Error('当前未连接协作服务；请等待 snapshot 完成同步');
    }
    const opId = 'op_' + crypto.randomUUID().replaceAll('-', '');
    this.socket.send(JSON.stringify({ type: 'op', opId, action, data }));
  }

  close() {
    this.closedByUser = true;
    this.ready = false;
    clearTimeout(this.retryTimer);
    if (this.socket) this.socket.close();
  }
}
