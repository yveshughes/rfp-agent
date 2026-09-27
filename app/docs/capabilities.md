# Capabilities and boundaries

Implementation baseline: `4140a21`. “Implemented” describes available code, not universal portal coverage or independently verified model output.

| Area | Implemented behavior | Boundary |
|---|---|---|
| Company workspaces | Switch companies; separate facts, files, RFPs, chat, browser and agent state | One owner/process; no user accounts or tenant authorization |
| Sources | Search directory, select multiple states, watch/unwatch with server-enforced allowance | Directory records are not verified portal integrations; default watch limit 10 |
| Monitoring | Check watched sources when due; scheduler checks every 15 seconds, scans approximately hourly when browser permits | No external alerts; failures/partial coverage visible; not every portal supported |
| Opportunity catalog | Shared import batches, company-specific lexical ranking, reversible administrative visibility | Imported records unverified; import does not fetch originals; admin API only |
| My RFPs | Pursued/manual records, sortable/searchable status table, original documents and draft workspace | Status is preparation/workflow state, not proof of submission or award |
| Company knowledge | Direct edits; evidence links to saved pages; model extraction with exact document/page or website quotations; user-reported statements | Historical claims remain historical; citations do not establish truth/current eligibility |
| Chat attachments | Stage up to five files, drop/paste images, upload and retain originals, attach to company profile/chat | PDF, PNG/JPEG/WebP, DOCX, UTF-8 TXT/CSV/MD; 25 MB each; OCR may be imperfect |
| Document reading | PDF extraction, selected page ranges, first-page thumbnail, reviewed-page progress in Activity | Up to 100 extracted PDF pages; not visual model reasoning; scanned PDFs have no built-in OCR pass |
| Main chat | Persistent Vultr model/tool loop; cited facts/analysis, concise completion summaries and linked RFP cards | Model output still needs review; no arbitrary shell or external write tool |
| Website learning | Saved/user-supplied company site, same-site links, saved URL/quotation provenance | Up to four pages per turn; claims are attributed, not verified |
| Discussing | Checklist of open company/RFP topics; a topic opens Billy's question and the answer is sent to main chat with that context | Derived from current saved facts/analysis, not a generic task manager |
| Autopilot | Global sequential preparation of suitable RFPs; pause/resume; single-RFP mode in detail view | User starts it; stops when exhausted/blocked or on execution/budget errors; no automatic restart after exhaustion |
| Drafts | Ready for review opens one continuous editable response canvas; three versioned sections and manual review checklists | No auto-checking of review items; unsupported details stay explicit placeholders |
| Review PDF | Immutable PDF with page count/section versions; stale detection after edits | Review copy, not a validated submission package; exact fonts/forms/attachments require checking |
| Review and submit | Shows PDF, gaps and deadline; review checkbox then link to agency source/instructions | No automated submission, signature, email, purchase or Responded transition |
| Browser | Per-company Chromium on VM, screenshots, take-control/hand-back, explicit approvals | Browser context not durable; side-effect detection is not universal |
| Voice | Call Billy: full-duplex conversation through Gemini Live with interruption; every workspace question is routed through `ask_billy` to the main agent, so replies come from GLM and are persisted in chat; optional Meta push-to-talk transcription remains; Settings picks the voice per workspace; a live waveform card sits in front of the call while chat updates behind it | Audio and Billy's replies go to Google; no session persistence across page loads; small talk is not saved; spoken answers depend on the agent finishing within the wait window, otherwise Billy says he is still working |

## Continuous Autopilot contract

1. The user starts global Autopilot (`autopilot: true, continuous: true`). Saved company evidence is authorized for preparation.
2. Billy evaluates company fit and deadlines. The feed score is lexical; final candidate choice is model-driven. Prefer feasible preparation time and nearer deadlines among comparable fits. Unknown dates stay flagged; expired/closed bids are rejected.
3. `pursue` marks the selected candidate as pursued. It is visible in My RFPs as Researching before deep document review. Only one RFP is selected at a time.
4. Billy reads extracted source pages, saves cited requirements/gaps, drafts three sections and exports a PDF. Missing prices, coverage, staffing or commitments remain `[NEEDS CONFIRMATION: ...]`.
5. The current review PDF completes that item. The queue records it, clears the selection and immediately searches for the next suitable RFP. Human review of earlier PDFs is independent.
6. A selected RFP blocked by inaccessible requirements is retained with its reason and skipped for this queue. Ready-for-review and already-handled items are excluded. A blocker affecting all work, no suitable candidates, a budget failure or unrecoverable execution error stops the queue.
7. Pause cancels the one queue task. Continue preserves selection and handled items. A service restart preserves progress but requires explicit Continue. Global Continue can upgrade an interrupted single-response job to continuous mode.

The 80-action bound applies to **each item**, not the whole queue. The shared inference budget still caps estimated total usage. Each new Start creates a new queue session; blocked items can be reconsidered in a later session. A separate source watcher continues discovering opportunities; it does not wake a completed queue. The finished summary can be dismissed and reopened with View last summary. Dismissal is stored in this browser per company and completion version; a new completion shows its summary again. Dismissal does not clear saved work or start/stop Billy.

## Lifecycle meaning

`Researching → Drafting → Ready for review` is automatic when a first nonempty section is saved and then a current PDF is exported. Editing and saving a Ready-for-review section returns it to Drafting. The canvas saves section text and titles; it does not regenerate the review PDF. Prepare the response again to generate an updated PDF before submission. Responded, Closed — won, Closed — lost and Not pursuing are owner-managed and are not automatically reopened. Review percentages measure manual checks, not drafting completeness or compliance.

## What is not implemented

Public authentication/authorization, NetBird access, automatic delivery, procurement-account integration, off-VM object storage, scheduled off-VM backups, durable distributed workers, vector/embedding search, guaranteed exhaustive portal coverage, external notifications and live conversational voice are future work. No subscription billing is connected. The source watch limit is only a local entitlement mechanism.
