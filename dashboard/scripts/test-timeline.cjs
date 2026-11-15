const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { parseTimeline, serializeTimeline, fenceTimeline, findTimelineBlocks, replacementFor } = require('../site/content/.obsidian/plugins/research-timeline/source.js');

test('task lists preserve statuses and indented Markdown details', () => {
  const model = parseTimeline('# Progress\n- [x] Done\n- [/] Working\n  **Details**\n  - nested item\n- [ ] Later\n- [!] Failed');
  assert.equal(model.title, 'Progress');
  assert.deepEqual(model.steps.map(s => s.status), ['done', 'running', 'pending', 'error']);
  assert.equal(model.steps[1].content, '**Details**\n- nested item');
});

test('visual editor data survives Markdown serialization', () => {
  const model = { title: '研究进度', collapse: 1, steps: [
    { text: '完成', status: 'done', content: '', open: false },
    { text: '分析', status: 'running', content: '第一段。\n\n- 项目', open: true }
  ] };
  assert.deepEqual(parseTimeline(serializeTimeline(model)), model);
});

test('nested code fences stay inside their timeline', () => {
  const source = '- [/] Working\n  ```python\n  print(1)\n  ```';
  const note = '# Before\n\n' + fenceTimeline(source) + '\n\n# After';
  const blocks = findTimelineBlocks(note);
  assert.equal(blocks.length, 1);
  assert.equal(blocks[0].source, source);
  assert.equal(note.slice(blocks[0].from, blocks[0].to), fenceTimeline(source));
});

test('editing the second identical block never replaces the first', () => {
  const source = '- [ ] Same';
  const fence = fenceTimeline(source);
  const note = fence + '\n\n' + fence;
  const blocks = findTimelineBlocks(note);
  const change = replacementFor(note, source, blocks[1].line, '- [x] Changed');
  assert.equal(note.slice(0, change.from), fence + '\n\n');
  assert.equal(note.slice(change.from, change.to), fence);
});

test('stale or ambiguous editing targets fail without overwriting notes', () => {
  assert.equal(replacementFor('```timeline\n- [x] Changed elsewhere\n```', '- [ ] Old', 0, '- [ ] New'), null);
  const source = '- [ ] Same';
  assert.equal(replacementFor(fenceTimeline(source) + '\n\n' + fenceTimeline(source), source, -1, '- [ ] New'), null);
});

test('invalid input reports an actionable error', () => {
  assert.throws(() => parseTimeline('title: hidden YAML'), /任务列表/);
  assert.throws(() => parseTimeline('collapse: 4\n- [ ] One'), /collapse/);
});

test('the packaged plugin loads without filesystem-relative require support', () => {
  const sandbox = { module: { exports: {} }, require(id) {
    assert.equal(id, 'obsidian', 'Obsidian plugins must bundle local modules');
    return { Plugin: class {}, Modal: class {}, MarkdownRenderChild: class {} };
  } };
  vm.runInNewContext(fs.readFileSync(require.resolve('../site/content/.obsidian/plugins/research-timeline/main.js'), 'utf8'), sandbox);
  assert.equal(typeof sandbox.module.exports, 'function');
});
