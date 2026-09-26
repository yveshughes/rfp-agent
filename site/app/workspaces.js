// URLs bind each tab (and every request/download) to one company workspace.
export async function connectWorkspace(origin, toast) {
  const $ = s => document.querySelector(s);
  const trigger = $('#workspace-switcher'), menu = $('#workspace-menu');
  let selected = new URL(location.href).searchParams.get('workspace');
  if (!selected) { try { selected = localStorage.getItem('billy-workspace'); } catch {} }
  selected ||= 'default';
  const request = async (data) => {
    const response = await fetch(origin + '/api/workspaces', data === undefined ? {} : {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-Billy-Client': 'workspace'}, body: JSON.stringify(data)
    });
    if (!response.ok) throw Error('Reconnect Billy’s workspace to manage companies.');
    return response.json();
  };
  const close = () => { menu.hidden = true; trigger.setAttribute('aria-expanded', 'false'); };
  const open = () => { menu.hidden = false; trigger.setAttribute('aria-expanded', 'true'); };
  const switchTo = id => {
    // Full navigation discards pending UI callbacks; old requests retain their old URL.
    try { localStorage.setItem('billy-workspace', id); } catch {}
    const url = new URL(location.href); url.searchParams.set('workspace', id); url.hash = '/chats';
    location.assign(url.href);
  };
  let rows;
  try { rows = (await request()).workspaces; }
  catch (error) {
    trigger.onclick = () => toast(error.message);
    $('#workspace-name').textContent = 'Workspace offline';
    $('#workspace-switcher-label').textContent = 'Reconnect to switch';
    // Never silently fall back to another company's data when offline.
    return {id: selected, api: selected === 'default' ? origin : origin + '/w/' + encodeURIComponent(selected)};
  }
  const current = rows.find(row => row.id === selected);
  if (!current) {
    $('#workspace-name').textContent = 'Workspace unavailable';
    // Show valid choices, but keep requests on the invalid ID until the user chooses.
  } else {
    $('#workspace-name').textContent = current.name;
    $('#workspace-initials').textContent = current.name.split(/\s+/).slice(0, 2).map(word => word[0]).join('').toUpperCase();
    trigger.title = 'Switch workspace · ' + current.name;
  }
  const url = new URL(location.href); url.searchParams.set('workspace', selected);
  history.replaceState(null, '', url.href);
  rows.forEach(row => {
    const button = document.createElement('button'); button.type = 'button';
    button.className = 'workspace-choice'; button.setAttribute('aria-current', String(row.id === selected));
    const name = document.createElement('span'); name.textContent = row.name;
    const check = document.createElement('span'); check.textContent = row.id === selected ? '✓' : '';
    button.append(name, check); button.onclick = () => row.id === selected ? close() : switchTo(row.id);
    $('#workspace-choices').append(button);
  });
  trigger.onclick = () => menu.hidden ? open() : close();
  document.addEventListener('click', event => { if (!event.target.closest('.workspace-picker')) close(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && !menu.hidden) { close(); trigger.focus(); } });
  $('#add-workspace').onclick = () => { close(); $('#new-workspace-dialog').showModal(); $('#new-workspace-name').focus(); };
  $('#cancel-workspace').onclick = () => $('#new-workspace-dialog').close();
  $('#new-workspace-form').onsubmit = async event => {
    event.preventDefault(); const name = $('#new-workspace-name').value.trim(); if (!name) return;
    const button = $('#create-workspace'); button.disabled = true;
    try { const row = await request({name}); switchTo(row.id); }
    catch (error) { toast(error.message); button.disabled = false; }
  };
  return {id: selected, api: origin + '/w/' + encodeURIComponent(selected)};
}
