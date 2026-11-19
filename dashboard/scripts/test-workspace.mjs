import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createStore, sections, parseSource } from './workspace-store.mjs';
function fixture(t, rebuild) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(),'workspace-test-'));
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  for (const section of sections) { fs.mkdirSync(path.join(root,section)); fs.writeFileSync(path.join(root,section,'_index.md'), `---\ntitle: ${section}\n---\n`); }
  fs.writeFileSync(path.join(root,'_index.md'),'---\ntitle: Overview\n---\nOriginal\n');
  return { root, store:createStore(root,rebuild) };
}
test('creates nested groups/documents and persists Markdown with lastmod',async t=>{
  const {root,store}=fixture(t);
  const group=await store.create({kind:'group',parent:'meetings',title:'Weekly Notes'});
  assert.equal(group.path,'meetings/weekly-notes/_index.md');
  assert.equal(store.groups('meetings')[1].title,'Weekly Notes');
  const doc=await store.create({kind:'document',parent:'meetings/weekly-notes',title:'First Meeting'});
  const saved=await store.save({...doc,source:doc.source+'## Decisions\n\n- [ ] Write tests\n'});
  assert.match(fs.readFileSync(path.join(root,doc.path),'utf8'),/Write tests/);
  assert.match(parseSource(saved.source).data.lastmod,/T/);
  assert.equal(saved.url,'/meetings/weekly-notes/first-meeting/');
  await assert.rejects(store.create({kind:'group',parent:'meetings/weekly-notes',title:'First Meeting'}),{status:409});
});
test('rejects stale edits and invalid metadata without changing files',async t=>{
  const {root,store}=fixture(t); const original=store.read('_index.md');
  fs.writeFileSync(path.join(root,'_index.md'),original.source+'External change\n');
  await assert.rejects(store.save({...original,source:original.source+'My edit'}),{status:409});
  assert.match(store.read('_index.md').source,/External change/);
  await assert.rejects(store.save({...store.read('_index.md'),source:'invalid'}),{status:422});
  assert.match(store.read('_index.md').source,/External change/);
});
test('new documents default to drafts in every journal and stay editable until published',async t=>{
  const {store}=fixture(t);
  for (const section of sections) {
    const doc=await store.create({kind:'document',parent:section,title:'Private note'});
    assert.equal(parseSource(doc.source).data.draft,true);
    assert.equal(doc.url,`/${section}/private-note/`);
    const saved=await store.save({...doc,source:doc.source+'Draft work\n'});
    assert.equal(parseSource(saved.source).data.draft,true);
    assert.equal(saved.url,doc.url);
    const published=await store.save({...saved,source:saved.source.replace('draft: true','draft: false')});
    assert.equal(parseSource(published.source).data.draft,false);
    assert.equal(published.url,doc.url);
  }
});
test('new groups and documents saved without a draft property also default to drafts',async t=>{
  const {root,store}=fixture(t);
  for (const section of sections) {
    const group=await store.create({kind:'group',parent:section,title:'Draft group'});
    assert.equal(parseSource(group.source).data.draft,true);
  }
  const filename='related-work/imported.md';
  fs.writeFileSync(path.join(root,filename),'---\ntitle: Imported note\n---\nOriginal\n');
  const doc=store.read(filename);
  const saved=await store.save({...doc,source:doc.source+'Edited\n'});
  assert.equal(parseSource(saved.source).data.draft,true);
});
test('rejects traversal, private paths, symlinks, and unsupported operations',async t=>{
  const {root,store}=fixture(t);
  for(const p of ['../README.md','meetings/../_index.md','meetings/.secret.md','.obsidian/data.md','Attachments/a.md','meetings/a.txt']) assert.throws(()=>store.read(p));
  fs.symlinkSync(path.join(root,'_index.md'),path.join(root,'meetings/link.md'));
  assert.throws(()=>store.read('meetings/link.md'),{status:403});
  fs.symlinkSync(root,path.join(root,'meetings/link'));
  await assert.rejects(store.create({kind:'document',parent:'meetings/link',title:'Bad'}),{status:403});
  await assert.rejects(store.create({kind:'table',parent:'meetings',title:'Bad'}),{status:400});
});
test('failed builds restore edited files and remove only newly created files',async t=>{
  const {store}=fixture(t,async()=>{throw new Error('Broken shortcode');});
  const old=store.read('_index.md');
  await assert.rejects(store.save({...old,source:old.source+'Changed'}),/Broken shortcode/);
  assert.equal(store.read('_index.md').source,old.source);
  await assert.rejects(store.create({kind:'group',parent:'meetings',title:'Failed'}),/Broken shortcode/);
  assert.equal(store.groups('meetings').length,1);
});
test('documents and groups default to Chinese while explicit languages survive saves', async t => {
  const {store}=fixture(t);
  for (const section of sections) {
    for (const kind of ['document','group']) {
      const doc=await store.create({kind,parent:section,title:`中文${kind}`});
      assert.equal(parseSource(doc.source).data.content_lang,'zh-CN');
    }
  }
  const doc=store.read('_index.md');
  const saved=await store.save({...doc,source:doc.source+'Edited\n'});
  assert.equal(parseSource(saved.source).data.content_lang,'zh-CN');
  const english=await store.save({...saved,source:saved.source.replace('content_lang: zh-CN','content_lang: en')});
  assert.equal(parseSource(english.source).data.content_lang,'en');
});
test('document menu renames, pins, copies, moves, removes and backs up deletions', async t => {
  const { root, store } = fixture(t);
  await store.create({ kind: 'group', parent: 'meetings', title: 'Weekly' });
  let doc = await store.create({ kind: 'document', parent: 'meetings/weekly', title: 'Notes' });
  doc = await store.action({ ...doc, action: 'rename', title: 'New title' });
  assert.equal(parseSource(doc.source).data.title, 'New title');
  doc = await store.action({ ...doc, action: 'pin' });
  assert.equal(parseSource(doc.source).data.sidebar_pinned, true);
  doc = await store.action({ ...doc, action: 'pin' });
  assert.equal(parseSource(doc.source).data.sidebar_pinned, false);
  const copy = await store.action({ ...doc, action: 'copy', parent: 'meetings' });
  assert.notEqual(copy.url, doc.url);
  assert.equal(parseSource(copy.source).data.draft, true);
  const moved = await store.action({ ...doc, action: 'remove' });
  assert.equal(moved.path, 'meetings/notes.md');
  assert.equal(moved.url, doc.url);
  assert.throws(() => store.read(doc.path), { status: 404 });
  await assert.rejects(store.action({ ...copy, action: 'move', parent: '../outside' }));
  await assert.rejects(store.action({ ...moved, revision: 'stale', action: 'delete' }), { status: 409 });
  await store.action({ ...moved, action: 'delete' });
  assert.throws(() => store.read(moved.path), { status: 404 });
  const backup = fs.readdirSync(path.join(root, '.workspace-trash'))[0];
  assert.equal(fs.readFileSync(path.join(root, '.workspace-trash', backup), 'utf8'), moved.source);
});
test('document action build failures roll back copies, moves and deletions', async t => {
  let broken = false;
  const { store } = fixture(t, async () => { if (broken) throw new Error('build failed'); });
  await store.create({ kind: 'group', parent: 'meetings', title: 'Weekly' });
  const doc = await store.create({ kind: 'document', parent: 'meetings', title: 'Notes' });
  broken = true;
  for (const action of ['rename', 'pin', 'copy', 'move', 'delete']) {
    await assert.rejects(store.action({ ...doc, action, title: 'Changed', parent: 'meetings/weekly' }), /build failed/);
    assert.equal(store.read(doc.path).source, doc.source);
  }
  assert.throws(() => store.read('meetings/weekly/notes.md'), { status: 404 });
  assert.throws(() => store.read('meetings/weekly/notes-copy-1.md'), { status: 404 });
});

