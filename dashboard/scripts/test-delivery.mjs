import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { once } from 'node:events';
import { execFileSync, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { checkDelivery, parseDeliveryArgs } from './check-delivery.mjs';

const script = fileURLToPath(new URL('./check-delivery.mjs', import.meta.url));
const addScript = fileURLToPath(new URL('./add-post.mjs', import.meta.url));
const repo = fileURLToPath(new URL('../../', import.meta.url));
function fixture(t) {
  const temp = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'delivery-')));
  t.after(() => fs.rmSync(temp, { recursive: true, force: true }));
  const root = path.join(temp, 'Project');
  fs.mkdirSync(root);
  const git = (...args) => execFileSync('git', ['-C', root, ...args], { stdio: 'pipe' });
  git('init');
  fs.mkdirSync(path.join(root, 'dashboard/site/content'), { recursive: true });
  fs.writeFileSync(path.join(root, 'dashboard/site/content/note.md'), 'Note');
  git('add', '.');
  git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', '-c', 'commit.gpgsign=false', 'commit', '-m', 'fixture');
  const worktree = path.join(temp, 'worktree');
  git('worktree', 'add', '--detach', worktree);
  return { temp, root, worktree };
}

test('linked worktree cannot substitute for the explicitly requested delivery directory', async t => {
  const f = fixture(t);
  fs.writeFileSync(path.join(f.worktree, 'only-here.md'), 'Wrong location');
  await assert.rejects(checkDelivery({ targetRoot: f.root, operationRoot: f.worktree }), /directory mismatch/);
  await assert.rejects(checkDelivery({ targetRoot: f.root, operationRoot: f.root, files: ['only-here.md'] }), /ENOENT/);
  const passed = await checkDelivery({ targetRoot: f.worktree, operationRoot: f.worktree, files: ['only-here.md'] });
  assert.equal(passed.files.length, 1);
  const failedCLI = spawnSync(process.execPath, [script, '--target-root', f.root], { cwd: f.worktree, encoding: 'utf8' });
  assert.equal(failedCLI.status, 1);
  assert.match(failedCLI.stderr, /directory mismatch/);
  const passedCLI = spawnSync(process.execPath, [script, '--target-root', f.worktree, '--file', 'only-here.md'], { cwd: f.worktree, encoding: 'utf8' });
  assert.equal(passedCLI.status, 0, passedCLI.stderr);
});

test('canonical paths support symlinks and renamed project instances without hardcoded names', async t => {
  const f = fixture(t);
  const link = path.join(f.temp, 'alias');
  fs.symlinkSync(f.root, link, 'dir');
  assert.equal((await checkDelivery({ targetRoot: link, operationRoot: f.root })).targetRoot, f.root);
  const moved = path.join(f.temp, 'Different Project');
  fs.renameSync(f.root, moved);
  await checkDelivery({ targetRoot: moved, operationRoot: path.join(moved, 'dashboard'), files: ['dashboard/site/content/note.md'] });
});

test('missing target, non-root targets and escaping files fail', async t => {
  const f = fixture(t);
  await assert.rejects(checkDelivery({ operationRoot: f.root }), /Explicit absolute/);
  await assert.rejects(checkDelivery({ targetRoot: '.', operationRoot: f.root }), /Explicit absolute/);
  await assert.rejects(checkDelivery({ targetRoot: path.join(f.root, 'dashboard'), operationRoot: f.root }), /Git root/);
  fs.writeFileSync(path.join(f.temp, 'outside.md'), 'Outside');
  fs.symlinkSync(path.join(f.temp, 'outside.md'), path.join(f.root, 'escape.md'));
  for (const file of ['../outside.md', 'escape.md', 'dashboard']) await assert.rejects(checkDelivery({ targetRoot: f.root, operationRoot: f.root, files: [file] }), /not inside/);
  await assert.rejects(checkDelivery({ targetRoot: f.root, operationRoot: f.root, pages: ['/'] }), /requires --url/);
  assert.equal(parseDeliveryArgs([], { DELIVERY_ROOT: f.root }).targetRoot, f.root);
  assert.throws(() => parseDeliveryArgs(['--target-root']), /incomplete/);
});

