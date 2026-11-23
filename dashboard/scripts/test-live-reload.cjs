const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');
const source = readFileSync(new URL('../site/static/js/workspace-live-reload.js', `file://${__filename}`), 'utf8');

function fixture(version = 'initial') {
  const state = { version: 'initial', open: false, reloads: 0, fail: false };
  vm.runInNewContext(source, {
    document: { currentScript: { dataset: { version } }, querySelector: () => state.open },
    setInterval: callback => { state.tick = callback; return 1; },
    clearInterval: () => { state.stopped = true; },
    fetch: async () => { if (state.fail) throw new Error('Offline'); return { ok: true, json: async () => ({ editable: true, version: state.version }) }; },
    location: { reload: () => { state.reloads++; } }
  });
  return state;
}

test('reloads only for a new successful build and defers while a dialog is open', async () => {
  const state = fixture();
  await state.tick();
  assert.equal(state.reloads, 0);
  state.version = 'updated'; state.open = true;
  await state.tick();
  assert.equal(state.reloads, 0);
  state.open = false;
  await state.tick();
  assert.equal(state.reloads, 1);
  assert.equal(state.stopped, true);
});

test('recovers after network failures and does not activate without a local version', async () => {
  const state = fixture();
  state.fail = true;
  await state.tick();
  assert.equal(state.reloads, 0);
  state.fail = false; state.version = 'restarted';
  await state.tick();
  assert.equal(state.reloads, 1);
  assert.equal(fixture('').tick, undefined);
});
