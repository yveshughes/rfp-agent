const host = document.querySelector('#workflow-chart');
const message = document.querySelector('#chart-status');
try {
  const [{ default: mermaid }, response] = await Promise.all([
    import('https://cdn.jsdelivr.net/npm/mermaid@12.0.0/dist/mermaid.esm.min.mjs'),
    fetch('/assets/workflow.mmd'),
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
