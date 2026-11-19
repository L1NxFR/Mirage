const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');

const source = readFileSync('site/static/js/print.js', 'utf8');

function fixture() {
  const events = {};
  const details = [{ open: false }, { open: true }, { open: false }];
  function element(overflowX, overflowY, preset = false) {
    const classes = new Set(preset ? ['print-expand'] : []);
    return {
      overflowX, overflowY, classes,
      classList: { contains: value => classes.has(value), add: value => classes.add(value), remove: value => classes.delete(value) }
    };
  }
  const elements = [element('auto', 'hidden'), element('visible', 'scroll'), element('visible', 'visible'), element('auto', 'auto', true)];
  const media = { matches: false, addEventListener: (_, fn) => { events.media = fn; } };
  vm.runInNewContext(source, {
    window: { addEventListener: (name, fn) => { events[name] = fn; }, matchMedia: () => media },
    document: { querySelectorAll: selector => selector.includes('details') ? details : elements },
    getComputedStyle: el => el
  });
  return { events, details, elements, media };
}

test('printing expands closed details and scroll containers, then restores the reading view', () => {
  const f = fixture();
  f.events.beforeprint();
  assert.deepEqual(f.details.map(el => el.open), [true, true, true]);
  assert.deepEqual(f.elements.map(el => el.classes.has('print-expand')), [true, true, false, true]);
  f.events.afterprint();
  assert.deepEqual(f.details.map(el => el.open), [false, true, false]);
  assert.deepEqual(f.elements.map(el => el.classes.has('print-expand')), [false, false, false, true]);
});

test('duplicate browser print events do not overwrite the original state', () => {
  const f = fixture();
  f.events.beforeprint();
  f.media.matches = true; f.events.media(f.media);
  f.events.beforeprint();
  f.events.afterprint();
  f.media.matches = false; f.events.media(f.media);
  assert.deepEqual(f.details.map(el => el.open), [false, true, false]);
  assert.equal(f.elements[0].classes.has('print-expand'), false);
});

test('closing print preview restores state and the next print uses current reading choices', () => {
  const f = fixture();
  f.media.matches = true; f.events.media(f.media);
  f.media.matches = false; f.events.media(f.media);
  f.details[0].open = true;
  f.details[1].open = false;
  f.events.beforeprint();
  f.events.afterprint();
  assert.deepEqual(f.details.map(el => el.open), [true, false, false]);
});
