// Highlight the section being read without changing the URL while scrolling.
(() => {
  const toc = document.getElementById('TableOfContents');
  const article = document.querySelector('.article-body');
  if (!toc || !article) return;
  const entries = [...toc.querySelectorAll('a[href^="#"]')].map(link => ({
    link, heading: document.getElementById(decodeURIComponent(link.hash.slice(1)))
  })).filter(({ heading }) => heading && article.contains(heading));
  if (!entries.length) return;

  let active, frame, destination;
  function activate(entry) {
    if (active === entry) return;
    active?.link.removeAttribute('aria-current');
    entry.link.setAttribute('aria-current', 'location');
    active = entry;
    // Only scroll the contents rail, never the document itself.
    if (getComputedStyle(toc).position === 'sticky') {
      const rail = toc.getBoundingClientRect();
      const link = entry.link.getBoundingClientRect();
      if (link.top < rail.top) toc.scrollTop += link.top - rail.top;
      else if (link.bottom > rail.bottom) toc.scrollTop += link.bottom - rail.bottom;
    }
  }
  function update() {
    // A near-bottom anchor may not reach the viewport top. Keep the clicked
    // section selected until the reader actually scrolls away from it.
    if (destination && Math.abs(window.scrollY - destination.scrollY) < 1) {
      activate(destination.entry);
      return;
    }
    destination = null;
    let current = entries[0];
    const threshold = Math.min(96, window.innerHeight * .2);
    for (const entry of entries) {
      if (entry.heading.getBoundingClientRect().top > threshold) break;
      current = entry;
    }
    if (window.scrollY > 0 && window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 2) {
      current = entries.at(-1);
    }
    activate(current);
  }
  function schedule() {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(update);
  }
  function followHash() {
    const entry = entries.find(({ heading }) => heading.id === decodeURIComponent(location.hash.slice(1)));
    if (!entry) return schedule();
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      destination = { entry, scrollY: window.scrollY };
      activate(entry);
    });
  }
  window.addEventListener('scroll', schedule, { passive: true });
  window.addEventListener('resize', schedule);
  window.addEventListener('hashchange', followHash);
  toc.addEventListener('click', event => {
    if (event.target.closest('a[href^="#"]') && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) {
      // Also handle a second click on the same hash (no hashchange event).
      requestAnimationFrame(followHash);
    }
  });
  new ResizeObserver(schedule).observe(article);
  article.addEventListener('load', schedule, true);
  followHash();
})();
