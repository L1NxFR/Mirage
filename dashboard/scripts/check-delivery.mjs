import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const canonical = value => fs.realpathSync(value);
function gitRoot(directory) {
  return canonical(execFileSync('git', ['-C', directory, 'rev-parse', '--show-toplevel'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim());
}
function inside(root, file) {
  const relative = path.relative(root, file);
  return relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative);
}
function localURL(value) {
  const url = new URL(value);
  if (url.protocol !== 'http:' || !['localhost', '127.0.0.1'].includes(url.hostname) || url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('Dashboard URL must be a local HTTP origin, for example http://127.0.0.1:23130/.');
  }
  return url;
}
async function request(url) {
  const response = await fetch(url, { redirect: 'error', signal: AbortSignal.timeout(5000) });
  if (!response.ok) throw new Error(`HTTP ${response.status}: ${url}`);
  return response;
}

export async function checkDelivery({ targetRoot, operationRoot = process.cwd(), files = [], url, pages = [] }) {
  if (!targetRoot || !path.isAbsolute(targetRoot)) throw new Error('Explicit absolute --target-root or DELIVERY_ROOT is required; the current directory is not a delivery target.');
  const target = canonical(targetRoot);
  if (gitRoot(target) !== target) throw new Error(`Target must be the project Git root: ${target}`);
  const actual = gitRoot(operationRoot);
  if (actual !== target) throw new Error(`Delivery directory mismatch.\nOperation root: ${actual}\nTarget root: ${target}`);
  const contentRoot = canonical(path.join(target, 'dashboard/site/content'));
  if (!inside(target, contentRoot) || !fs.statSync(contentRoot).isDirectory()) {
    throw new Error(`Dashboard content directory is outside target root: ${contentRoot}`);
  }
  const checkedFiles = files.map(file => {
    if (path.isAbsolute(file)) throw new Error(`File must be relative to target root: ${file}`);
    const resolved = canonical(path.resolve(target, file));
    if (!inside(target, resolved) || !fs.statSync(resolved).isFile()) throw new Error(`File is not inside target root: ${file}`);
    return resolved;
  });
  if (pages.length && !url) throw new Error('--page requires --url; a file check does not verify rendering.');
  if (url) {
    const base = localURL(url);
    const status = await (await request(new URL('/api/workspace/status', base))).json();
    if (typeof status.projectRoot !== 'string' || typeof status.contentRoot !== 'string' || canonical(status.projectRoot) !== target || canonical(status.contentRoot) !== contentRoot) {
      throw new Error(`Dashboard directory mismatch or missing identity. Expected project root: ${target}`);
    }
    for (const page of pages) {
      if (!page.startsWith('/') || page.startsWith('//') || page.includes('\\')) throw new Error(`Page must be a local absolute URL path: ${page}`);
      const response = await request(new URL(page, base));
      if (!response.headers.get('content-type')?.includes('text/html')) throw new Error(`Page is not HTML: ${page}`);
      if (!(await response.text()).trim()) throw new Error(`Page is empty: ${page}`);
    }
  }
  return { targetRoot: target, operationRoot: actual, files: checkedFiles, dashboardChecked: Boolean(url), pages };
}

export function parseDeliveryArgs(args, env = process.env) {
  const result = { targetRoot: env.DELIVERY_ROOT, files: [], pages: [] };
  for (let i = 0; i < args.length; i++) {
    const flag = args[i];
    if (!['--target-root', '--file', '--url', '--page'].includes(flag) || !args[i + 1] || args[i + 1].startsWith('--')) throw new Error(`Invalid or incomplete option: ${flag}`);
    const value = args[++i];
    if (flag === '--file') result.files.push(value);
    else if (flag === '--page') result.pages.push(value);
    else result[flag === '--target-root' ? 'targetRoot' : 'url'] = value;
  }
  return result;
}

if (process.argv[1] && canonical(process.argv[1]) === canonical(fileURLToPath(import.meta.url))) {
  try {
    if (process.argv.slice(2).some(arg => ['--help', '-h'].includes(arg))) {
      console.log('Usage: node scripts/check-delivery.mjs --target-root /absolute/project [--file relative/path] [--url http://127.0.0.1:23130/ --page /page/]');
    } else {
      const result = await checkDelivery(parseDeliveryArgs(process.argv.slice(2)));
      console.log(`Delivery check passed: ${result.targetRoot}\nFiles checked: ${result.files.length}\nDashboard identity: ${result.dashboardChecked ? 'passed' : 'not checked'}\nHTML pages checked: ${result.pages.length}`);
    }
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
