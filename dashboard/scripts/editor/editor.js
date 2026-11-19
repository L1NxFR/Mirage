import { basicSetup, EditorView } from 'codemirror';
import { keymap } from '@codemirror/view';
import { markdown } from '@codemirror/lang-markdown';
import { undo, redo } from '@codemirror/commands';
import katex from 'katex';
import { sanitizePreview } from './sanitize.mjs';
import { parseMarkdown } from './markdown.mjs';
import { parseDocument } from 'yaml';
import { readSummary, writeSummary } from './summary.mjs';
import { connect, request } from './api.js';

export function setupEditor() {
  const dialog = document.getElementById('article-editor');
  if (!dialog) return;
  const trigger = document.querySelector('[data-edit-article]');
  const status = dialog.querySelector('.editor-status');
  const metadata = dialog.querySelector('[data-editor-metadata]');
  const preview = dialog.querySelector('[data-editor-preview]');
  const summary = dialog.querySelector('[data-editor-summary]');
  const summaryError = dialog.querySelector('[data-summary-error]');
  const saveButton = dialog.querySelector('[data-editor-save]');
  const reloadButton = dialog.querySelector('[data-editor-reload]');
  const closeWarning = dialog.querySelector('[data-unsaved-warning]');
  let editor, baseline = '', revision, pending = false, writable = false, changedOnDisk = false, savedUrl;
  trigger.hidden = false;
  const source = () => `---\n${metadata.value.trimEnd()}\n---\n${editor?.state.doc.toString() || ''}`;
  const dirty = () => Boolean(editor && source() !== baseline);
  const setStatus = (text, error = false) => { status.textContent = text; status.classList.toggle('is-error', error); };
  function update(syncSummary = true) {
    if (!editor) return;
    saveButton.disabled = !writable || pending || changedOnDisk || !dirty();
    if (!pending) setStatus(dirty() ? 'Unsaved changes' : 'All changes saved');
    let summaryText = '';
    try {
      summaryText = readSummary(metadata.value);
      if (syncSummary && summary.value !== summaryText) summary.value = summaryText;
      if (!syncSummary) summaryText = summary.value;
      summary.disabled = false;
      summaryError.hidden = true;
    } catch (error) {
      summary.disabled = true;
      summaryError.textContent = error.message;
      summaryError.hidden = false;
      setStatus(error.message, true);
    }
    let title = 'Untitled';
    try { title = String(parseDocument(metadata.value).get('title') || title); } catch { /* Server validates metadata on save. */ }
    dialog.querySelector('[data-editor-document-title]').textContent = title;
    const heading = document.createElement('h1'); heading.textContent = title;
    preview.replaceChildren(heading);
    if (summaryText.trim()) {
      const section = document.createElement('section');
      section.className = 'workspace-summary-preview';
      section.setAttribute('aria-label', 'Summary');
      section.append(renderMarkdown(summaryText));
      preview.append(section);
    }
    preview.append(renderMarkdown(editor.state.doc.toString()));
  }
  function renderMarkdown(markdownSource) {
    // Only sanitized DOM nodes enter the preview; scripts, handlers, and unsafe URLs are removed.
    const { html, formulas } = parseMarkdown(markdownSource);
    const fragment = sanitizePreview(html);
    for (const input of fragment.querySelectorAll('input')) {
      if (input.type === 'checkbox') input.disabled = true; else input.remove();
    }
    for (const element of fragment.querySelectorAll('[href],[src]')) {
      for (const attr of ['href','src']) {
        const value = element.getAttribute(attr);
        if (!value || /^(?:[a-z]+:|\/|#)/i.test(value)) continue;
        const parts = dialog.dataset.path.split('/'); parts.pop();
        let resolved = new URL(value, `https://preview.invalid/${parts.join('/')}/`).pathname;
        if (resolved.startsWith('/Attachments/')) resolved = '/attachments/' + resolved.slice('/Attachments/'.length);
        else if (resolved.startsWith('/Excalidraw/')) resolved = '/excalidraw/' + resolved.slice('/Excalidraw/'.length);
        else resolved = value;
        element.setAttribute(attr, resolved);
      }
    }
    // Render only the captured TeX after sanitizing user HTML. KaTeX needs its
    // own layout styles; trust:false keeps HTML/URL commands disabled.
    for (const element of fragment.querySelectorAll('[data-workspace-math]')) {
      const formula = formulas[element.dataset.workspaceMath];
      element.removeAttribute('data-workspace-math');
      if (formula) katex.render(formula.text, element, {
        displayMode: formula.displayMode, output: 'htmlAndMathml',
        throwOnError: false, strict: 'ignore', trust: false
      });
    }
    return fragment;
  }
  async function load() {
    pending = true; saveButton.disabled = true; reloadButton.hidden = true; setStatus('Loading document…');
    try {
      writable = Boolean(await connect());
      const data = writable ? await request(`document?path=${encodeURIComponent(dialog.dataset.path)}`) :
        { source: await fetch(dialog.dataset.sourceUrl).then(r=>{if(!r.ok) throw new Error('Could not load this document.'); return r.text();}) };
      const match = data.source.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/);
      if (!match) throw new Error('This document needs YAML metadata.');
      metadata.value = match[1]; revision = data.revision; changedOnDisk = false;
      editor?.destroy();
      editor = new EditorView({
        doc:data.source.slice(match[0].length), parent:dialog.querySelector('[data-editor-code]'),
        extensions:[basicSetup, markdown(), EditorView.lineWrapping,
          EditorView.contentAttributes.of({'aria-label':'Markdown source',spellcheck:'false'}),
          keymap.of([{key:'Mod-s',run:()=>{save();return true;}},{key:'Mod-b',run:()=>{insert('**','**','bold text');return true;}},{key:'Mod-i',run:()=>{insert('*','*','italic text');return true;}}]),
          EditorView.updateListener.of(change=>{if(change.docChanged)update();})]
      });
      baseline=source(); pending=false; update();
      if (!writable) setStatus('Local editing is unavailable. Run npm run dev in this repository to enable saving.',true);
      editor.focus();
    } catch(error) { pending=false; setStatus(error.message,true); reloadButton.hidden=false; }
  }
  async function save() {
    if (!editor || pending || !writable || changedOnDisk || !dirty()) return;
    pending=true; saveButton.disabled=true; setStatus('Saving and rebuilding…');
    const submitted=source();
    try {
      const result=await request('save',{path:dialog.dataset.path,source:submitted,revision});
      const match=result.source.match(/^---\n([\s\S]*?)\n---\n/);
      // Edits made while the request runs remain unsaved, rather than being overwritten.
      if (source()===submitted) { metadata.value=match[1]; baseline=source(); }
      else { baseline=result.source; }
      revision=result.revision; savedUrl=result.url;
      setStatus(dirty()?'Saved. New edits are still unsaved.':'Saved to repository');
    } catch(error) {
      if(error.status===409) {changedOnDisk=true;reloadButton.hidden=false;}
      setStatus(error.message,true);
    } finally {pending=false;saveButton.disabled=!writable||changedOnDisk||!dirty();}
  }
  function insert(before,after='',placeholder='text') {
    if(!editor) return;
    const selection=editor.state.selection.main;
    const chosen=editor.state.sliceDoc(selection.from,selection.to)||placeholder;
    editor.dispatch({changes:{from:selection.from,to:selection.to,insert:before+chosen+after},selection:{anchor:selection.from+before.length,head:selection.from+before.length+chosen.length}});
    editor.focus();
  }
  function close(discard=false) {
    if(pending) {setStatus('Wait for the current operation to finish.');return;}
    if(dirty()&&!discard) {closeWarning.hidden=false;return;}
    if(discard && editor) baseline=source();
    closeWarning.hidden=true;dialog.close();trigger.focus();
    if(savedUrl) location.assign(savedUrl);
    else if(discard) {editor?.destroy();editor=null;}
  }
  trigger.addEventListener('click',async()=>{dialog.showModal();if(!editor)await load();else editor.focus();});
  saveButton.addEventListener('click',save);
  metadata.addEventListener('input',update);
  summary.addEventListener('input', () => {
    try {
      metadata.value = writeSummary(metadata.value, summary.value);
      update(false);
    } catch (error) {
      summaryError.textContent = error.message;
      summaryError.hidden = false;
      setStatus(error.message, true);
    }
  });
  summary.addEventListener('keydown', event => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
      event.preventDefault(); save();
    }
  });
  reloadButton.addEventListener('click',()=>{if(dirty()) {closeWarning.hidden=false;setStatus('Copy your edits before reloading the changed file.',true);return;} load();});
  dialog.querySelector('[data-editor-close]').addEventListener('click',()=>close());
  dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
  dialog.querySelector('[data-keep-editing]').addEventListener('click',()=>{closeWarning.hidden=true;editor?.focus();});
  dialog.querySelector('[data-discard]').addEventListener('click',()=>close(true));
  window.addEventListener('beforeunload',event=>{if(dirty()||pending){event.preventDefault();event.returnValue='';}});
  dialog.querySelectorAll('[data-editor-mode]').forEach(button=>button.addEventListener('click',()=>{
    dialog.dataset.mode=button.dataset.editorMode;
    dialog.querySelectorAll('[data-editor-mode]').forEach(item=>item.setAttribute('aria-pressed',String(item===button)));
    editor?.requestMeasure();
  }));
  const actions={bold:()=>insert('**','**','bold text'),italic:()=>insert('*','*','italic text'),heading:()=>insert('\n## ','\n','Heading'),link:()=>insert('[','](https://example.com)','link text'),code:()=>insert('\n```\n','\n```\n','code'),list:()=>insert('\n- ','\n','List item'),undo:()=>editor&&undo(editor),redo:()=>editor&&redo(editor)};
  dialog.querySelectorAll('[data-format]').forEach(button=>button.addEventListener('click',()=>actions[button.dataset.format]?.()));
  // Preview links do not navigate away from unsaved edits.
  preview.addEventListener('click',event=>{if(event.target.closest('a'))event.preventDefault();});
  if(new URL(location.href).searchParams.get('edit')==='1') {history.replaceState(null,'',location.pathname);trigger.click();}
}
