// The navigation works as anchors without JavaScript, then becomes accessible tabs.
const tablist = document.querySelector('.section-tabs');
const tabs = [...tablist.querySelectorAll('a')];
const panels = [...document.querySelectorAll('.tech-panel')];
tablist.setAttribute('role', 'tablist');
tablist.setAttribute('aria-orientation', 'vertical');
tabs.forEach(tab => {
  tab.setAttribute('role', 'tab');
  tab.setAttribute('aria-controls', tab.hash.slice(1));
});
panels.forEach(panel => {
  panel.setAttribute('role', 'tabpanel');
  panel.tabIndex = 0;
});
function activateSection(hash, focus = false) {
  const active = tabs.find(tab => tab.hash === hash) || tabs[0];
  tabs.forEach(tab => {
    const selected = tab === active;
    tab.setAttribute('aria-selected', String(selected));
    tab.tabIndex = selected ? 0 : -1;
  });
  panels.forEach(panel => { panel.hidden = panel.id !== active.hash.slice(1); });
  if (focus) active.focus();
}
function navigateSection(tab) {
  if (location.hash !== tab.hash) history.pushState(null, '', tab.hash);
  activateSection(tab.hash, true);
  const top = document.querySelector('.technical').offsetTop - 24;
  if (window.scrollY > top) window.scrollTo({ top, behavior: 'instant' });
}
tabs.forEach((tab, index) => {
  tab.addEventListener('click', event => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    navigateSection(tab);
  });
  tab.addEventListener('keydown', event => {
    if (event.key === ' ') {
      event.preventDefault();
      navigateSection(tab);
      return;
    }
    let next;
    if (event.key === 'ArrowDown' || event.key === 'ArrowRight') next = (index + 1) % tabs.length;
    if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = tabs.length - 1;
    if (next !== undefined) {
      event.preventDefault();
      navigateSection(tabs[next]);
    }
  });
});
window.addEventListener('hashchange', () => activateSection(location.hash));
window.addEventListener('popstate', () => activateSection(location.hash));
activateSection(location.hash);

const host = document.querySelector('#workflow-chart');
const message = document.querySelector('#chart-status');
try {
  const [{ default: mermaid }, response] = await Promise.all([
    import('https://cdn.jsdelivr.net/npm/mermaid@12.0.0/dist/mermaid.esm.min.mjs'),
    fetch('/assets/workflow.mmd?v=live-agent-2'),
  ]);
  if (!response.ok) throw new Error('Diagram source unavailable');
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: 'strict',
    theme: 'base',
    themeVariables: {
      fontFamily: 'DM Sans, sans-serif',
      fontSize: '14px',
      primaryColor: '#e6ecdf',
      primaryTextColor: '#172b29',
      primaryBorderColor: '#8caa7c',
      lineColor: '#657c62',
      clusterBkg: '#f0f2e9',
      clusterBorder: '#cbd6c3',
      edgeLabelBackground: '#f5f4ee',
    },
    flowchart: { htmlLabels: false, curve: 'basis', nodeSpacing: 28, rankSpacing: 35 },
  });
  const { svg } = await mermaid.render('rfp-workflow', await response.text());
  host.innerHTML = svg;
  message.hidden = true;
} catch {
  message.textContent = 'The interactive diagram could not load. The workflow is described below, and its Mermaid source is available to view.';
}
