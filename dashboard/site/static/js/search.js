(function () {
  'use strict';
  const dialog = document.getElementById('site-search');
  let indexPromise;
  const loadIndex = url => {
    if (!indexPromise) indexPromise = fetch(url).then(response => {
      if (!response.ok) throw new Error('index');
      return response.json();
    }).catch(error => { indexPromise = undefined; throw error; });
    return indexPromise;
  };
  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  };
  function highlight(node, text, terms) {
    const escaped = terms.map(term => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    if (!escaped.length) { node.textContent = text; return; }
    const regex = new RegExp(escaped.sort((a, b) => b.length - a.length).join('|'), 'giu');
    let cursor = 0;
    for (const match of text.matchAll(regex)) {
      node.append(document.createTextNode(text.slice(cursor, match.index)), element('mark', '', match[0]));
      cursor = match.index + match[0].length;
    }
    node.append(document.createTextNode(text.slice(cursor)));
  }
  for (const panel of document.querySelectorAll('.site-search')) {
    const input = panel.querySelector('input');
    const status = panel.querySelector('.search-status');
    const results = panel.querySelector('.search-results');
    let revision = 0, timer;
    async function update() {
      const current = ++revision, query = input.value.trim();
      results.replaceChildren();
      if (!query) { status.textContent = '输入关键词搜索文章和章节。'; return; }
      status.textContent = '正在搜索…';
      try {
        const pages = await loadIndex(panel.dataset.indexUrl);
        if (revision !== current) return;
        const found = SiteSearch.search(pages, query);
        status.textContent = found.length ? `找到 ${found.length} 篇文档${found.length > 20 ? '，显示前 20 篇' : ''}` : '没有找到结果，请尝试更短的关键词或其他写法。';
        for (const page of found.slice(0, 20)) {
          const group = element('section', 'search-result-group');
          const heading = element('h3');
          const link = element('a', 'search-result-link');
          link.href = page.uri;
          highlight(link, page.title, page.terms);
          heading.append(link); group.append(heading);
          for (const section of page.sections) {
            const item = element('a', 'search-result-link search-section-link');
            item.href = page.uri + (section.anchor ? '#' + encodeURIComponent(section.anchor) : '');
            if (section.title) {
              const title = element('strong'); highlight(title, section.title, page.terms); item.append(title);
            }
            const preview = element('span');
            highlight(preview, SiteSearch.snippet(section.text, page.terms), page.terms);
            item.append(preview); group.append(item);
          }
          results.append(group);
        }
      } catch (error) {
        if (revision !== current) return;
        status.textContent = error.message === '精确匹配短语时，请使用成对的双引号。' ? error.message : '无法加载搜索索引，请检查连接后重试。';
      }
    }
    input.addEventListener('input', () => { ++revision; clearTimeout(timer); timer = setTimeout(update, 120); });
    panel.addEventListener('keydown', event => {
      if (event.isComposing) return;
      const links = [...results.querySelectorAll('a')];
      if (!links.length) return;
      const selected = links.indexOf(document.activeElement);
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const next = event.key === 'ArrowDown' ? selected + 1 : selected < 0 ? links.length - 1 : selected - 1;
        (next < 0 ? input : links[next % links.length]).focus();
      } else if (event.key === 'Enter' && document.activeElement === input) {
        event.preventDefault(); links[0].click();
      }
    });
  }
  function openSearch() {
    if (!dialog || dialog.open) return;
    dialog.showModal();
    dialog.querySelector('input').focus();
  }
  document.querySelectorAll('[data-search-open]').forEach(link => {
    link.setAttribute('aria-keyshortcuts', 'Control+k Meta+k');
    link.title = '搜索 (⌘K / Ctrl+K)';
    link.addEventListener('click', event => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault(); openSearch();
    });
  });
  document.addEventListener('keydown', event => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); openSearch(); }
  });
  dialog.querySelector('[data-search-close]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => {
    if (event.target.closest('a[href]')) { dialog.close(); return; }
    if (event.target !== dialog) return;
    const box = dialog.getBoundingClientRect();
    if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close();
  });
})();
