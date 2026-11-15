import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { randomBytes } from 'node:crypto';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { createStore, WorkspaceError } from './workspace-store.mjs';
const exec = promisify(execFile);
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
process.chdir(repo);
const args = process.argv.slice(2);
const option = name => { const i = args.indexOf(name); return i < 0 ? undefined : args[i + 1]; };
const port = Number(option('--port') || 1313);
if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Choose a port between 1024 and 65535.');
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'research-workspace-'));
let output, generation = 0, queue = Promise.resolve();
const token = randomBytes(32).toString('hex');
async function rebuild() {
  const destination = path.join(temp, `public-${++generation}`);
  try {
    await exec('hugo', ['--source', path.join(repo, 'site'), '--themesDir', path.dirname(repo),
      '--theme', path.basename(repo), '--environment', 'workspace', '--buildDrafts', '--baseURL', `http://localhost:${port}/`, '--destination', destination],
      { cwd: repo, timeout: 30000, maxBuffer: 2_000_000 });
    const previous = output; output = destination;
    if (previous) fs.rmSync(previous, { recursive: true, force: true });
  } catch (error) {
    fs.rmSync(destination, { recursive: true, force: true });
    const message = (error.stderr || error.stdout || '').split('\n').find(line => /error/i.test(line));
    throw new WorkspaceError(422, `The site could not be built. ${message?.slice(0, 350) || 'Check the Markdown and shortcodes.'}`);
  }
}
const serial = task => { const next = queue.then(task); queue = next.catch(() => {}); return next; };
const store = createStore(path.join(repo, 'site/content'), rebuild);
const json = (response, status, data) => { response.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' }); response.end(JSON.stringify(data)); };
async function body(request) {
  if (!request.headers['content-type']?.startsWith('application/json')) throw new WorkspaceError(415, 'JSON is required.');
  let value = '';
  for await (const chunk of request) {
    value += chunk;
    if (Buffer.byteLength(value) > 2_100_000) throw new WorkspaceError(413, 'Document is too large.');
  }
  try { return JSON.parse(value); } catch { throw new WorkspaceError(400, 'Invalid JSON.'); }
}
const types = { '.html':'text/html; charset=utf-8', '.css':'text/css', '.js':'text/javascript', '.json':'application/json', '.svg':'image/svg+xml', '.png':'image/png', '.jpg':'image/jpeg', '.webp':'image/webp', '.woff2':'font/woff2', '.woff':'font/woff', '.ttf':'font/ttf', '.otf':'font/otf', '.md':'text/plain; charset=utf-8', '.xml':'application/xml', '.pdf':'application/pdf' };
const server = http.createServer(async (request, response) => {
  try {
    const host = request.headers.host;
    if (![`localhost:${port}`, `127.0.0.1:${port}`].includes(host)) throw new WorkspaceError(403, 'Invalid host.');
    const url = new URL(request.url, `http://${host}`);
    if (url.pathname.startsWith('/api/workspace/')) {
      if (request.headers['sec-fetch-site'] === 'cross-site' || (request.headers.origin && request.headers.origin !== `http://${host}`)) throw new WorkspaceError(403, 'Cross-origin access is not allowed.');
      if (url.pathname === '/api/workspace/status' && request.method === 'GET') return json(response, 200, { editable: true, token });
      if (request.headers['x-workspace-token'] !== token) throw new WorkspaceError(403, 'Reload the page to reconnect to the workspace.');
      const route = url.pathname.slice('/api/workspace/'.length);
      if (request.method === 'GET' && route === 'document') return json(response, 200, store.read(url.searchParams.get('path')));
      if (request.method === 'GET' && route === 'groups') return json(response, 200, store.groups(url.searchParams.get('section')));
      if (request.method === 'POST' && ['save','create','action'].includes(route)) {
        const data = await body(request);
        if (!data || typeof data !== 'object' || Array.isArray(data)) throw new WorkspaceError(400, 'Invalid request.');
        return json(response, 200, await serial(() => store[route](data)));
      }
      throw new WorkspaceError(404, 'Unknown operation.');
    }
    if (!['GET','HEAD'].includes(request.method)) throw new WorkspaceError(405, 'Method not allowed.');
    const relative = decodeURIComponent(url.pathname);
    if (relative.split('/').some(part => part.startsWith('.') || part.includes('\\'))) throw new WorkspaceError(404, 'Not found.');
    let file = path.join(output, relative);
    if (fs.existsSync(file) && fs.statSync(file).isDirectory()) file = path.join(file, 'index.html');
    if (!fs.existsSync(file) || !fs.statSync(file).isFile()) throw new WorkspaceError(404, 'Not found.');
    const bytes = fs.readFileSync(file);
    response.writeHead(200, { 'Content-Type': types[path.extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-store', 'X-Content-Type-Options':'nosniff', 'X-Frame-Options':'SAMEORIGIN' });
    response.end(request.method === 'HEAD' ? undefined : bytes);
  } catch (error) { json(response, error.status || 500, { error: error.status ? error.message : 'The operation could not be completed.' }); }
});
try { await rebuild(); } catch (error) { console.error(error.message); fs.rmSync(temp,{recursive:true,force:true}); process.exit(1); }
server.listen(port, '127.0.0.1', () => console.log(`Research workspace: http://localhost:${port}/ (editing saves directly to this repository)`));
server.on('error', error => { console.error(error.message); cleanup(); });
const watchers = [];
let timer;
for (const directory of ['site/content', 'site/layouts', 'site/static', 'site/data', 'layouts']) {
  watchers.push(fs.watch(path.join(repo, directory), { recursive: true }, (_, filename) => {
    if (!filename || /(^|\/)\./.test(filename)) return;
    clearTimeout(timer);
    timer = setTimeout(() => serial(rebuild).catch(error => console.error(error.message)), 300);
  }));
}
watchers.push(fs.watch(path.join(repo,'site/hugo.yaml'), () => { clearTimeout(timer); timer=setTimeout(()=>serial(rebuild).catch(error=>console.error(error.message)),300); }));
function cleanup() { clearTimeout(timer); watchers.forEach(watcher=>watcher.close()); server.close(); fs.rmSync(temp,{recursive:true,force:true}); process.exit(); }
process.on('SIGINT', cleanup); process.on('SIGTERM', cleanup);
