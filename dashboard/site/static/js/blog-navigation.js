(() => {
  const navigation = document.querySelector('.blog-sidebar > details');
  if (!navigation) return;
  const rail = navigation.parentElement;
  const layout = rail.closest('.blog-layout');
  const header = document.querySelector('.site-header');
  const wide = matchMedia('(min-width: 1024px)');
  let frame;
  // Keep the full-height rail in the viewport even beyond the article's end.
  // Measure the shared header rather than duplicating its responsive geometry.
  function position() {
    if (!wide.matches) return;
    rail.style.setProperty('--blog-rail-left', `${layout.getBoundingClientRect().left}px`);
    rail.style.setProperty('--blog-rail-top', `${Math.max(64, header.getBoundingClientRect().bottom + 16)}px`);
  }
  function schedule() {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(position);
  }
  const adapt = () => { navigation.open = wide.matches; position(); };
  adapt();
  wide.addEventListener('change', adapt);
  window.addEventListener('scroll', schedule, { passive: true });
  window.addEventListener('resize', schedule);
  new ResizeObserver(schedule).observe(header);
})();
