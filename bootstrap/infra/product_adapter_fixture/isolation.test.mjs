import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';

test('reviewed delivery cannot be overwritten', () => {
  assert.throws(() => fs.writeFileSync('/workspace/isolation.test.mjs', 'tampered'));
});
test('no Docker socket or controller credentials', () => {
  for (const p of ['/var/run/docker.sock','/opt/data','/deliveries','/root/.ssh']) {
    assert.equal(fs.existsSync(p), false);
  }
  for (const key of ['GH_TOKEN','GITHUB_TOKEN','OPENROUTER_API_KEY']) assert.equal(process.env[key], undefined);
});
test('temporary writes isolated from snapshot', () => {
  fs.writeFileSync('/tmp/probe', 'temporary');
  assert.equal(fs.readFileSync('/tmp/probe','utf8'), 'temporary');
});
test('no external network route', async () => {
  const blocked = await new Promise((resolve) => {
    const socket = net.createConnection({host:'192.0.2.1',port:443});
    socket.setTimeout(1000);
    socket.once('connect', () => {socket.destroy();resolve(false);});
    socket.once('error', () => {socket.destroy();resolve(true);});
    socket.once('timeout', () => {socket.destroy();resolve(true);});
  });
  assert.equal(blocked,true);
});
