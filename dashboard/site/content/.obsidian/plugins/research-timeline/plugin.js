'use strict';

const { Plugin, Modal, Component, Notice, MarkdownView, MarkdownRenderChild, MarkdownRenderer, setIcon } = require('obsidian');
const { parseTimeline, serializeTimeline, fenceTimeline, findTimelineBlocks, replacementFor } = require('./source');

function element(parent, tag, className = '', text = '') {
  const node = parent.ownerDocument.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  parent.appendChild(node);
  return node;
}

function icon(parent, type, className) {
  const svg = parent.ownerDocument.createElementNS('http://www.w3.org/2000/svg', 'svg');
  for (const [key, value] of Object.entries({ viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': '2', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true', class: className })) svg.setAttribute(key, value);
  const shapes = type === 'running' ? [['path', { d: 'M21 12a9 9 0 1 1-6.219-8.56' }]]
    : type === 'chevron' ? [['path', { d: 'm9 18 6-6-6-6' }]]
      : [['circle', { cx: '12', cy: '12', r: '10' }], ...(type === 'done' ? [['path', { d: 'm9 12 2 2 4-4' }]] : type === 'error' ? [['path', { d: 'M12 8v4m0 4h.01' }]] : [])];
  for (const [tag, attrs] of shapes) {
    const child = parent.ownerDocument.createElementNS(svg.namespaceURI, tag);
    for (const [key, value] of Object.entries(attrs)) child.setAttribute(key, value);
    svg.appendChild(child);
  }
  parent.appendChild(svg);
}

async function renderTimeline(app, model, target, component, sourcePath) {
  const root = element(target, 'div', 'timeline');
  if (model.title) element(root, 'p', 'timeline__title', model.title);
  const renders = [];
  function steps(parent, list, start = 1) {
    const ol = element(parent, 'ol', 'timeline__steps');
    ol.setAttribute('role', 'list');
    ol.start = start;
    for (const step of list) {
      const li = element(ol, 'li', 'timeline__step');
      let parent = li;
      let detail;
      if (step.content) {
        detail = element(li, 'details', 'timeline__detail');
        detail.open = !!step.open;
        parent = element(detail, 'summary', 'timeline__trigger');
      }
      const line = element(parent, 'span', 'timeline__line');
      if (step.status !== 'done') line.dataset.status = step.status;
      if (step.status === 'running') line.setAttribute('aria-current', 'step');
      icon(line, step.status, 'timeline__icon');
      element(line, 'span', 'timeline__text', step.text);
      if (detail) {
        icon(parent, 'chevron', 'timeline__chevron');
        const content = element(detail, 'div', 'timeline__detail-content');
        renders.push(MarkdownRenderer.render(app, step.content, content, sourcePath, component));
      }
    }
  }
  if (model.collapse) {
    const history = element(root, 'details', 'timeline__history');
    const summary = element(history, 'summary', 'timeline__trigger');
    element(summary, 'span', 'timeline__text', `${model.collapse} earlier ${model.collapse === 1 ? 'step' : 'steps'}`);
    icon(summary, 'chevron', 'timeline__chevron');
    steps(history, model.steps.slice(0, model.collapse));
  }
  if (model.steps.length > model.collapse) steps(root, model.steps.slice(model.collapse), model.collapse + 1);
  await Promise.all(renders);
  return root;
}

class TimelineEditor extends Modal {
  constructor(plugin, model, path, save) {
    super(plugin.app);
    this.plugin = plugin;
    this.draft = JSON.parse(JSON.stringify(model));
    this.path = path;
    this.save = save;
  }

