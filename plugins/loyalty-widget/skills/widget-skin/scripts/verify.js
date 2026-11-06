async () => {
  const sdk = window.GamifySDK;
  if (!sdk) return { ok: false, error: 'GamifySDK is not on the page' };
  const errors = [];
  const record = (e) => errors.push(String((e.error && e.error.message) || e.message || e.reason || e));
  window.addEventListener('error', record);
  window.addEventListener('unhandledrejection', record);
  await sdk.ready();
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const scrolls = (el) => {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const o = getComputedStyle(p).overflowX;
      if (o === 'auto' || o === 'scroll' || o === 'hidden' || o === 'clip') return true;
    }
    return false;
  };
  const label = (el) => el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).join('.') : '');
  const pages = [];
  for (const name of sdk.pages) {
    sdk.navigate(name);
    await wait(300);
    const root = document.querySelector('[data-gamify-outlet] [data-gamify-page-root]');
    const overflow = document.documentElement.scrollWidth - innerWidth;
    const offenders = overflow > 1
      ? [...document.body.querySelectorAll('*')]
          .filter((el) => el.getBoundingClientRect().right > innerWidth + 1 && getComputedStyle(el).position !== 'fixed' && !scrolls(el))
          .slice(0, 5)
          .map(label)
      : [];
    const nav = document.querySelector('[data-gamify-nav="' + name + '"]');
    pages.push({
      page: name,
      rendered: !!root && root.innerText.trim().length > 0,
      overflowPx: Math.max(0, overflow),
      offenders,
      brokenImages: [...document.images].filter((i) => i.complete && i.naturalWidth === 0 && i.isConnected).length,
      buttons: root ? root.querySelectorAll('button').length : 0,
      navActive: nav ? nav.classList.contains('is-active') : null,
    });
  }
  sdk.navigate(sdk.pages[0]);
  const problems = pages.filter((p) => !p.rendered || p.overflowPx > 1 || p.brokenImages || p.navActive === false);
  return { ok: !problems.length && !errors.length, mode: sdk.mode, viewport: innerWidth + 'x' + innerHeight, breakpoint: sdk.breakpoint, errors, problems, pages };
}
