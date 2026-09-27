const starters = [
  'Find RFPs that match my business and help me apply.',
  'Review my company website and extract information about my company.',
  'Review my company profile and tell me what is missing.',
  'Help me import a previous RFP response.',
];

export function suggestedPrompts(snapshot) {
  const run = snapshot?.run;
  if (run?.status === 'running') return [];
  const next = [];
  if (snapshot?.pdfs?.some(pdf => pdf.rfp_id === run?.rfp_id && !pdf.stale)) {
    next.push('Review the response for missing details before I approve it.');
  } else if (run?.rfp_id) {
    next.push('What information do you still need from me for this RFP?',
      'Use my previous response to identify gaps in this RFP.');
  }
  if (run?.status === 'error' || run?.status === 'interrupted') {
    next.unshift('Continue from the work you have already saved.');
  }
  return [...next, ...starters];
}

export function completionFor(value, candidates) {
  // Only extend what was typed. Never replace an unrelated draft or invent facts.
  if (/\n/.test(value)) return '';
  const match = candidates.find(text => text.length > value.length && text.toLowerCase().startsWith(value.toLowerCase()));
  return match ? match.slice(value.length) : '';
}

export function canAcceptCompletion(event, input, suffix, composing = false) {
  return !!suffix && event.key === 'ArrowRight' && !event.altKey && !event.ctrlKey &&
    !event.metaKey && !event.shiftKey && !event.isComposing && !composing &&
    input.selectionStart === input.value.length && input.selectionEnd === input.value.length;
}

export function createChatSuggestions({input, getCandidates}) {
  const shell = document.createElement('div'); shell.className = 'chat-completion';
  input.before(shell); shell.append(input);
  const ghost = document.createElement('div'); ghost.className = 'chat-completion-ghost'; ghost.setAttribute('aria-hidden', 'true');
  const prefix = document.createElement('span'), rest = document.createElement('span');
  prefix.className = 'chat-completion-prefix'; ghost.append(prefix, rest); shell.append(ghost);
  const hint = document.createElement('button'); hint.type = 'button'; hint.className = 'chat-completion-hint';
  hint.textContent = '→ Accept suggestion'; hint.setAttribute('aria-label', 'Add suggested message to input');
  shell.append(hint);
  const description = document.createElement('span'); description.id = 'chat-completion-description'; description.className = 'sr-only';
  shell.append(description); input.setAttribute('aria-describedby', description.id);
  input.setAttribute('aria-autocomplete', 'inline');
  let originalPlaceholder = input.placeholder;
  let suffix = '', dismissed = null, composing = false;
  function update() {
    const atEnd = input.selectionStart === input.value.length && input.selectionEnd === input.value.length;
    const candidate = !input.disabled && !composing && atEnd ? completionFor(input.value, getCandidates()) : '';
    suffix = dismissed === input.value + candidate ? '' : candidate;
    prefix.textContent = input.value; rest.textContent = suffix;
    ghost.hidden = hint.hidden = !suffix;
    input.placeholder = suffix ? '' : originalPlaceholder;
    description.textContent = suffix ? `Suggestion: ${input.value}${suffix} Press Right Arrow at the end to add it, or Escape to dismiss.` : '';
    input.style.height = '36px';
    input.style.height = Math.min(140, Math.max(36, input.scrollHeight, suffix ? ghost.scrollHeight : 0)) + 'px';
    ghost.scrollTop = input.scrollTop;
  }
  function accept() {
    if (!suffix) return;
    input.focus(); input.setRangeText(suffix, input.value.length, input.value.length, 'end');
    suffix = ''; input.dispatchEvent(new Event('input', {bubbles: true}));
  }
  hint.onclick = accept;
  input.addEventListener('keydown', event => {
    if (canAcceptCompletion(event, input, suffix, composing)) { event.preventDefault(); accept(); }
    else if (event.key === 'Escape' && suffix) { dismissed = input.value + suffix; update(); }
  });
  input.addEventListener('input', () => { dismissed = null; update(); });
  for (const event of ['click', 'keyup', 'focus', 'select']) input.addEventListener(event, update);
  input.addEventListener('compositionstart', () => { composing = true; update(); });
  input.addEventListener('compositionend', () => { composing = false; update(); });
  input.addEventListener('billy-context-change', () => { originalPlaceholder = input.placeholder; update(); });
  input.addEventListener('scroll', () => { ghost.scrollTop = input.scrollTop; });
  document.addEventListener('selectionchange', () => { if (document.activeElement === input) update(); });
  update();
  return {update};
}
