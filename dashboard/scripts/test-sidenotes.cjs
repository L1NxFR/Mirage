const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const { readFileSync } = require('node:fs');
const source = readFileSync(require('node:path').join(__dirname, '../site/static/js/sidenotes.js'), 'utf8');

function fixture(hash = '') {
  const callbacks = {}, frames = new Map();
  let serial = 0, scrolled = 0;
  const classes = () => ({ values: new Set(), toggle(name, enabled) { enabled ? this.values.add(name) : this.values.delete(name); } });
  const style = () => ({ setProperty(name, value) { this[name] = value; }, removeProperty(name) { delete this[name]; } });
  const notes = [100, 80].map((height, i) => ({ id: `fn:${i + 1}`, height, style: style(), dataset: {},
    getBoundingClientRect() { return { height: this.height }; }, scrollIntoView() { scrolled++; } }));
  const references = [450, 500].map((top, i) => ({ id: `fnref:${i + 1}`, hash: `#fn:${i + 1}`, textContent: `${i + 1}`,
    getBoundingClientRect: () => ({ top }), scrollIntoView() { scrolled++; } }));
  const toc = { getBoundingClientRect: () => ({ bottom: 600 }) };
  const container = { right: 1132, classList: classes(), querySelector: () => toc,
    getBoundingClientRect() { return { right: this.right }; } };
  const article = { classList: classes(), style: style(), children: [], closest: () => container,
    querySelectorAll: selector => selector.includes('ol') ? notes : references,
    getBoundingClientRect: () => ({ top: 400, right: 900 }), addEventListener() {} };
  const media = { matches: true, addEventListener: (_, fn) => { callbacks.media = fn; } };
  vm.runInNewContext(source, {
    document: { querySelector: () => article, getElementById: id => [...notes, ...references].find(n => n.id === id) },
    window: { matchMedia: () => media, addEventListener: (event, fn) => { callbacks[event] = fn; } },
    location: { hash },
    requestAnimationFrame: fn => { frames.set(++serial, fn); return serial; },
    cancelAnimationFrame: id => frames.delete(id),
    ResizeObserver: class { constructor(fn) { callbacks.resizeObserver = fn; } observe() {} }
  });
  function flush() {
    for (let i = 0; frames.size; i++) {
      assert.ok(i < 10, 'Layout must settle');
      const pending = [...frames.values()]; frames.clear(); pending.forEach(fn => fn());
    }
  }
  flush();
  return { article, container, notes, media, callbacks, flush, scrollCount: () => scrolled };
}
test('notes avoid the TOC and each other, including after a note grows', () => {
  const f = fixture();
  assert.equal(f.notes[0].style.top, '224px');
  assert.equal(f.notes[1].style.top, '340px');
  assert.equal(f.article.style.minHeight, '436px');
  f.notes[0].height = 250;
  f.callbacks.resizeObserver(); f.flush();
  assert.equal(f.notes[1].style.top, '490px');
  assert.equal(f.article.style.minHeight, '586px');
});
test('narrow views reset note positioning and restore it when widened', () => {
  const f = fixture();
  f.media.matches = false; f.callbacks.media(); f.flush();
  assert.equal(f.article.classList.values.has('sidenotes-ready'), false);
  assert.equal(f.container.classList.values.has('has-margin-notes'), false);
  assert.equal(f.article.style.minHeight, '');
  assert.equal(f.notes[0].style.top, '');
  f.media.matches = true; f.callbacks.media(); f.flush();
  assert.equal(f.article.classList.values.has('sidenotes-ready'), true);
  assert.equal(f.notes[0].style.top, '224px');
});
test('actual rail space, not only viewport width, controls enhancement', () => {
  const f = fixture();
  f.container.right = 1080; f.callbacks.resize(); f.flush();
  assert.equal(f.article.classList.values.has('sidenotes-ready'), false);
});
test('direct footnote links follow the relocated note only on initial layout', () => {
  const f = fixture('#fn%3A2');
  assert.equal(f.scrollCount(), 1);
  f.callbacks.resize(); f.flush();
  assert.equal(f.scrollCount(), 1);
});
