import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import http from 'node:http';
import { once } from 'node:events';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
let nextTestPort = 20000 + (process.pid % 250) * 32;
async function reserve(t, port) {
  for (;;) {
    const server = net.createServer();
    const listening = once(server, 'listening');
    // Avoid OS-assigned ephemeral ports being reused by concurrent HTTP clients.
    server.listen(port ?? nextTestPort++, '127.0.0.1');
    try { await listening; }
    catch (error) {
      if (port !== undefined || error.code !== 'EADDRINUSE') throw error;
      continue;
    }
    t.after(() => new Promise(resolve => server.close(resolve)));
    return server;
  }
}
function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dev-port-test-'));
  for (const dir of ['scripts', 'layouts', 'site/content', 'site/layouts', 'site/static', 'site/data', 'site/config']) {
    fs.mkdirSync(path.join(root, dir), { recursive: true });
  }
  for (const name of ['dev-server.mjs', 'workspace-store.mjs', 'document-weights.mjs']) {
    fs.copyFileSync(path.join(repo, 'scripts', name), path.join(root, 'scripts', name));
  }
  fs.symlinkSync(path.join(repo, 'node_modules'), path.join(root, 'node_modules'), 'dir');
  fs.writeFileSync(path.join(root, 'site/hugo.yaml'), 'baseURL: https://published.example/\ndisableKinds: [taxonomy, term]\n');
  fs.writeFileSync(path.join(root, 'site/content/_index.md'), '---\ntitle: Port test\ndraft: false\n---\nOriginal body.\n');
  fs.writeFileSync(path.join(root, 'site/layouts/home.html'), '<a href="{{ .Site.BaseURL }}">Workspace</a>{{ .Content }}');
  let child, exited, output = '';
  t.after(async () => {
    if (child?.exitCode === null && child.signalCode === null) child.kill('SIGTERM');
    if (exited) await exited;
    fs.rmSync(root, { recursive: true, force: true });
  });
  return {
    root,
    launch(args = []) {
      child = spawn(process.execPath, ['scripts/dev-server.mjs', ...args], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
      exited = once(child, 'exit');
      child.stdout.on('data', data => { output += data; });
      child.stderr.on('data', data => { output += data; });
      return { child, exited, output: () => output };
    }
  };
}
async function ready(run) {
  let timer, onData;
  try {
    return await Promise.race([
      new Promise(resolve => {
        onData = () => {
          const match = run.output().match(/http:\/\/localhost:(\d+)\//);
          if (match) resolve(Number(match[1]));
        };
        run.child.stdout.on('data', onData);
        onData();
      }),
      run.exited.then(([code]) => { throw new Error(`Server exited before readiness (${code}): ${run.output()}`); }),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`Startup timed out: ${run.output()}`)), 15000); })
    ]);
  } finally {
    clearTimeout(timer);
    run.child.stdout.off('data', onData);
  }
}
async function verifyWorkspace(port, oldPort) {
  const base = `http://127.0.0.1:${port}`;
  const page = await fetch(base).then(r => r.text());
  assert.ok(page.includes(`href="http://localhost:${port}/"`), 'Hugo uses the listening port');
  const status = await fetch(`${base}/api/workspace/status`);
  assert.equal(status.status, 200);
  const { token, projectRoot, contentRoot } = await status.json();
  assert.equal(path.dirname(path.dirname(path.dirname(contentRoot))), projectRoot);
  assert.equal(fs.realpathSync(contentRoot), contentRoot);
  assert.ok(fs.existsSync(path.join(contentRoot, '_index.md')));
  const headers = { 'X-Workspace-Token': token, Origin: base, 'Content-Type': 'application/json' };
  const doc = await fetch(`${base}/api/workspace/document?path=_index.md`, { headers }).then(r => r.json());
  const saved = await fetch(`${base}/api/workspace/save`, {
    method: 'POST', headers, body: JSON.stringify({ ...doc, source: doc.source + '\nSaved after port selection.\n' })
  });
  assert.equal(saved.status, 200, 'same-origin saving works on the selected port');
  const rebuilt = await fetch(base).then(r => r.text());
  assert.ok(rebuilt.includes('Saved after port selection.'));
  assert.ok(rebuilt.includes(`href="http://localhost:${port}/"`), 'rebuilds retain the selected port');
  if (oldPort !== undefined) {
    const wrongHost = await new Promise((resolve, reject) => {
      http.get(`${base}/api/workspace/status`, { headers: { Host: `localhost:${oldPort}` } }, response => {
        response.resume(); resolve(response.statusCode);
      }).on('error', reject);
    });
    assert.equal(wrongHost, 403, 'the occupied port is not accepted as a workspace host');
    const wrongOrigin = await fetch(`${base}/api/workspace/status`, { headers: { Origin: `http://127.0.0.1:${oldPort}` } });
    assert.equal(wrongOrigin.status, 403, 'origin checks use the selected port');
  }
}

