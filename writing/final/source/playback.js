/* Activate only the visible Marp slide's video. Playback rate always remains 1. */
(() => {
  const videos = [...document.querySelectorAll('video.demo-video')];
  let active = null;
  function visibleVideo() {
    const current = document.querySelector('.bespoke-marp-active');
    if (current) return current.querySelector('video.demo-video');
    // Fallback for non-Bespoke HTML: select the video nearest the viewport center.
    return videos.find(v => {
      const r = v.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && r.top < innerHeight / 2 && r.bottom > innerHeight / 2;
    }) || null;
  }
  function sync() {
    const next = visibleVideo();
    if (next === active) return;
    videos.forEach(v => { v.pause(); v.playbackRate = 1; });
    active = next;
    if (active) {
      active.currentTime = 0;
      active.muted = true;
      active.play().catch(() => { /* Native controls remain available. */ });
    }
  }
  new MutationObserver(sync).observe(document.body, {subtree: true, attributes: true, attributeFilter: ['class']});
  addEventListener('hashchange', sync);
  addEventListener('resize', sync);
  addEventListener('load', sync);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) videos.forEach(v => v.pause());
    else if (active && !active.ended) active.play().catch(() => {});
  });
  sync();
})();
