const { test } = require('node:test');
const assert = require('node:assert/strict');
const { parse, search, snippet } = require('../site/static/js/search-core.js');
const pages = [
  { title: '集体通信', uri: '/collectives/', content: 'GPU 通信。AllReduce uses NCCL.', sections: [
    { title: '定义', anchor: '定义', text: 'GPU 通信' },
    { title: 'NVIDIA NCCL', anchor: 'nvidia-nccl', text: 'AllReduce uses NCCL.' }
  ] },
  { title: 'Collective Communication', uri: '/guide/', content: 'A collective communication guide with AllGather.', sections: [
    { title: 'AllGather', anchor: 'allgather', text: 'A collective communication guide with AllGather.' }
  ] }
];
test('Chinese matches without spaces, with correct section anchors', () => {
  const result = search(pages, '通信');
  assert.equal(result[0].uri, '/collectives/');
  assert.equal(search(pages, 'NCCL')[0].sections[0].anchor, 'nvidia-nccl');
});
test('AND across sections, OR alternatives, and quoted phrases', () => {
  assert.equal(search(pages, 'GPU NCCL').length, 1);
  assert.equal(search(pages, 'GPU AllGather').length, 0);
  assert.equal(search(pages, 'GPU | AllGather').length, 2);
  assert.equal(search(pages, '"collective communication"')[0].uri, '/guide/');
  assert.equal(search(pages, '"communication collective"').length, 0);
});
test('empty input, literal punctuation, and malformed quotes', () => {
  assert.deepEqual(parse(' | '), []);
  assert.deepEqual(search(pages, ''), []);
  assert.deepEqual(search(pages, '[.*]'), []);
  assert.throws(() => parse('"unfinished'), /double quotes/);
});
test('case and compatibility forms match; snippets retain matching context', () => {
  assert.equal(search(pages, 'ｎｃｃｌ')[0].uri, '/collectives/');
  const text = 'a'.repeat(200) + 'GPU 通信' + 'b'.repeat(200);
  const preview = snippet(text, ['通信']);
  assert.ok(preview.includes('通信'));
  assert.ok(preview.length <= 152);
});
