'use strict';

const STATUS = { x: 'done', X: 'done', '/': 'running', ' ': 'pending', '!': 'error' };
const MARKER = { done: 'x', running: '/', active: '/', pending: ' ', error: '!' };
const normalized = text => text.replace(/\r\n/g, '\n').replace(/\n+$/, '');

function parseTimeline(source) {
  const model = { title: '', collapse: 0, steps: [] };
  let current;
  for (const [index, line] of normalized(source).split('\n').entries()) {
    const task = line.match(/^[-*+] \[([xX /!])\][ \t]*(.*)$/);
    if (task) {
      const open = / \{open\}$/.test(task[2]);
      current = { text: task[2].replace(/ \{open\}$/, ''), status: STATUS[task[1]], content: '', open };
      model.steps.push(current);
    } else if (current && (/^( {2}|\t)/.test(line) || !line.trim())) {
      current.content += (current.content ? '\n' : '') + line.replace(/^( {2}|\t)/, '');
    } else if (!line.trim()) {
      continue;
    } else if (!current && /^# /.test(line)) {
      model.title = line.slice(2).trim();
    } else if (!current && /^collapse: \d+$/.test(line)) {
      model.collapse = Number(line.slice(10));
    } else {
      throw new Error(`第 ${index + 1} 行：用任务列表写步骤，例如 - [ ] 步骤；详情缩进两个空格。`);
    }
  }
  for (const step of model.steps) step.content = step.content.trimEnd();
  if (model.collapse > model.steps.length) throw new Error('collapse 不能超过步骤数。');
  return model;
}

function serializeTimeline(model) {
  const lines = [];
  if (model.title.trim()) lines.push('# ' + model.title.trim());
  if (model.collapse) lines.push('collapse: ' + model.collapse);
  for (const step of model.steps) {
    lines.push(`- [${MARKER[step.status] || ' '}] ${step.text}${step.open && step.content ? ' {open}' : ''}`);
    if (step.content) lines.push(...step.content.split('\n').map(line => '  ' + line));
  }
  return lines.join('\n');
}

function fenceTimeline(source) {
  const runs = source.match(/`+/g) || [];
  const fence = '`'.repeat(Math.max(3, ...runs.map(run => run.length + 1)));
  return `${fence}timeline\n${source}\n${fence}`;
}

function findTimelineBlocks(note) {
  const lines = note.match(/[^\n]*\n|[^\n]+$/g) || [];
  const blocks = [];
  let offset = 0;
  let fence = null;
  let block;
  for (const [index, raw] of lines.entries()) {
    const line = raw.replace(/\r?\n$/, '');
    if (!fence) {
      const opening = line.match(/^(`{3,}|~{3,})([^\r\n]*)$/);
      if (opening) {
        fence = opening[1];
        if (opening[2].trim() === 'timeline') block = { from: offset, line: index, sourceStart: offset + raw.length };
      }
    } else if (new RegExp('^' + fence[0] + '{' + fence.length + ',}\\s*$').test(line)) {
      if (block) blocks.push({ from: block.from, to: offset + line.length, line: block.line, source: normalized(note.slice(block.sourceStart, offset)) });
      fence = null;
      block = null;
    }
    offset += raw.length;
  }
  return blocks;
}

function replacementFor(note, original, expectedLine, replacement) {
  const candidates = findTimelineBlocks(note).filter(block => block.source === normalized(original));
  const target = candidates.find(block => block.line === expectedLine) || (candidates.length === 1 ? candidates[0] : null);
  return target ? { from: target.from, to: target.to, text: fenceTimeline(replacement) } : null;
}

module.exports = { parseTimeline, serializeTimeline, fenceTimeline, findTimelineBlocks, replacementFor };
