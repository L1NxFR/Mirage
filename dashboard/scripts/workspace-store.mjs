import fs from 'node:fs';
import path from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { parseDocument } from 'yaml';

export const sections = ['related-work', 'research-journey', 'system-implementation', 'meetings'];
export class WorkspaceError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
const fail = (status, message) => { throw new WorkspaceError(status, message); };
export const revision = source => createHash('sha256').update(source).digest('hex');
export function parseSource(source) {
  if (typeof source !== 'string' || Buffer.byteLength(source) > 2_000_000) fail(422, 'Document must be smaller than 2 MB.');
  const match = source.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/);
  if (!match) fail(422, 'A YAML metadata block is required at the start of the document.');
  const metadata = parseDocument(match[1]);
  if (metadata.errors.length) fail(422, `Invalid metadata: ${metadata.errors[0].message.split('\n')[0]}`);
  let data;
  try { data = metadata.toJS({ maxAliasCount: 20 }); } catch { fail(422, 'Metadata aliases are too complex.'); }
  if (!data || typeof data !== 'object' || Array.isArray(data) || typeof data.title !== 'string' || !data.title.trim()) fail(422, 'Metadata must include a nonempty title.');
  return { metadata, data, body: source.slice(match[0].length) };
}
const slug = value => value.normalize('NFKC').toLowerCase().trim().replace(/[^\p{L}\p{N}_-]+/gu, '-').replace(/^-+|-+$/g, '');
export function createStore(contentRoot, rebuild = async () => {}) {
  const root = fs.realpathSync(contentRoot);
  function resolve(relative, directory = false) {
    if (typeof relative !== 'string' || !relative || relative.includes('\\') || relative.includes('\0')) fail(400, 'Invalid document path.');
    const parts = relative.split('/');
    if (parts.some(part => !part || part.startsWith('.') || /[\u0000-\u001f]/.test(part))) fail(400, 'Invalid document path.');
    if (!(sections.includes(parts[0]) || (!directory && parts.length === 1 && ['_index.md', 'search.md'].includes(relative)))) fail(403, 'This path is outside the editable content.');
    if (!directory && !relative.endsWith('.md')) fail(400, 'Only Markdown documents can be edited.');
    let target = root;
    for (const part of parts) {
      target = path.join(target, part);
      try { if (fs.lstatSync(target).isSymbolicLink()) fail(403, 'Symbolic links cannot be edited.'); }
      catch (error) { if (error.code !== 'ENOENT') throw error; }
    }
    return target;
  }
  function read(relative) {
    const file = resolve(relative);
    if (!fs.existsSync(file) || !fs.statSync(file).isFile()) fail(404, 'Document not found.');
    const source = fs.readFileSync(file, 'utf8');
    return { path: relative, source, revision: revision(source) };
  }
  function url(relative, data = {}) {
    if (typeof data.url === 'string' && data.url.startsWith('/') && !data.url.startsWith('//')) return data.url;
    if (relative === '_index.md') return '/';
    let parts = relative.replace(/\.md$/, '').split('/');
    if (['index', '_index'].includes(parts.at(-1))) parts.pop();
    else if (typeof data.slug === 'string') parts[parts.length - 1] = slug(data.slug);
    return '/' + parts.map(part => encodeURIComponent(slug(part))).join('/') + '/';
  }
  function atomic(file, source) {
    const temp = path.join(path.dirname(file), `.workspace-${randomUUID()}.tmp`);
    try { fs.writeFileSync(temp, source, { flag: 'wx', mode: fs.statSync(file).mode & 0o777 }); fs.renameSync(temp, file); }
    finally { if (fs.existsSync(temp)) fs.unlinkSync(temp); }
  }
  async function save({ path: relative, source, revision: expected }) {
    const before = read(relative);
    if (expected !== before.revision) fail(409, 'This document changed outside the editor. Reload the latest version before saving. Your edits are still here.');
    const parsed = parseSource(source);
    if (!parsed.metadata.has('content_lang')) parsed.metadata.set('content_lang', 'en');
    if (!parsed.metadata.has('draft')) parsed.metadata.set('draft', true);
    parsed.metadata.set('lastmod', new Date().toISOString());
    const updated = `---\n${String(parsed.metadata)}---\n${parsed.body}`;
    const file = resolve(relative);
    atomic(file, updated);
    try { await rebuild(); }
    catch (error) {
      if (revision(fs.readFileSync(file, 'utf8')) === revision(updated)) atomic(file, before.source);
      throw error;
    }
    return { ...read(relative), url: url(relative, parsed.data) };
  }
  function groups(section) {
    if (!sections.includes(section)) fail(400, 'Unknown journal.');
    const result = [];
    function walk(relative, depth = 0) {
      if (depth > 16) return;
      const folder = resolve(relative, true);
      let title = relative.split('/').at(-1);
      const index = path.join(folder, '_index.md');
      if (fs.existsSync(index) && !fs.lstatSync(index).isSymbolicLink()) {
        try { title = parseSource(fs.readFileSync(index, 'utf8')).data.title; } catch { /* Folder name is a safe fallback. */ }
      }
      result.push({ path: relative, title, depth });
      for (const entry of fs.readdirSync(folder, { withFileTypes: true }).sort((a,b) => a.name.localeCompare(b.name))) {
        if (entry.isDirectory() && !entry.name.startsWith('.')) walk(`${relative}/${entry.name}`, depth + 1);
      }
    }
    walk(section);
    return result;
  }
  async function create({ kind, parent, title }) {
    if (!['document', 'group'].includes(kind)) fail(400, 'Choose Document or Group.');
    if (typeof title !== 'string' || !title.trim() || title.length > 180) fail(422, 'Enter a title of 1–180 characters.');
    const name = slug(title);
    if (!name || ['index', '_index'].includes(name)) fail(422, 'Choose a different title.');
    const directory = resolve(parent, true);
    if (!fs.existsSync(directory) || !fs.statSync(directory).isDirectory()) fail(404, 'Parent group not found.');
    const stem = path.join(directory, name);
    if (fs.existsSync(stem) || fs.existsSync(`${stem}.md`)) fail(409, 'A document or group with this name already exists here.');
    const relative = `${parent}/${name}${kind === 'group' ? '/_index.md' : '.md'}`;
    const now = new Date().toISOString();
    const source = `---\ntitle: ${JSON.stringify(title.trim())}\ndate: ${now}\nlastmod: ${now}\ndraft: true\ncontent_lang: en\n${kind === 'document' ? 'show_toc: true\n' : ''}---\n\n`;
    if (kind === 'group') fs.mkdirSync(stem);
    const file = resolve(relative);
    fs.writeFileSync(file, source, { flag: 'wx' });
    try { await rebuild(); }
    catch (error) {
      if (fs.existsSync(file) && fs.readFileSync(file, 'utf8') === source) fs.unlinkSync(file);
      if (kind === 'group' && fs.existsSync(stem) && !fs.readdirSync(stem).length) fs.rmdirSync(stem);
      throw error;
    }
    return { ...read(relative), url: url(relative), kind };
  }
  async function action({ path: relative, revision: expected, action, title, parent }) {
    if (!['rename', 'pin', 'copy', 'move', 'remove', 'delete'].includes(action)) fail(400, 'Unknown document operation.');
    if (['index.md', '_index.md'].includes(path.basename(relative || ''))) fail(400, 'Group pages cannot use document operations.');
    const before = read(relative);
    if (before.revision !== expected) fail(409, 'Document changed. Reload and try again.');
    const parsed = parseSource(before.source);
    if (action === 'rename') {
      if (typeof title !== 'string' || !title.trim() || title.length > 180) fail(422, 'Enter a title of 1–180 characters.');
      parsed.metadata.set('title', title.trim());
    }
    if (action === 'pin') {
      const pinned = parsed.data.sidebar_pinned === true;
      parsed.metadata.set('sidebar_pinned', !pinned);
    }
    if (['rename', 'pin'].includes(action)) return save({ ...before, source: `---\n${String(parsed.metadata)}---\n${parsed.body}` });
    const file = resolve(relative);
    if (action === 'delete') {
      const trash = path.join(root, '.workspace-trash');
      if (fs.existsSync(trash) && fs.lstatSync(trash).isSymbolicLink()) fail(403, 'Invalid trash directory.');
      fs.mkdirSync(trash, { recursive: true });
      const backup = path.join(trash, `${randomUUID()}.md`);
      fs.renameSync(file, backup);
      try { await rebuild(); } catch (error) { fs.renameSync(backup, file); throw error; }
      return { url: '/' + relative.split('/')[0] + '/', deleted: true };
    }
    if (action === 'remove') parent = relative.split('/')[0];
    const directory = resolve(parent, true);
    if (!fs.existsSync(directory) || !fs.statSync(directory).isDirectory()) fail(404, 'Parent group not found.');
    let name = path.basename(relative, '.md');
    if (action === 'copy') {
      let suffix = 1;
      while (fs.existsSync(path.join(directory, `${name}-copy-${suffix}.md`)) || fs.existsSync(path.join(directory, `${name}-copy-${suffix}`))) suffix++;
      name = `${name}-copy-${suffix}`;
      parsed.metadata.set('title', `${parsed.data.title}（副本）`);
      for (const key of ['url', 'slug', 'aliases', 'sidebar_pinned']) parsed.metadata.delete(key);
      parsed.metadata.set('draft', true);
    }
    const target = `${parent}/${name}.md`;
    if (target === relative) fail(409, 'Document is already in this group.');
    if (fs.existsSync(resolve(target)) || fs.existsSync(path.join(directory, name))) fail(409, 'A document with this name already exists here.');
    // Keep the public address stable when reorganizing a document.
    if (action !== 'copy') parsed.metadata.set('url', url(relative, parsed.data));
    const source = `---\n${String(parsed.metadata)}---\n${parsed.body}`;
    fs.writeFileSync(resolve(target), source, { flag: 'wx' });
    if (action !== 'copy') fs.unlinkSync(file);
    try { await rebuild(); }
    catch (error) {
      if (action !== 'copy') fs.writeFileSync(file, before.source, { flag: 'wx' });
      fs.unlinkSync(resolve(target));
      throw error;
    }
    return { ...read(target), url: url(target, parseSource(source).data) };
  }
  return { read, save, create, groups, action };
}
