import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { parseDocument } from 'yaml';

const sections = ['related-work','research-journey','system-implementation','meetings','other'];
export const validWeight = value => Number.isSafeInteger(value);

function records(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).filter(entry =>
    entry.isFile() && entry.name.endsWith('.md') && !entry.name.endsWith('.excalidraw.md') && entry.name !== '_index.md' && !entry.name.startsWith('.')
  ).map(entry => {
    const file = path.join(directory, entry.name), source = fs.readFileSync(file, 'utf8');
    const match = source.match(/^---\r?\n(?:([\s\S]*?)\r?\n)?---(?:\r?\n|$)/);
    if (!match && source.startsWith('---')) throw new Error(`Invalid YAML metadata: ${file}`);
    const metadata = match ? parseDocument(match[1] || '') : null;
    if (metadata?.errors.length) throw new Error(`Invalid YAML metadata: ${file}`);
    const data = metadata?.toJS({ maxAliasCount: 20 }) || {};
    if (typeof data !== 'object' || Array.isArray(data)) throw new Error(`Invalid YAML metadata: ${file}`);
    if (Object.hasOwn(data, 'weight') && !validWeight(data.weight)) throw new Error(`weight must be a safe integer: ${file}`);
    return { file, source, title: String(data.title || entry.name), weight: data.weight, hasMetadata: Boolean(match), blank: !source.slice(match?.[0].length || 0).trim() && Object.keys(data).every(key => key === 'weight') && (!match || /^---\r?\n(?:weight: *-?\d+\r?\n)?---\s*$/.test(source)) };
  });
}

export function nextDocumentWeight(directory, exclude) {
  const weights = records(directory).filter(record => record.file !== exclude).map(record => record.weight).filter(validWeight);
  const next = weights.length ? Math.max(...weights) + 1 : 1;
  if (!validWeight(next)) throw new Error('No integer weight remains after the last document.');
  return next;
}

export function firstDocumentWeight(directory) {
  const weights = records(directory).map(record => record.weight).filter(validWeight);
  const first = weights.length ? Math.min(...weights) - 1 : 1;
  if (!validWeight(first)) throw new Error('No integer weight remains before the first document.');
  return first;
}

// Initialize blank notes; otherwise add only weight and preserve existing content.
function assign(record, weight) {
  const newline = record.source.includes('\r\n') ? '\r\n' : '\n';
  if (record.blank) {
    const now = new Date(Date.now() + 8 * 60 * 60 * 1000).toISOString().replace('Z', '+08:00');
    return ['---', `title: ${JSON.stringify(path.basename(record.file, '.md'))}`, 'description: ""', 'subtitle: ""', 'tldr: ""', 'author: ""', `date: ${now}`, `lastmod: ${now}`, 'draft: true', 'content_lang: zh-CN', 'tags: []', 'show_toc: true', `weight: ${weight}`, '---', '', ''].join(newline);
  }
  if (!record.hasMetadata) return `---${newline}weight: ${weight}${newline}---${newline}${record.source}`;
  const offset = record.source.indexOf('\n') + 1;
  return record.source.slice(0, offset) + `weight: ${weight}${newline}` + record.source.slice(offset);
}

export function syncDocumentWeights(root, { check = false } = {}) {
  const changes = [];
  function walk(directory) {
    const notes = records(directory);
    const assigned = notes.map(record => record.weight).filter(validWeight);
    let next = assigned.length ? Math.max(...assigned) + 1 : 1;
    for (const record of notes.filter(record => (record.weight === undefined || record.blank)).sort((a,b) => a.title.localeCompare(b.title))) {
      const weight = record.weight ?? next++;
      if (!validWeight(weight)) throw new Error(`No integer weight remains: ${directory}`);
      changes.push({ ...record, updated: assign(record, weight), weight });
    }
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      if (entry.isDirectory() && !entry.name.startsWith('.') && !['Templates','Attachments'].includes(entry.name)) walk(path.join(directory, entry.name));
    }
  }
  for (const section of sections) {
    const directory = path.join(root, section);
    if (fs.existsSync(directory) && !fs.lstatSync(directory).isSymbolicLink()) walk(directory);
  }
  if (!check) {
    for (const item of changes) {
      if (fs.readFileSync(item.file, 'utf8') !== item.source) throw new Error(`Document changed during weight assignment: ${item.file}`);
    }
    for (const item of changes) {
      const temp = path.join(path.dirname(item.file), `.weight-${randomUUID()}.tmp`);
      try {
        fs.writeFileSync(temp, item.updated, { flag: 'wx', mode: fs.statSync(item.file).mode & 0o777 });
        fs.renameSync(temp, item.file);
      } finally { if (fs.existsSync(temp)) fs.unlinkSync(temp); }
    }
  }
  return changes;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const option = process.argv.indexOf('--root');
  const root = option < 0 ? fileURLToPath(new URL('../site/content/', import.meta.url)) : path.resolve(process.argv[option + 1]);
  const changes = syncDocumentWeights(root, { check: process.argv.includes('--check') });
  console.log(`${process.argv.includes('--check') ? 'Missing' : 'Assigned'} document weights: ${changes.length}`);
  if (changes.length && process.argv.includes('--check')) process.exitCode = 1;
}
