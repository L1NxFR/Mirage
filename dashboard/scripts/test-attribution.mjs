import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { attributeFiles } from './attribute-files.mjs';
import { parse } from 'yaml';

function fixture(t, metadata) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'attribution-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const file = 'dashboard/site/content/other/note.md';
  fs.mkdirSync(path.dirname(path.join(root, file)), { recursive: true });
  fs.writeFileSync(path.join(root, 'dashboard/site/hugo.yaml'), 'params:\n  author:\n    default: 林楠\n');
  fs.writeFileSync(path.join(root, file), `---\n${metadata}\n---\n\nUnchanged body\n`);
  return { root, file, source: () => fs.readFileSync(path.join(root, file), 'utf8'), data() { return parse(this.source().split('---')[1]); } };
}

test('appends agents, preserves user attribution and body, deduplicates case-insensitively', t => {
  const f = fixture(t, 'title: Note\nauthor: 林楠');
  const original = f.source();
  assert.deepEqual(attributeFiles(f.root, 'Claude', [f.file], { check: true }), [f.file]);
  assert.equal(f.source(), original);
  attributeFiles(f.root, 'Claude', [f.file]);
  attributeFiles(f.root, 'Codex', [f.file]);
  assert.deepEqual(f.data().author, ['林楠', 'Claude', 'Codex']);
  assert.deepEqual(Object.keys(f.data()).sort(), ['author', 'lastmod', 'title']);
  assert.ok(f.source().endsWith('\n\nUnchanged body\n'));
  const source = f.source();
  assert.deepEqual(attributeFiles(f.root, 'claude', [f.file]), []);
  assert.equal(f.source(), source);
});

test('preserves agent-only authors and resolves uncredited user documents', t => {
  const f = fixture(t, 'title: Note\nauthor: [Claude, Grok]');
  attributeFiles(f.root, 'Codex', [f.file]);
  assert.deepEqual(f.data().author, ['Claude', 'Grok', 'Codex']);
  const g = fixture(t, 'title: User note');
  attributeFiles(g.root, 'Codex', [g.file]);
  assert.deepEqual(g.data().author, ['林楠', 'Codex']);
});

test('records non-document files without modifying their bytes and rejects outside paths', t => {
  const f = fixture(t, 'title: Note');
  fs.writeFileSync(path.join(f.root, 'example.js'), 'export const value = 1;\n');
  attributeFiles(f.root, 'Codex', ['example.js']);
  assert.equal(fs.readFileSync(path.join(f.root, 'example.js'), 'utf8'), 'export const value = 1;\n');
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(f.root, '.file-coauthors.json'), 'utf8')), { 'example.js': ['Codex'] });
  assert.deepEqual(attributeFiles(f.root, 'Codex', ['example.js'], { check: true }), []);
  assert.throws(() => attributeFiles(f.root, 'Codex', ['../outside.md']), /Unsupported path/);
});


test('migrates legacy coauthors into one ordered author list without losing names', t => {
  const f = fixture(t, 'title: Note\nauthor: 林楠\ncoauthors: [Claude, claude, Codex]');
  attributeFiles(f.root, 'Codex', [f.file]);
  assert.deepEqual(f.data().author, ['林楠', 'Claude', 'Codex']);
  assert.equal(Object.hasOwn(f.data(), 'coauthors'), false);
});
