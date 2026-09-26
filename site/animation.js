// Respect motion preferences and let every visitor pause the decorative loop.
const video = document.querySelector('#agent-loop');
const toggle = document.querySelector('#motion-toggle');
const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
if (video && toggle) {
  function reflectPlayback() {
    toggle.textContent = video.paused ? 'Play ▷' : 'Pause Ⅱ';
    toggle.setAttribute('aria-label', video.paused ? 'Play animation' : 'Pause animation');
  }
  function followPreference() {
    if (preference.matches) {
      video.autoplay = false;
      video.pause();
    } else {
      video.play().catch(reflectPlayback);
    }
    reflectPlayback();
  }
  toggle.addEventListener('click', () => {
    if (video.paused) video.play().catch(reflectPlayback);
    else video.pause();
  });
  video.addEventListener('play', reflectPlayback);
  video.addEventListener('pause', reflectPlayback);
  video.addEventListener('error', () => { toggle.hidden = true; });
  preference.addEventListener('change', followPreference);
  followPreference();
}