  onOpen() {
    this.modalEl.classList.add('timeline-editor-modal');
    this.setTitle('编辑时间线');
    const grid = element(this.contentEl, 'div', 'timeline-editor-grid');
    this.form = element(grid, 'div', 'timeline-editor-form');
    const titleLabel = element(this.form, 'label', 'timeline-editor-field', '标题（可选）');
    const title = element(titleLabel, 'input');
    title.type = 'text';
    title.value = this.draft.title;
    title.addEventListener('input', () => { this.draft.title = title.value; this.preview(); });
    this.stepList = element(this.form, 'div', 'timeline-editor-steps');
    const add = element(this.form, 'button', '', '添加步骤');
    add.addEventListener('click', () => {
      this.draft.steps.push({ text: '', status: 'pending', content: '', open: false });
      this.fields();
      this.stepList.querySelectorAll('input[type="text"]').item(this.draft.steps.length - 1)?.focus();
      this.preview();
    });
    const collapseLabel = element(this.form, 'label', 'timeline-editor-field', '折叠前几个步骤');
    this.collapseInput = element(collapseLabel, 'input');
    this.collapseInput.type = 'number';
    this.collapseInput.min = '0';
    this.collapseInput.value = this.draft.collapse;
    this.collapseInput.addEventListener('input', () => {
      this.draft.collapse = Math.max(0, Math.min(this.draft.steps.length, Math.trunc(Number(this.collapseInput.value) || 0)));
      this.preview();
    });
    const previewPane = element(grid, 'div', 'timeline-editor-preview-pane');
    element(previewPane, 'div', 'timeline-editor-preview-label', '实时预览');
    this.previewEl = element(previewPane, 'div', 'timeline-editor-preview');
    const footer = element(this.contentEl, 'div', 'timeline-editor-actions');
    const cancel = element(footer, 'button', '', '取消');
    cancel.addEventListener('click', () => this.close());
    this.saveButton = element(footer, 'button', 'mod-cta', '保存');
    this.saveButton.addEventListener('click', async () => {
      this.saveButton.disabled = true;
      try {
        if (await this.save(this.draft) !== false) this.close();
      } catch (error) { new Notice(error.message); }
      finally { this.validate(); }
    });
    this.fields();
    this.preview();
  }

  fields() {
    this.stepList.replaceChildren();
    this.draft.steps.forEach((step, index) => {
      const field = element(this.stepList, 'fieldset', 'timeline-step-field');
      element(field, 'legend', '', `步骤 ${index + 1}`);
      const row = element(field, 'div', 'timeline-step-row');
      const state = element(row, 'select');
      state.setAttribute('aria-label', `步骤 ${index + 1} 状态`);
      for (const [value, label] of Object.entries({ done: '已完成', running: '进行中', pending: '未开始', error: '失败' })) {
        const option = element(state, 'option', '', label);
        option.value = value;
      }
      state.value = step.status;
      state.addEventListener('change', () => { step.status = state.value; this.preview(); });
      const title = element(row, 'input');
      title.type = 'text';
      title.setAttribute('aria-label', `步骤 ${index + 1} 内容`);
      title.placeholder = '步骤内容';
      title.value = step.text;
      title.addEventListener('input', () => { step.text = title.value; this.preview(); });
      const remove = element(row, 'button', 'clickable-icon');
      remove.setAttribute('aria-label', `删除步骤 ${index + 1}`);
      setIcon(remove, 'trash-2');
      remove.addEventListener('click', () => {
        this.draft.steps.splice(index, 1);
        this.draft.collapse = Math.min(this.draft.collapse, this.draft.steps.length);
        this.collapseInput.value = this.draft.collapse;
        this.fields(); this.preview();
      });
      const details = element(field, 'details', 'timeline-step-options');
      details.open = !!step.content;
      element(details, 'summary', '', '详情');
      const body = element(details, 'textarea');
      body.setAttribute('aria-label', `步骤 ${index + 1} 详情`);
      body.placeholder = '可选，支持 Markdown';
      body.rows = 3;
      body.value = step.content;
      const label = element(details, 'label', 'timeline-editor-open');
      const open = element(label, 'input');
      open.type = 'checkbox';
      open.checked = step.open;
      open.disabled = !step.content;
      label.append('默认展开详情');
      open.addEventListener('change', () => { step.open = open.checked; this.preview(); });
      body.addEventListener('input', () => {
        step.content = body.value;
        open.disabled = !step.content;
        this.preview();
      });
    });
  }