for (const instant of ['2026-11-15T16:00:01.123Z', '2026-06-30T23:59:59.999Z']) {
  test(`creation and saves use Beijing time at ${instant}`, async t => {
    t.mock.timers.enable({ apis: ['Date'], now: new Date(instant) });
    const { store } = fixture(t);
    const expected = new Date(Date.parse(instant) + 8 * 60 * 60 * 1000).toISOString().replace('Z', '+08:00');
    for (const kind of ['document', 'group']) {
      const doc = await store.create({ kind, parent: 'meetings', title: `Beijing ${kind}` });
      assert.equal(parseSource(doc.source).data.date, expected);
      assert.equal(parseSource(doc.source).data.lastmod, expected);
      const saved = await store.save({ ...doc, source: doc.source + 'Edited\n' });
      assert.equal(parseSource(saved.source).data.lastmod, expected);
      assert.equal(Date.parse(parseSource(saved.source).data.lastmod), Date.parse(instant));
    }
  });
}

test('Chinese document paths and text round-trip through creation and saving', async t => {
  const {store}=fixture(t);
  const group=await store.create({kind:'group',parent:'research-journey',title:'实验记录'});
  const doc=await store.create({kind:'document',parent:'research-journey/实验记录',title:'精度对比'});
  assert.equal(group.path,'research-journey/实验记录/_index.md');
  assert.equal(doc.path,'research-journey/实验记录/精度对比.md');
  assert.equal(doc.url,'/research-journey/'+encodeURIComponent('实验记录')+'/'+encodeURIComponent('精度对比')+'/');
  const saved=await store.save({...doc,source:doc.source+'## 结果\n\n中文正文与 English 混排。\n'});
  assert.equal(parseSource(saved.source).data.content_lang,'zh-CN');
  assert.match(saved.source,/中文正文与 English 混排。/);
  assert.equal(parseSource(saved.source).data.draft,true);
});