test('Dashboard identity and served HTML are checked; failures are not passes', async t => {
  const f = fixture(t);
  let identity = { projectRoot: f.root, contentRoot: path.join(f.root, 'dashboard/site/content') };
  const server = http.createServer((req, res) => {
    if (req.url === '/api/workspace/status') { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(identity)); }
    else if (req.url === '/note/') { res.setHeader('Content-Type', 'text/html'); res.end('<html>Note</html>'); }
    else if (req.url === '/json/') { res.setHeader('Content-Type', 'application/json'); res.end('{}'); }
    else { res.writeHead(404); res.end('Missing'); }
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  t.after(() => { server.closeAllConnections(); server.close(); });
  const options = { targetRoot: f.root, operationRoot: f.root, url: `http://127.0.0.1:${server.address().port}` };
  assert.equal((await checkDelivery({ ...options, pages: ['/note/'] })).dashboardChecked, true);
  for (const [page, message] of [['/missing/', /404/], ['/json/', /not HTML/], ['//example.com', /local absolute/]]) await assert.rejects(checkDelivery({ ...options, pages: [page] }), message);
  identity = { projectRoot: f.worktree, contentRoot: path.join(f.worktree, 'dashboard/site/content') };
  await assert.rejects(checkDelivery(options), /directory mismatch/);
  identity = {};
  await assert.rejects(checkDelivery(options), /missing identity/);
  server.closeAllConnections();
  await new Promise(resolve => server.close(resolve));
  await assert.rejects(checkDelivery(options), /fetch failed/);
});

test('add CLI rejects missing or wrong target before prompting or writing', t => {
  const f = fixture(t);
  const env = { ...process.env };
  delete env.DELIVERY_ROOT;
  for (const args of [['Post'], ['--target-root', f.worktree, 'Post']]) {
    const result = spawnSync(process.execPath, [addScript, ...args], { cwd: f.worktree, env, input: '1\n', encoding: 'utf8' });
    assert.equal(result.status, 1);
    assert.match(result.stderr, /Explicit absolute|directory mismatch/);
    assert.doesNotMatch(result.stdout, /Choose a category/);
  }
  const correct = spawnSync(process.execPath, [addScript, '--target-root', repo, 'Post'], { cwd: f.worktree, env, input: 'q\n', encoding: 'utf8' });
  assert.equal(correct.status, 0, correct.stderr);
  assert.match(correct.stdout, /Cancelled/);
  const help = spawnSync(process.execPath, [addScript, '--help'], { env, encoding: 'utf8' });
  assert.equal(help.status, 0, help.stderr);
});


test('add CLI writes only to its checked script checkout, independent of cwd', t => {
  const f = fixture(t);
  const scripts = path.join(f.worktree, 'dashboard/scripts');
  fs.mkdirSync(scripts, { recursive: true });
  for (const name of ['add-post.mjs', 'check-delivery.mjs', 'workspace-store.mjs', 'document-weights.mjs']) {
    fs.copyFileSync(fileURLToPath(new URL(name, import.meta.url)), path.join(scripts, name));
  }
  fs.symlinkSync(path.join(repo, 'dashboard/node_modules'), path.join(f.worktree, 'dashboard/node_modules'), 'dir');
  fs.mkdirSync(path.join(f.worktree, 'dashboard/site/content/research-journey'));
  const run = target => spawnSync(process.execPath, [path.join(scripts, 'add-post.mjs'), '--target-root', target, 'Delivery fixture'], { cwd: f.root, input: '3\n', encoding: 'utf8' });
  const failed = run(f.root);
  assert.equal(failed.status, 1);
  assert.match(failed.stderr, /directory mismatch/);
  assert.deepEqual(fs.readdirSync(path.join(f.worktree, 'dashboard/site/content/research-journey')), []);
  const passed = run(f.worktree);
  assert.equal(passed.status, 0, passed.stderr);
  assert.ok(fs.existsSync(path.join(f.worktree, 'dashboard/site/content/research-journey/delivery-fixture.md')));
  assert.ok(!fs.existsSync(path.join(f.root, 'dashboard/site/content/research-journey/delivery-fixture.md')));
});


test('add CLI rejects content symlinks into another checkout before writing', async t => {
  const f = fixture(t);
  const scripts = path.join(f.worktree, 'dashboard/scripts');
  fs.mkdirSync(scripts, { recursive: true });
  for (const name of ['add-post.mjs', 'check-delivery.mjs', 'workspace-store.mjs', 'document-weights.mjs']) {
    fs.copyFileSync(fileURLToPath(new URL(name, import.meta.url)), path.join(scripts, name));
  }
  fs.symlinkSync(path.join(repo, 'dashboard/node_modules'), path.join(f.worktree, 'dashboard/node_modules'), 'dir');
  const actualContent = path.join(f.root, 'dashboard/site/content');
  fs.mkdirSync(path.join(actualContent, 'research-journey'));
  const content = path.join(f.worktree, 'dashboard/site/content');
  fs.rmSync(content, { recursive: true });
  fs.symlinkSync(actualContent, content, 'dir');
  const result = spawnSync(process.execPath, [path.join(scripts, 'add-post.mjs'), '--target-root', f.worktree, 'Delivery fixture'], { cwd: f.worktree, input: '3\n', encoding: 'utf8' });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /content directory is outside target root/);
  assert.doesNotMatch(result.stdout, /Choose a category/);
  assert.deepEqual(fs.readdirSync(path.join(actualContent, 'research-journey')), []);
  fs.unlinkSync(content);
  const sameProjectContent = path.join(f.worktree, 'documents');
  fs.mkdirSync(sameProjectContent);
  fs.symlinkSync(sameProjectContent, content, 'dir');
  await checkDelivery({ targetRoot: f.worktree, operationRoot: f.worktree });
});


test('CLI entry points execute through symlink ancestors rather than silently succeeding', t => {
  const f = fixture(t);
  const link = path.join(f.temp, 'project-alias');
  fs.symlinkSync(repo, link, 'dir');
  const env = { ...process.env };
  delete env.DELIVERY_ROOT;
  for (const name of ['check-delivery.mjs', 'add-post.mjs']) {
    const entry = path.join(link, 'dashboard/scripts', name);
    const args = name === 'add-post.mjs' ? ['Post'] : [];
    const failed = spawnSync(process.execPath, [entry, ...args], { cwd: repo, env, encoding: 'utf8' });
    assert.equal(failed.status, 1, name);
    assert.match(failed.stderr, /Explicit absolute/);
    const passed = spawnSync(process.execPath, [entry, '--target-root', repo, ...args], { cwd: repo, env, input: 'q\n', encoding: 'utf8' });
    assert.equal(passed.status, 0, passed.stderr);
    assert.match(passed.stdout, name === 'add-post.mjs' ? /Cancelled/ : /Delivery check passed/);
  }
});
