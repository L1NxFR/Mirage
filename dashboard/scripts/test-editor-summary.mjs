import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readSummary, writeSummary } from './editor/summary.mjs';
import { parseDocument } from 'yaml';

test('existing documents without a summary can add multiline Markdown without changing other properties', () => {
  const metadata = '# Keep this comment\ntitle: Existing\ndraft: true\ncustom: [a, b]\n';
  assert.equal(readSummary(metadata), '');
  const summary = '**Result:** faster.\n\n- First\n- Second';
  const updated = writeSummary(metadata, summary);
  const data = parseDocument(updated).toJS();
  assert.equal(readSummary(updated), summary);
  assert.equal(data.title, 'Existing');
  assert.equal(data.draft, true);
  assert.deepEqual(data.custom, ['a', 'b']);
  assert.match(updated, /# Keep this comment/);
  assert.match(updated, /tldr: \|/);
});
test('reads existing YAML summaries, replaces them, and clears them without empty cover blocks', () => {
  const metadata = 'title: Note\ntldr: |\n  Old summary.\n';
  assert.equal(readSummary(metadata), 'Old summary.\n');
  assert.equal(readSummary(writeSummary(metadata, 'New: "summary"')), 'New: "summary"');
  assert.equal(readSummary(writeSummary(metadata, ' \n ')), '');
  assert.equal(parseDocument(writeSummary(metadata, '')).has('tldr'), false);
});
test('refuses malformed YAML and unsupported summary types without rewriting metadata', () => {
  for (const metadata of ['title: [broken', '- a list', 'title: A\ntldr: [a, b]', 'title: A\ntitle: B']) {
    assert.throws(() => readSummary(metadata));
    assert.throws(() => writeSummary(metadata, 'Replacement'));
  }
});