test('default startup uses the portable five-digit port range', { timeout: 20000 }, async t => {
  const run = fixture(t).launch();
  const port = await ready(run);
  assert.match(run.output(), /Research workspace: http:/);
  assert.doesNotMatch(run.output(), /\p{Script=Han}/u);
  assert.ok(port >= 23130 && port <= 65535, `Unexpected default port ${port}`);
  await verifyWorkspace(port);
});
test('an available explicit port is used unchanged', { timeout: 20000 }, async t => {
  const reservation = await reserve(t);
  const port = reservation.address().port;
  await new Promise(resolve => reservation.close(resolve));
  const run = fixture(t).launch(['--port', String(port)]);
  assert.equal(await ready(run), port);
  await verifyWorkspace(port);
});
test('occupied ports are skipped sequentially and runtime configuration follows the selected port', { timeout: 20000 }, async t => {
  // Twelve failed attempts also catch leaked listening/error event handlers.
  const servers = [];
  for (let attempt = 0; attempt < 30; attempt++) {
    const first = await reserve(t);
    const start = first.address().port;
    servers.push(first);
    if (start > 65523) {
      servers.pop();
      await new Promise(resolve => first.close(resolve));
      continue;
    }
    try {
      for (let offset = 1; offset <= 12; offset++) servers.push(await reserve(t, start + offset));
      const available = servers.pop();
      await new Promise(resolve => available.close(resolve));
      const run = fixture(t).launch(['--port', String(start)]);
      const port = await ready(run);
      assert.equal(port, start + 12);
      assert.match(run.output(), /Port \d+ is in use; trying \d+\./);
      assert.doesNotMatch(run.output(), /\p{Script=Han}/u);
      assert.ok(!run.output().includes('MaxListenersExceededWarning'));
      await verifyWorkspace(port, start);
      return;
    } catch (error) {
      if (error.code !== 'EADDRINUSE') throw error;
      for (const server of servers.splice(0)) await new Promise(resolve => server.close(resolve));
    }
  }
  assert.fail('Could not reserve consecutive ports for the regression test');
});
test('invalid requested ports fail instead of silently changing configuration', { timeout: 20000 }, async t => {
  for (const port of ['1023', '65536', 'invalid']) {
    const run = fixture(t).launch(['--port', port]);
    const [code] = await run.exited;
    assert.notEqual(code, 0);
    assert.match(run.output(), /Choose a port between 1024 and 65535\./);
    assert.ok(!run.output().includes('http://localhost:'));
  }
});

test('external Markdown gets a persisted weight on the next watched rebuild', { timeout: 20000 }, async t => {
  const site = fixture(t);
  fs.mkdirSync(path.join(site.root, 'site/content/meetings'));
  fs.writeFileSync(path.join(site.root, 'site/content/meetings/old.md'), '---\ntitle: Old\nweight: 8\n---\n');
  const run = site.launch();
  await ready(run);
  const file = path.join(site.root, 'site/content/meetings/incoming.md');
  fs.writeFileSync(file, '---\ntitle: Incoming\n---\nExternal body.\n');
  const deadline = Date.now() + 10000;
  while (!/^weight: 9$/m.test(fs.readFileSync(file, 'utf8')) && Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  assert.match(fs.readFileSync(file, 'utf8'), /^weight: 9$/m);
  assert.ok(fs.readFileSync(file, 'utf8').endsWith('External body.\n'));
});

test('live reload versions advance after successful external saves but not failed builds', { timeout: 20000 }, async t => {
  const site = fixture(t);
  const run = site.launch();
  const port = await ready(run);
  const base = `http://127.0.0.1:${port}`;
  const status = () => fetch(`${base}/api/workspace/status`).then(r => r.json());
  const initial = (await status()).version;
  const html = await fetch(base).then(r => r.text());
  assert.ok(html.includes(`data-version="${initial}"`));
  assert.ok(html.includes('/js/workspace-live-reload.js'));
  const content = path.join(site.root, 'site/content/_index.md');
  fs.appendFileSync(content, '\nAutomatically updated.\n');
  const deadline = Date.now() + 10000;
  while ((await status()).version === initial && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 50));
  const updated = (await status()).version;
  assert.notEqual(updated, initial);
  assert.match(await fetch(base).then(r => r.text()), /Automatically updated/);
  fs.writeFileSync(path.join(site.root, 'site/layouts/home.html'), '{{ invalidFunction }}');
  const failureDeadline = Date.now() + 5000;
  while (!run.output().includes('Site build failed') && Date.now() < failureDeadline) await new Promise(resolve => setTimeout(resolve, 50));
  assert.match(run.output(), /Site build failed/);
  assert.equal((await status()).version, updated);
  assert.match(await fetch(base).then(r => r.text()), /Automatically updated/);
});
