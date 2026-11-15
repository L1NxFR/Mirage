const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');
const source = readFileSync(require('node:path').join(__dirname, '../site/static/js/toc.js'), 'utf8');

function page(hash = '') {
  const handlers = {}, frames = new Map();
  let next = 0;
  const window = { scrollY: 0, innerHeight: 600, addEventListener: (type, fn) => handlers[type] = fn };
  const location = { hash };
  const headings = ['定义', 'applications', 'nccl', 'algorithms'].map((id, i) => ({
    id, getBoundingClientRect: () => ({ top: [200, 700, 1100, 1200][i] - window.scrollY })
  }));
  const links = headings.map(heading => ({
    hash: '#' + encodeURIComponent(heading.id), attributes: {},
    setAttribute(name, value) { this.attributes[name] = value; },
    removeAttribute(name) { delete this.attributes[name]; }
  }));
  const toc = { querySelectorAll: () => links, addEventListener: (type, fn) => handlers['toc-' + type] = fn };
  const article = { contains: h => headings.includes(h), addEventListener() {} };
  const document = {
    documentElement: { scrollHeight: 1400 },
    getElementById: id => id === 'TableOfContents' ? toc : headings.find(h => h.id === id),
    querySelector: () => article
  };
  vm.runInNewContext(source, {
    window, document, location, getComputedStyle: () => ({ position: 'static' }),
    requestAnimationFrame: fn => { frames.set(++next, fn); return next; },
    cancelAnimationFrame: id => frames.delete(id),
    ResizeObserver: class { observe() {} }
  });
  const flush = () => {
    while (frames.size) {
      const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach(fn => fn());
    }
  };
  const current = () => links.filter(a => a.attributes['aria-current'] === 'location').map(a => a.hash);
  const scroll = y => { window.scrollY = y; handlers.scroll(); flush(); };
  flush();
  return { window, location, handlers, flush, current, scroll };
}

test('scrolling changes exactly one current section, including reverse scroll and page end', () => {
  const p = page();
  assert.deepEqual(p.current(), ['#%E5%AE%9A%E4%B9%89']);
  p.scroll(650); assert.deepEqual(p.current(), ['#applications']);
  p.scroll(800); assert.deepEqual(p.current(), ['#algorithms']);
  p.scroll(100); assert.deepEqual(p.current(), ['#%E5%AE%9A%E4%B9%89']);
});

test('clicked near-bottom heading stays selected until actual scrolling', () => {
  const p = page();
  p.scroll(800);
  p.location.hash = '#nccl'; p.handlers.hashchange(); p.flush();
  assert.deepEqual(p.current(), ['#nccl']);
  p.handlers.scroll(); p.flush(); assert.deepEqual(p.current(), ['#nccl']);
  p.scroll(650); assert.deepEqual(p.current(), ['#applications']);
});

test('direct links decode Chinese IDs and footnote hashes do not select missing sections', () => {
  const p = page('#%E5%AE%9A%E4%B9%89');
  assert.deepEqual(p.current(), ['#%E5%AE%9A%E4%B9%89']);
  p.scroll(650); p.location.hash = '#fn:2'; p.handlers.hashchange(); p.flush();
  assert.deepEqual(p.current(), ['#applications']);
});
