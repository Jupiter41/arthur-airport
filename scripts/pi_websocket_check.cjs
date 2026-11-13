// Bounded public-ingress checks. Tokens stay in process memory and out of logs.
const assert = require('node:assert/strict');
const WebSocket = require('../services/api-gateway/node_modules/ws');
const origin = 'https://airportdt.duckdns.org';

async function rejected(token, requestOrigin) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(origin.replace('https:', 'wss:') + '/ws' + (token ? '?token=' + token : ''),
      { origin: requestOrigin, handshakeTimeout: 10000 });
    ws.on('open', () => { ws.close(); reject(new Error('Unexpected authorized connection')); });
    ws.on('unexpected-response', (_req, response) => {
      response.resume(); ws.terminate();
      try { assert.equal(response.statusCode, 401); resolve(); } catch (error) { reject(error); }
    });
    ws.on('error', () => {});
  });
}

function observer(token) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(origin.replace('https:', 'wss:') + '/ws?token=' + token,
      { origin, handshakeTimeout: 10000 });
    let snapshot = false;
    const timer = setTimeout(() => { ws.terminate(); reject(new Error('No shared simulation event in 85 seconds')); }, 85000);
    ws.on('open', () => ws.send(JSON.stringify({ action: 'subscribe', topics: ['sim'] })));
    ws.on('error', error => { clearTimeout(timer); reject(error); });
    ws.on('message', raw => {
      const message = JSON.parse(raw.toString());
      if (message.type === 'snapshot') snapshot = true;
      if (message.type === 'ping') ws.send(JSON.stringify({ type: 'pong' }));
      if (message.event_type === 'SimClockTick') {
        clearTimeout(timer); ws.close();
        try { assert(snapshot); resolve(message.event_id ?? message.sim_time ?? message.payload?.sim_time); }
        catch (error) { reject(error); }
      }
    });
  });
}

async function oversized(token) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(origin.replace('https:', 'wss:') + '/ws?token=' + token, { origin, handshakeTimeout: 10000 });
    const timer = setTimeout(() => { ws.terminate(); reject(new Error('Oversize frame was not closed')); }, 10000);
    ws.on('open', () => ws.send('x'.repeat(8192)));
    ws.on('close', code => { clearTimeout(timer); try { assert.equal(code, 1009); resolve(); } catch (e) { reject(e); } });
    ws.on('error', () => {});
  });
}

(async () => {
  const response = await fetch(origin + '/auth/viewer', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
  assert.equal(response.status, 200);
  const { token } = await response.json();
  await rejected(null, origin); console.log('PASS unauthenticated WebSocket denied');
  await rejected(token, 'https://untrusted.invalid'); console.log('PASS cross-origin WebSocket denied');
  await oversized(token); console.log('PASS oversized WebSocket frame closed with 1009');
  const ids = await Promise.all([observer(token), observer(token)]);
  assert(ids[0]); assert.equal(ids[0], ids[1]);
  console.log('PASS two viewers received snapshots and the same live simulation tick');
})().catch(error => { console.error(error.message); process.exitCode = 1; });
