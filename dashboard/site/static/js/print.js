// Expand only document content; retain the reader's state after print or cancel.
(() => {
  let snapshot;
  function expand() {
    if (snapshot) return;
    const details = [...document.querySelectorAll('.article-body details, .blog-tldr-content details')];
    snapshot = { details: details.map(element => [element, element.open]), scroll: [] };
    details.forEach(element => { element.open = true; });
    document.querySelectorAll('.article-body *, .blog-tldr-content *').forEach(element => {
      const style = getComputedStyle(element);
      if ([style.overflowX, style.overflowY].some(value => value === 'auto' || value === 'scroll') &&
          !element.classList.contains('print-expand')) {
        element.classList.add('print-expand');
        snapshot.scroll.push(element);
      }
    });
  }
  function restore() {
    if (!snapshot) return;
    snapshot.details.forEach(([element, open]) => { element.open = open; });
    snapshot.scroll.forEach(element => element.classList.remove('print-expand'));
    snapshot = undefined;
  }
  window.addEventListener('beforeprint', expand);
  window.addEventListener('afterprint', restore);
  window.matchMedia('print').addEventListener('change', event => event.matches ? expand() : restore());
})();
