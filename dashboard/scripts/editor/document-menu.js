import { connect, request } from './api.js';

export function setupDocumentMenu(sidebar) {
  const menu = document.createElement('div');
  menu.className = 'document-menu';
  menu.setAttribute('role', 'menu');
  menu.hidden = true;
  document.body.append(menu);
  const status = sidebar.querySelector('[data-sidebar-status]');
  const dialog = document.createElement('dialog');
  dialog.className = 'document-action-dialog';
  dialog.innerHTML = '<form><h2></h2><p data-description></p><label><span></span><input name="title" required maxlength="180"><select name="parent"></select></label><p role="status"></p><footer><button type="button" data-cancel>取消</button><button type="submit">确定</button></footer></form>';
  document.body.append(dialog);
  const form = dialog.querySelector('form');
  let row, trigger, pending, snapshot, busy = false;
  let editable = false;
  connect().then(session => { editable = Boolean(session); });
  function close(restore = false) {
    menu.hidden = true;
    trigger?.setAttribute('aria-expanded', 'false');
    if (restore) trigger?.focus();
  }
  const actions = [
    ['rename', '重命名', 'rename'], ['edit', '编辑文档', 'edit'],
    ['link', '复制链接', 'link'], ['open', '在新标签页打开', 'open'],
    ['remove', '移出目录', 'remove'], ['copy', '复制…', 'copy'],
    ['move', '移动…', 'move'], ['export', '导出…', 'export'],
    ['pin', '置顶文档', 'pin'], ['delete', '删除', 'delete']
  ];
  const paths = {
    rename:'M4 7h6M4 7v10h6M15 4v16M12 4h6M12 20h6',
    edit:'m4 16 12-12 4 4-12 12-5 1zM13 7l4 4',
    link:'m10 14 4-4M8 16l-2 2a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0M16 8l2-2a4 4 0 0 1 6 6l-5 5a4 4 0 0 1-6 0',
    open:'M13 4h7v7M20 4 10 14M10 4H4v16h16v-6',
    remove:'M9 4H4v16h16v-5M9 10h12m-4-4 4 4-4 4',
    copy:'M9 9H3v12h12v-6M9 3h12v12H9z',
    move:'M3 5h7l2 3h9v13H3zM7 14h10m-4-4 4 4-4 4',
    export:'M9 3H4v18h16v-6M12 8h9m-4-4 4 4-4 4',
    pin:'m9 3 12 12-5 1-3 4-9-9 4-3zM9 15l-6 6',
    delete:'M3 6h18M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7M14 10v7'
  };
  function show(button) {
    close(); trigger = button; row = button.closest('[data-document-path]');
    menu.replaceChildren();
    for (const [action, label, icon] of actions) {
      const item = document.createElement('button');
      item.type = 'button'; item.setAttribute('role', 'menuitem');
      item.dataset.action = action;
      item.innerHTML = `<svg viewBox="0 0 26 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[icon]}"/></svg><span></span>`;
      item.querySelector('span').textContent = action === 'pin' && row.dataset.pinned === 'true' ? '取消置顶' : label;
      item.disabled = !editable && !['link', 'open'].includes(action);
      if (item.disabled) item.title = '请用 npm run dev 启动本地工作区';
      if (action === 'remove' && row.dataset.documentPath.split('/').length === 2) item.disabled = true;
      item.addEventListener('click', () => run(action));
      menu.append(item);
    }
    menu.hidden = false; trigger.setAttribute('aria-expanded', 'true');
    const rect = button.getBoundingClientRect();
    menu.style.left = `${Math.max(8, Math.min(rect.right - menu.offsetWidth, innerWidth - menu.offsetWidth - 8))}px`;
    menu.style.top = `${Math.max(8, Math.min(rect.bottom + 6, innerHeight - menu.offsetHeight - 8))}px`;
    menu.querySelector('button:not(:disabled)')?.focus();
  }
  sidebar.addEventListener('click', event => {
    const button = event.target.closest('.document-more');
    if (!button) return;
    event.stopPropagation();
    if (button === trigger && !menu.hidden) close(true); else show(button);
  });
  document.addEventListener('click', event => { if (!menu.contains(event.target)) close(); });
  window.addEventListener('resize', () => close());
  document.addEventListener('scroll', () => close(), true);
  menu.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); close(true); }
    if (event.key === 'Tab') close();
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      const items = [...menu.querySelectorAll('button:not(:disabled)')];
      const index = items.indexOf(document.activeElement);
      items[event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length].focus();
    }
  });
  async function run(action) {
    const link = row.querySelector('a').href;
    close(); status.textContent = '';
    try {
      if (action === 'open') { window.open(link, '_blank', 'noopener'); return; }
      if (action === 'edit') { const url = new URL(link); url.searchParams.set('edit', '1'); location.assign(url); return; }
      if (action === 'link') { await navigator.clipboard.writeText(link); status.textContent = '链接已复制'; return; }
      snapshot = await request(`document?path=${encodeURIComponent(row.dataset.documentPath)}`);
      if (action === 'export') {
        const blob = URL.createObjectURL(new Blob([snapshot.source], { type: 'text/markdown;charset=utf-8' }));
        const a = document.createElement('a'); a.href = blob; a.download = snapshot.path.split('/').pop(); a.click();
        setTimeout(() => URL.revokeObjectURL(blob), 1000); return;
      }
      pending = action;
      if (action === 'pin') { await apply(); return; }
      form.reset();
      dialog.querySelector('h2').textContent = actions.find(item => item[0] === action)[1];
      dialog.querySelector('[data-description]').textContent = action === 'delete' ? `删除「${row.dataset.documentTitle}」？文档会移入本地 .workspace-trash 备份目录。` : action === 'remove' ? '将文档移动到当前栏目的顶层。' : row.dataset.documentTitle;
      const title = form.elements.title, parent = form.elements.parent;
      title.hidden = action !== 'rename'; title.required = action === 'rename'; title.value = row.dataset.documentTitle;
      parent.hidden = !['move', 'copy'].includes(action); parent.replaceChildren();
      dialog.querySelector('label span').textContent = action === 'rename' ? '文档名称' : !parent.hidden ? '目标目录' : '';
      dialog.querySelector('[role=status]').textContent = '';
      form.querySelector('[type=submit]').disabled = false;
      if (!parent.hidden) {
        const groups = await request(`groups?section=${encodeURIComponent(sidebar.dataset.section)}`);
        for (const group of groups) { const option = new Option('— '.repeat(group.depth) + group.title, group.path); parent.add(option); }
        parent.value = snapshot.path.split('/').slice(0, -1).join('/');
      }
      dialog.showModal();
      (title.hidden ? parent.hidden ? form.querySelector('[type=submit]') : parent : title).focus();
      if (!title.hidden) title.select();
    } catch (error) { status.textContent = error.message; }
  }
  async function apply() {
    const result = await request('action', { path: snapshot.path, revision: snapshot.revision, action: pending, title: form.elements.title.value, parent: form.elements.parent.value });
    location.assign(result.url);
  }
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (busy || !form.reportValidity()) return;
    busy = true; form.querySelector('[type=submit]').disabled = true;
    dialog.querySelector('[role=status]').textContent = '正在保存…';
    try { await apply(); } catch (error) { dialog.querySelector('[role=status]').textContent = error.message; }
    finally { busy = false; form.querySelector('[type=submit]').disabled = false; }
  });
  dialog.querySelector('[data-cancel]').addEventListener('click', () => { if (!busy) { dialog.close(); trigger?.focus(); } });
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
}
