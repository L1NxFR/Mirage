import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { syncDocumentWeights, nextDocumentWeight } from './document-weights.mjs';
import { createStore, parseSource } from './workspace-store.mjs';
import { parse } from 'yaml';
import documentWeight from '../site/content/Templates/Scripts/document_weight.js';

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'document-weights-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  for (const section of ['related-work','research-journey','system-implementation','meetings']) fs.mkdirSync(path.join(root, section));
  const note = (name, weight, title = name) => {
    const file = path.join(root, 'meetings', name + '.md');
    fs.writeFileSync(file, `---\ntitle: ${title}\n${weight === undefined ? '' : `weight: ${weight}\n`}date: 2026-01-01\n---\nBody bytes.\n`);
    return file;
  };
  return { root, note };
}

test('fills missing weights in title order, preserves explicit values, indexes, bodies and timestamps', t => {
  const { root, note } = fixture(t);
  const b = note('b'), a = note('a'); note('zero', 0); note('negative', -3);
  note('_index');
  const changes = syncDocumentWeights(root);
  assert.equal(changes.length, 2);
  assert.equal(parseSource(fs.readFileSync(a, 'utf8')).data.weight, 1);
  assert.equal(parseSource(fs.readFileSync(b, 'utf8')).data.weight, 2);
  assert.ok(fs.readFileSync(a,'utf8').endsWith('---\nBody bytes.\n'));
  assert.equal(parseSource(fs.readFileSync(a,'utf8')).data.date, '2026-01-01');
  assert.equal(syncDocumentWeights(root).length, 0);
  assert.equal(nextDocumentWeight(path.join(root,'meetings')), 3);
  assert.equal(parseSource(fs.readFileSync(path.join(root,'meetings/_index.md'),'utf8')).data.weight, undefined);
});

test('new, copied and moved documents append locally, while saves respect manual weights and reject invalid values', async t => {
  const { root, note } = fixture(t);
  note('old');
  fs.mkdirSync(path.join(root,'meetings/nested'));
  const store = createStore(root);
  const a = await store.create({ kind:'document', parent:'meetings', title:'New A' });
  const b = await store.create({ kind:'document', parent:'meetings', title:'New B' });
  assert.equal(parseSource(a.source).data.weight, 2);
  assert.equal(parseSource(b.source).data.weight, 3);
  const nested = await store.create({ kind:'document', parent:'meetings/nested', title:'Inner' });
  assert.equal(parseSource(nested.source).data.weight, 1);
  const copied = await store.action({ ...nested, action:'copy', parent:'meetings' });
  assert.equal(parseSource(copied.source).data.weight, 4);
  const moved = await store.action({ ...nested, action:'move', parent:'meetings' });
  assert.equal(parseSource(moved.source).data.weight, 5);
  const manual = await store.save({ ...a, source:a.source.replace('weight: 2','weight: -10') });
  assert.equal(parseSource(manual.source).data.weight, -10);
  const missing = await store.save({ ...manual, source:manual.source.replace('weight: -10\n','') });
  assert.equal(parseSource(missing.source).data.weight, 6);
  await assert.rejects(store.save({ ...missing, source:missing.source.replace('weight: 6','weight: invalid') }), {status:422});
  const pin = await store.action({ ...b, action:'pin' });
  assert.ok(parseSource(pin.source).data.weight < 1);
  const unpin = await store.action({ ...pin, action:'pin' });
  assert.equal(parseSource(unpin.source).data.weight, 7);
});

test('normalizes notes without YAML, skips symlinks and applies no partial writes on malformed metadata', t => {
  const { root, note } = fixture(t);
  const plain = path.join(root,'meetings/plain.md'); fs.writeFileSync(plain,'Plain body.\n');
  syncDocumentWeights(root);
  assert.match(fs.readFileSync(plain,'utf8'), /^---\nweight: 1\n---\nPlain body\.\n$/);
  const missing = note('missing');
  fs.writeFileSync(path.join(root,'meetings/broken.md'),'---\ntitle: [invalid\n---\n');
  assert.throws(() => syncDocumentWeights(root), /metadata|YAML/i);
  assert.doesNotMatch(fs.readFileSync(missing,'utf8'), /weight:/);
  fs.unlinkSync(path.join(root,'meetings/broken.md'));
  fs.symlinkSync(plain,path.join(root,'meetings/link.md'));
  syncDocumentWeights(root);
  assert.ok(fs.lstatSync(path.join(root,'meetings/link.md')).isSymbolicLink());
});

test('Templater assigns a sibling weight from live files, backfills peers and leaves group indexes alone', async t => {
  const { root, note } = fixture(t);
  note('existing', 5); note('b'); note('a'); note('_index', 1000);
  const targetPath = note('new');
  const children = fs.readdirSync(path.dirname(targetPath)).map(name => ({
    path: 'meetings/' + name, basename: name.slice(0,-3), extension: 'md'
  }));
  const target = children.find(file => file.basename === 'new');
  target.parent = { children };
  const tp = { config: { target_file: target }, obsidian: { parseYaml: parse }, app: { vault: {
    read: async file => fs.readFileSync(path.join(root,file.path),'utf8'),
    modify: async (file,source) => fs.writeFileSync(path.join(root,file.path),source)
  } } };
  assert.equal(await documentWeight(tp), 'weight: 8');
  assert.equal(parseSource(fs.readFileSync(path.join(root,'meetings/a.md'),'utf8')).data.weight, 6);
  assert.equal(parseSource(fs.readFileSync(path.join(root,'meetings/b.md'),'utf8')).data.weight, 7);
  target.basename = '_index';
  assert.equal(await documentWeight(tp), '');
});
