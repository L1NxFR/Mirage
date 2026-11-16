import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { parse } from 'yaml';

const vault = new URL('../site/content/', import.meta.url);
const settings = JSON.parse(fs.readFileSync(new URL('.obsidian/plugins/templater-obsidian/data.json', vault), 'utf8'));
const mappings = Object.fromEntries(settings.folder_templates.map(item => [item.folder, item.template]));

test('automatic Obsidian templates cover every journal and retain the root fallback', () => {
  assert.equal(settings.trigger_on_file_creation, true);
  assert.equal(settings.enable_folder_templates, true);
  assert.equal(settings.enable_file_templates, false);
  for (const [folder, template] of Object.entries({
    'related-work': 'Templates/Related Work.md',
    'research-journey': 'Templates/Research Journey.md',
    'system-implementation': 'Templates/System & Implementation.md',
    meetings: 'Templates/Meetings.md',
    '/': 'Templates/New Note.md'
  })) assert.equal(mappings[folder], template, folder);
});

function renderMetadata(template, title, date) {
  // Evaluate only the known substitutions in these project templates.
  const source = template
    .replace(/<%\s*JSON\.stringify\(tp\.file\.title\)\s*%>/g, () => JSON.stringify(title))
    .replace(/<%\s*tp\.date\.now\("YYYY-MM-DD"\)\s*%>/g, date);
  const match = source.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  assert.ok(match, 'The note must begin with YAML front matter');
  assert.ok(!match[1].includes('<%'), 'Metadata must not retain an unresolved template command');
  return parse(match[1]);
}

test('all configured templates provide safe default YAML metadata', () => {
  for (const template of new Set(Object.values(mappings))) {
    const source = fs.readFileSync(new URL(template, vault), 'utf8');
    const data = renderMetadata(source, 'Example note', '2026-11-15');
    assert.equal(data.draft, true, template);
    assert.equal(data.show_toc, true, template);
    assert.ok(['en', 'zh-CN'].includes(data.content_lang), template);
    assert.equal(data.date, '2026-11-15', `${template} must use the creation date`);
    assert.ok(Object.hasOwn(data, 'title'), template);
  }
});

test('related-work metadata uses the note name safely and never a fixed date', () => {
  const source = fs.readFileSync(new URL('Templates/Related Work.md', vault), 'utf8');
  const title = 'GPU "cache": 中文 comparison';
  for (const date of ['2026-11-15', '2027-01-02']) {
    const data = renderMetadata(source, title, date);
    assert.equal(data.title, title);
    assert.equal(data.date, date);
    assert.equal(data.draft, true);
  }
});
