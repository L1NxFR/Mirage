import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { Readable, Writable } from 'node:stream';
import { addPost } from './add-post.mjs';
import { parseSource } from './workspace-store.mjs';

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'add-post-'));
  for (const section of ['related-work', 'meetings', 'research-journey', 'system-implementation', 'other']) fs.mkdirSync(path.join(root, section));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  let log = '';
  const output = new Writable({ write(chunk, encoding, callback) { log += chunk; callback(); } });
  return { root, output, log: () => log, run: (args, answers) => addPost({ args, root, input: Readable.from([answers]), output }) };
}

test('interactive selection creates complete drafts in every category', async t => {
  const f = fixture(t);
  for (const [i, section] of ['related-work', 'meetings', 'research-journey', 'system-implementation', 'other'].entries()) {
    const doc = await f.run(['My Post.md'], `${i + 1}\n`);
    assert.equal(doc.path, `${section}/my-post.md`);
    const { data } = parseSource(doc.source);
    assert.equal(data.title, 'My Post');
    assert.equal(data.weight, 1);
    assert.equal(data.draft, true);
    for (const key of ['description', 'subtitle', 'tldr', 'author']) assert.equal(data[key], '');
    assert.deepEqual(data.tags, []);
  }
  const second = await f.run(['中文标题'], 'invalid\nrelated-work\n');
  assert.equal(parseSource(second.source).data.weight, 2);
  assert.match(f.log(), /Invalid category/);
  const before = fs.readFileSync(path.join(f.root, second.path), 'utf8');
  await assert.rejects(f.run(['中文标题'], '1\n'), { status: 409 });
  assert.equal(fs.readFileSync(path.join(f.root, second.path), 'utf8'), before);
});

test('cancel, EOF, invalid titles and help do not create documents', async t => {
  const f = fixture(t);
  await f.run(['Post'], 'q\n');
  await f.run(['Post'], '');
  await f.run(['--help'], '');
  for (const args of [[], ['../escape'], ['a/b'], ['.hidden'], ['a', 'b']]) await assert.rejects(f.run(args, '1\n'));
  for (const dir of fs.readdirSync(f.root)) assert.deepEqual(fs.readdirSync(path.join(f.root, dir)), []);
});
