(() => {
  const version = document.currentScript?.dataset.version;
  if (!version) return;
  let checking = false;
  const timer = setInterval(async () => {
    if (checking) return;
    checking = true;
    try {
      const response = await fetch('/api/workspace/status', { cache: 'no-store' });
      if (!response.ok) return;
      const status = await response.json();
      if (status.editable && status.version && status.version !== version && !document.querySelector('dialog[open]')) {
        clearInterval(timer);
        location.reload();
      }
    } catch {
      // Keep the current page during a restart or temporary connection failure.
    } finally { checking = false; }
  }, 1000);
})();
