import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseDocument } from 'yaml';

const project = fileURLToPath(new URL('../../', import.meta.url));
const list = value => value == null || value === '' ? [] : Array.isArray(value) ? value : [value];
const has = (values, name) => values.some(value => String(value).toLowerCase() === name.toLowerCase());

// Identity is supplied by the editing agent, never inferred from a filesystem event.
export function attributeFiles(root, agent, files, { check = false } = {}) {
  if (!agent?.trim() || !files.length) throw new Error('Provide --agent NAME and project-relative file paths.');
  agent = agent.trim();
  root = fs.realpathSync(root);
  const registryPath = path.join(root, '.file-coauthors.json');
  const registry = fs.existsSync(registryPath) ? JSON.parse(fs.readFileSync(registryPath, 'utf8')) : {};
  const writes = [];
  const missing = [];
  let registryChanged = false;
  for (const file of files) {
    const absolute = path.resolve(root, file);
    const relative = path.relative(root, absolute).split(path.sep).join('/');
    if (relative.startsWith('../') || path.isAbsolute(relative) || !relative || relative.split('/').some(part => ['.git', 'node_modules', '.file-coauthors.json'].includes(part))) throw new Error(`Unsupported path: ${file}`);
    const real = fs.realpathSync(absolute);
    if (real !== absolute || !fs.statSync(absolute).isFile()) throw new Error(`Expected a regular project file: ${file}`);
    if (relative.startsWith('dashboard/site/content/') && relative.endsWith('.md') && !relative.includes('/Templates/')) {
      const source = fs.readFileSync(absolute, 'utf8');
      const match = source.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/);
      if (!match) throw new Error(`Missing YAML front matter: ${file}`);
      const doc = parseDocument(match[1]);
      if (doc.errors.length) throw new Error(`Invalid YAML: ${file}`);
      const authors = list(doc.get('author')?.toJSON?.() ?? doc.get('author'));
      const legacy = list(doc.get('coauthors')?.toJSON?.() ?? doc.get('coauthors'));
      const merged = [];
      for (const name of [...authors, ...legacy]) if (!has(merged, String(name))) merged.push(name);
      if (has(merged, agent) && !doc.has('coauthors')) continue;
      missing.push(relative);
      if (check) continue;
      if (!authors.length) {
        const legacyAgent = path.basename(file).startsWith('agent-') || String(doc.get('title')).startsWith('[Agent]');
        const config = parseDocument(fs.readFileSync(path.join(root, 'dashboard/site/hugo.yaml'), 'utf8')).toJS();
        const original = legacyAgent ? '待确认代理' : config.params.author.default;
        if (!has(merged, original)) merged.unshift(original);
      }
      if (!has(merged, agent)) merged.push(agent);
      doc.set('author', merged.length === 1 ? merged[0] : merged);
      doc.delete('coauthors');
      doc.set('lastmod', new Date(Date.now() + 8 * 60 * 60 * 1000).toISOString().replace('Z', '+08:00'));
      writes.push([absolute, `---\n${doc.toString()}---\n${source.slice(match[0].length)}`]);
    } else {
      const names = registry[relative] || [];
      if (!has(names, agent)) {
        missing.push(relative);
        registry[relative] = [...names, agent];
        registryChanged = true;
      }
    }
  }
  if (!check) {
    for (const [file, source] of writes) fs.writeFileSync(file, source);
    if (registryChanged) fs.writeFileSync(registryPath, JSON.stringify(registry, null, 2) + '\n');
  }
  return missing;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const args = process.argv.slice(2);
    const check = args.includes('--check');
    const filtered = args.filter(arg => arg !== '--check');
    if (filtered[0] !== '--agent') throw new Error('Usage: node dashboard/scripts/attribute-files.mjs [--check] --agent NAME FILE...');
    const missing = attributeFiles(project, filtered[1], filtered.slice(2), { check });
    console.log(`${check ? 'Missing attribution' : 'Updated attribution'}: ${missing.length}`);
    if (check && missing.length) { console.error(missing.join('\n')); process.exitCode = 1; }
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