  validate() {
    if (this.saveButton) this.saveButton.disabled = !this.draft.steps.length || this.draft.steps.some(step => !step.text.trim());
  }

  preview() {
    this.previewComponent?.unload();
    this.previewComponent = new Component();
    this.previewComponent.load();
    this.previewEl.replaceChildren();
    const preview = JSON.parse(JSON.stringify(this.draft));
    preview.steps.forEach(step => { if (step.content) step.open = true; });
    renderTimeline(this.app, preview, this.previewEl, this.previewComponent, this.path).catch(error => {
      this.previewEl.textContent = error.message;
    });
    this.validate();
  }

  onClose() { this.previewComponent?.unload(); this.contentEl.replaceChildren(); }
}

class TimelineChild extends MarkdownRenderChild {
  constructor(el, plugin, source, ctx) { super(el); this.plugin = plugin; this.source = source; this.ctx = ctx; }
  async onload() {
    try {
      this.containerEl.replaceChildren();
      const model = parseTimeline(this.source);
      const frame = element(this.containerEl, 'div', 'timeline-frame');
      const edit = element(frame, 'button', 'timeline-edit-button clickable-icon');
      edit.setAttribute('aria-label', '编辑时间线');
      setIcon(edit, 'pencil');
      this.registerDomEvent(edit, 'click', () => this.plugin.edit(this.source, this.ctx.sourcePath, this.ctx.getSectionInfo(this.containerEl)?.lineStart ?? -1));
      await renderTimeline(this.plugin.app, model, frame, this, this.ctx.sourcePath);
    } catch (error) { element(this.containerEl, 'div', 'timeline-input-error', error.message); }
  }
}

module.exports = class TimelinePlugin extends Plugin {
  onload() {
    const font = this.app.vault.adapter.getResourcePath(`${this.manifest.dir}/Geist-latin.woff2`);
    const style = document.head.appendChild(document.createElement('style'));
    style.textContent = `@font-face { font-family: "Timeline Geist"; src: url(${JSON.stringify(font)}) format("woff2"); font-weight: 100 900; font-display: swap; }`;
    this.register(() => style.remove());
    this.registerMarkdownCodeBlockProcessor('timeline', (source, el, ctx) => ctx.addChild(new TimelineChild(el, this, source, ctx)));
    const insert = (editor, view) => new TimelineEditor(this, { title: '', collapse: 0, steps: [{ text: '', status: 'pending', content: '', open: false }] }, view.file?.path || '', draft => {
      editor.replaceSelection(fenceTimeline(serializeTimeline(draft)) + '\n\n');
    }).open();
    this.addCommand({ id: 'insert-timeline', name: '插入时间线', icon: 'list-checks', editorCallback: insert });
    this.addCommand({ id: 'edit-timeline', name: '编辑光标处的时间线', editorCallback: (editor, view) => {
      const offset = editor.posToOffset(editor.getCursor());
      const block = findTimelineBlocks(editor.getValue()).find(block => offset >= block.from && offset <= block.to);
      if (block) this.edit(block.source, view.file.path, block.line);
      else new Notice('将光标放在时间线中，或点击时间线上的铅笔。');
    } });
    this.registerEvent(this.app.workspace.on('editor-menu', (menu, editor, view) => menu.addItem(item => item.setTitle('插入时间线').setIcon('list-checks').onClick(() => insert(editor, view)))));
  }

  edit(source, path, line) {
    const view = this.app.workspace.getActiveViewOfType(MarkdownView);
    if (!view || view.file?.path !== path) return new Notice('请先打开这篇笔记，再编辑时间线。');
    new TimelineEditor(this, parseTimeline(source), path, draft => {
      const note = view.editor.getValue();
      const change = replacementFor(note, source, line, serializeTimeline(draft));
      if (!change) { new Notice('原文已发生变化，请重新打开时间线编辑器。'); return false; }
      if (change.to === note.length) change.text += '\n\n';
      view.editor.replaceRange(change.text, view.editor.offsetToPos(change.from), view.editor.offsetToPos(change.to));
    }).open();
  }
};
