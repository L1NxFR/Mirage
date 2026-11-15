// Keep Hugo's real footnotes and anchors: desktop margin notes, mobile endnotes.
(() => {
  const article = document.querySelector('.document-page.blog .article-body');
  if (!article) return;
  const container = article.closest('.blog-layout');
  const toc = container.querySelector('#TableOfContents');
  const footnotes = [...article.querySelectorAll('.footnotes > ol > li')];
  const notes = footnotes.map(note => {
    const reference = [...article.querySelectorAll('a.footnote-ref')].find(link =>
      decodeURIComponent(link.hash.slice(1)) === note.id);
    return { note, reference };
  }).filter(({ reference }) => reference);
  if (!notes.length || notes.length !== footnotes.length) return;

  const wide = window.matchMedia('screen and (min-width: 1280px)');
  let frame, firstLayout = true;
  function layout() {
    const width = container.getBoundingClientRect().right - article.getBoundingClientRect().right - 32;
    const enabled = wide.matches && width >= 180;
    container.classList.toggle('has-margin-notes', enabled);
    article.classList.toggle('sidenotes-ready', enabled);
    article.style.minHeight = '';
    if (!enabled) {
      article.style.removeProperty('--sidenote-width');
      notes.forEach(({ note }) => { note.style.top = ''; });
      firstLayout = false;
      return;
    }
    article.style.setProperty('--sidenote-width', `${width}px`);
    const origin = article.getBoundingClientRect().top;
    // The TOC shares this rail. It stays in document flow on sidenote pages,
    // so neither it nor a long previous note can overlap a later note.
    let bottom = toc ? Math.max(0, toc.getBoundingClientRect().bottom - origin + 24) : 0;
    notes.forEach(({ note, reference }) => {
      const top = Math.max(reference.getBoundingClientRect().top - origin, bottom);
      note.style.top = `${top}px`;
      bottom = top + note.getBoundingClientRect().height + 16;
    });
    article.style.minHeight = `${Math.ceil(bottom)}px`;
    if (firstLayout && location.hash) {
      let target;
      try { target = document.getElementById(decodeURIComponent(location.hash.slice(1))); } catch { /* malformed fragment */ }
      if (notes.some(({ note, reference }) => target === note || target === reference)) {
        requestAnimationFrame(() => target.scrollIntoView({ block: 'start' }));
      }
    }
    firstLayout = false;
  }
  function schedule() {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(layout);
  }
  notes.forEach(({ note, reference }) => {
    note.dataset.noteNumber = reference.textContent.trim();
  });
  window.addEventListener('resize', schedule);
  wide.addEventListener('change', schedule);
  article.addEventListener('load', schedule, true);
  if (document.fonts) document.fonts.ready.then(schedule);
  // Images, expandable content and font reflow can move a reference after load.
  const observer = new ResizeObserver(schedule);
  [...article.children, ...notes.map(({ note }) => note)].forEach(el => observer.observe(el));
  if (toc) observer.observe(toc);
  schedule();
})();
