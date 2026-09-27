# Billy workspace

A single-owner app with a six-section UI and a shared Chromium research browser. The API persists source checks, page text, PDF imports and activity in SQLite. Source lookup and guided company-profile updates are deterministic. Contextual discussion includes an optional Meta transcription/chat connection; semantic matching and proposal generation are separate integrations.

## Run on this Mac

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r app/requirements.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m uvicorn app.server:app --host 127.0.0.1 --port 8081
```

Open http://localhost:8081/app/. If the static site is already running on localhost:8080, its app UI uses localhost:8081 for the API. Provide the original source JSON through `BILLY_SOURCES` or at the ignored project-root path `rfpsonar-found-rfp-sources.json`. It is not bundled in this public repo. Runtime state defaults to the ignored `.billy/` directory; override with `BILLY_DATA_DIR`.

## Vultr service and local access

`deploy/install-app.sh` installs a non-root `billy` systemd service, binding only to `127.0.0.1:8787`. Put the private source JSON at `/var/lib/billy/rfp-sources.json`, readable only by `billy`. Browser binaries are root-owned under `/opt/billy-browsers`. Following [Ubuntu’s per-application namespace guidance](https://ubuntu.com/blog/ubuntu-23-10-restricted-unprivileged-user-namespaces), a specific AppArmor profile permits the pinned Chromium binary to create its sandbox namespaces; the global namespace restriction is left enabled. Bump the profile path when upgrading the pinned browser.

Connect from the Mac with the server's existing authorized SSH login:

```sh
ssh -N -L 127.0.0.1:8081:127.0.0.1:8787 root@YOUR_SERVER_IP
```

Then open http://localhost:8081/app/, or use the local static UI at http://localhost:8080/app/. The browser, imported PDFs and database are on Vultr when using this tunnel. No new publicly reachable API port is needed. Do not proxy this API to public nginx until authenticated HTTPS/NetBird access and workspace authorization have been implemented. The bottom-left workspace switcher supports multiple demo companies for this single owner. Each company has a separate SQLite database, uploaded/generated files, agent state and browser session. URLs scope every request and file link to its company; background jobs retain that scope when the UI switches. The source directory and inference budget ledger are shared. This is data separation for one trusted owner, not multi-user authorization or tenant security isolation.

## Control and approval behavior

- Billy opens the source selected by the user and extracts visible page text and relevant links. He does not autonomously fill forms yet.
- Take control enables click, type, keyboard and scrolling. Hand back releases the session to source-reading jobs.
- Normal form submissions are intercepted before navigation, including GET forms. Explicit approval resumes that captured form once.
- Other non-read network requests are blocked unless explicitly approved for one exact method and URL, expiring after 30 seconds. Background cross-site writes are blocked without filling the decision queue with analytics notices.
- The network request gate is conservative; it is not a semantic classifier for every site's possible side effects. GET endpoints and custom JavaScript workflows are not universally guaranteed read-only. Do not use this initial browser for authenticated procurement submissions or sensitive accounts until portal-specific controls are tested.
- Requests to private/reserved addresses, unusual ports and non-HTTP(S) URLs are rejected. WebSockets and service workers are disabled. These checks and Chromium's sandbox are defense in depth, not a claim of complete hostile-code isolation or immunity to DNS rebinding.
- Use trusted demo PDFs for now. PDF size and page count are bounded, but extraction runs in a backend thread; a timeout does not terminate that thread. Process isolation/resource limits are needed before accepting hostile uploads.

The browser context is temporary and discarded on service restart. Documents, page captures and events persist. A 403 is an error, not a verified source. East Palo Alto's public RFP page was read successfully in the first integration check; Berkeley returned 403 from both Mac and VM browser checks.

## Validation

```sh
.venv/bin/python -m unittest discover -s tests -v
node --check site/app/workspace.js
```

The directory-count integration check requires the private source file and skips when it is absent. Tests cover California/Berkeley disambiguation, pagination, private-address rejection, browser ownership, one-use approvals and persisted research metadata.

## RFP pipeline and originals

RFPs opens to **My RFPs**, a searchable table with sortable title, agency, status, due date, file count and update date. Add a record directly or choose **Track RFP** from Saved research. Statuses are owner-managed: Researching, Drafting, Ready for review, Responded, Closed — won, Closed — lost and Not pursuing. A status change never sends or submits anything.

Open a record to edit its details and save original PDFs from a public URL or an upload. Downloading validates redirects and does not send browser cookies; a gated portal may require a manual download and upload. Linked PDFs selected from Saved research open the RFP save flow. Arbitrary browser download events are not captured automatically yet.

The complete original is stored as `$BILLY_DATA_DIR/<document-id>.pdf`; metadata, source URL, SHA-256, extraction range and RFP association live in SQLite. On the VM this is `/var/lib/billy/workspace/`. The filename is preserved for downloads. Repeated identical imports for the same RFP and page range reuse the stored document. URL downloads extract the first 100 pages while keeping the whole original; uploads permit choosing a range. Existing imported responses stay under Company Profile and Artifacts.

This central VM storage survives restarts and is available to authorized clients through their workspace connection. It is **not** public storage, multi-user authorization, an off-VM backup or object storage. The SSH tunnel is still required. Next storage step: a private object-store bucket behind authenticated API reads or short-lived URLs, plus SQLite backups and a tested recovery procedure. Do not delete the VM without backing up its workspace.

## Sources and watch allowance

Sources has its own sidebar section, all 6,222 source records, search/state filters and a Watched only filter. Watch selections persist in SQLite. `BILLY_WATCH_LIMIT` sets the workspace allowance (default 10); the server enforces it transactionally, including repeated Watch requests. Unwatching frees a slot. This is a configurable entitlement mechanism, not a connected subscription or billing system. Watching saves intent only: scheduled polling, change detection and alerts are not connected yet. Manual source reads remain available independently.

## Billy’s activity animations

Four consistent Higgsfield/Seedance 2.0 loops provide idle, researching, reading and waiting for input poses. With no active work, Billy enters Snoozing: an existing closed-eye frame with lightweight CSS breathing and floating Zs, requiring no additional generation or model call. Pending decisions take priority, then human browser control, document operations, browser research and snoozing. A browser error uses the waiting pose with a Needs your attention label; disconnection pauses the idle pose. Upload/download operations publish an active document count in `/api/state`, cleared even on failure. The animation does not start jobs or infer success from an RFP status.

Settings includes a clearly separate motion preview. The avatar pause preference persists locally, respects reduced-motion defaults, and playback pauses while the page is hidden. Videos are muted, served from the app’s own assets, and only change sources when the activity changes.

Validate state precedence with `node --test tests/billy-motion.test.mjs` alongside the backend test suite.

## Company knowledge and follow-ups

Company Profile has a secondary section sidebar: Company, Registrations, Experience, Team, Insurance, Compliance, Pricing, References, and Documents. Existing PDF imports remain intact under Documents. `app/company.py` provides SQLite-backed facts, per-field conversation history, conversation stages, and deduplicated queued tasks. `/api/company`, `/api/company/chat`, `/api/company/evidence`, and `/api/company/tasks/{id}` use the existing private API protections.

Profile details appear as document rows with line separators. Clicking a row opens a textarea with Save/Cancel; direct edits use the `edit` action, never accept a pending research offer, and never queue work. Unchanged values retain their evidence links. Facts are marked Reported by you, Unknown, Gap reported, or Evidence linked. Only an explicitly selected existing PDF and valid original page create an evidence link. Corrections clear previous citations. Task completion does not independently verify coverage. Main Chats can continue a scoped company conversation; its active field persists across reloads in session storage.

The illustrative $5M insurance question offers research after a negative answer and queues research only after acceptance. Yes/unsure answers queue verification. Follow-ups appear in Billy’s activity panel; they do not execute automatically. Automatic extraction of policy details, independent policy verification, general model reasoning and voice are not implemented. No insurer is contacted or policy purchased by these endpoints.

## RFP response workspace

An RFP opens as a center-pane page with Files and three editable response-section tabs. The section names, drafts, checklists, and discussion notes persist in SQLite through `app/rfp_workspace.py`. Existing PDFs remain under Files with original review/download actions. Metadata stays in a collapsible details section.

Progress is the proportion of manually completed checklist items; overall progress is weighted by the total number of items across sections, excluding files. An empty draft cannot reach 100%. Starter checklists are suggestions, not requirements extracted from the source. Saving sections uses optimistic versions to reject stale writes. Unsaved drafts are kept in memory while switching sections; use Save section before reloading or closing the app.

Each tab summarizes its remaining saved checklist items and has a scoped text-notes panel. Notes can be explicitly appended to a response draft. Model-generated discussion replies, automatic requirement extraction, and voice are not connected yet. No response submission is triggered by drafting or completing a checklist.

## Workspace design convention

Use the shared top bar for each primary page title. Do not repeat the navigation name in a large content heading, eyebrow, or introductory banner. Place relevant counts beside the top-bar title; begin the content with tabs, controls, or records. Specific record names (such as an RFP title) and meaningful subsection headings remain in the content area. Apply this convention to new pages as well as existing ones.

## Discussing, voice, and actions

The right panel has Discussing, Activity, and Decisions. “Discuss with Billy” on a company field or RFP section opens the contextual conversation in the main Chats area. The right sidebar contains saved learnings and follow-ups, with no message composer. Outcomes persist across turns and reopening the discussion. RFP messages are also saved as section notes. Guided insurance discussion can record a reported coverage statement, a single unambiguous dollar limit, and the Hartford insurer example. It distinguishes current statements from questions, hypothetical coverage, premiums, and deductibles. Occurrence/aggregate terms still need evidence. The $5M example is explicitly illustrative; other comparisons use the requirement saved in Company Profile. A research offer creates a queued task only after acceptance, and never changes or purchases a policy. Conversation stages are scoped per discussion while company facts are shared.

Optional Meta integration uses `META_API_KEY` (or `MODEL_API_KEY`) from the **server environment only**. No key belongs in browser JavaScript or git. A service can load a root-owned, mode-600 environment file via a systemd `EnvironmentFile` drop-in; restart the service when it is idle. `BILLY_META_MODEL` defaults to `muse-spark-1.3` for read-only open-ended replies. Guided fact updates remain deterministic. The model receives the discussion, saved company facts, and selected RFP metadata/section; it has no external-action tools. A key is needed to exercise these provider calls end to end.

Voice uses Meta `muse-voice-transcribe-1.0`, push-to-talk. The browser captures at most 60 seconds, resamples to mono 24 kHz PCM WAV, and sends it to the private backend, which forwards it to Meta. Raw audio is not written by Billy to disk; provider retention is governed by Meta. The transcript returns to an editable composer. Only pressing Send saves it and runs the same guided action flow as typed text. Leaving Chats, hiding the page, or ending the conversation stops recording. Switching between the right-side tabs does not move or interrupt the central conversation. Optional read-aloud uses the browser's speech synthesis voices, separate from Meta transcription. Microphone capture requires localhost or HTTPS. Missing credentials disable voice with a clear status; provider errors do not silently switch transcription services.

Text discussion uses Billy's working clip with a messaging bubble. Voice listening, transcription, and spoken replies use a dedicated generated corded-phone portrait with a gentle CSS breathing loop. Both respect pause and reduced-motion preferences. The phone pose is an animated still, not a generated video or lip sync. Preview it under Settings → Billy’s expressions → On the phone.

### Voice provider decision

Recommended next integration: **Gemini Live** for Billy’s natural back-and-forth conversation. It combines spoken replies, user interruptions, input/output transcripts, and tool calls. Muse Voice Transcribe is speech-to-text and needs separate reasoning and speech generation. The existing optional Meta push-to-talk adapter remains a transcription path; Gemini Live is a recommendation, not an already-connected service. Credentials and a live end-to-end test are still required.

References: [Gemini Audio](https://deepmind.google/models/gemini-audio/), [Live API](https://ai.google.dev/gemini-api/docs/live-api), [Muse Voice Transcribe](https://dev.meta.ai/docs/speech-to-text).


### Watched opportunities

The RFP tab defaults to All opportunities; My RFPs contains manually saved or explicitly pursued bids. Watching a source queues a scan within 15 seconds when Billy is free. The service checks hourly while running, with a manual refresh button. Public downloads reuse DNS validation and pinned connections, without browser cookies or form submission. Discovery and document reviews are stored in SQLite; full originals remain in private VM storage.

Berkeley and the public Municode tables used by East Palo Alto and Siskiyou County have tested adapters. Other sources use conservative table/link discovery and report partial coverage, including pagination or access limits. No company-fit threshold removes candidates. A bounded 100-page listing scan follows same-site next-page links. PDF extraction retains full originals and reads at most 100 pages per file. Previously discovered RFPs survive portal failures and disappearing listings; current availability must be confirmed at the source.

Fit is a deterministic, preliminary lexical score: 65% title term overlap and 35% body term overlap against company overview, services, sectors and projects. Unknown company capabilities or unreadable detail pages produce no score. Matching terms and company evidence page links are shown. This is not semantic AI evaluation, compliance verification, or a win probability. Ratings are recalculated from current profile facts on each feed load. Pursuit never submits anything externally.

A readable RFP with a supporting PDF beyond the extraction limit can receive a preliminary score from the available pages, with an explicit incomplete-review warning. Failed downloads never erase an earlier successful review. Municode page text excludes navigation and footer content from the fit calculation.

## Workspace persistence and checks

The original company retains its existing database and files in `BILLY_DATA_DIR`. Additional companies live under `companies/<id>/`. The registry and shared inference usage ledger remain in the original database, preserving usage already billed before this feature. All saved companies resume source watchers on service startup. The source directory is shared read-only; watched selections remain company-specific.

Install test dependencies with `uv pip install --python .venv/bin/python -r tests/requirements.txt`, then run `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'` and `node --test tests/*.test.mjs`. Tests use temporary workspace data and no live model calls.

### Shared opportunity catalog

Jev imports are stored once in `catalog.sqlite3` beside the default workspace database. Existing and future company workspaces use this shared catalog, with keyword ranking calculated from each company's own profile. Private local RFP records, pursuit status, notes, documents and drafts remain in the company workspace. Imported evidence is unverified and never marked as a completed source review.

The private `POST /api/opportunity-imports` endpoint accepts a labeled batch of up to 1,000 candidates. Batch content hashes make retries idempotent, and canonical URL matching preserves existing RFPs without overwriting them. `POST /api/opportunity-imports/{id}/visibility` with `active: false` removes the shared batch from every company's opportunity feed; `active: true` restores it. This is reversible visibility, not data erasure: pursued items remain in My RFPs and all saved work is retained. Batch removal and restoration are administrative API operations; customer opportunity screens do not expose ingestion labels or batch controls. These controls inherit the existing single-owner private connection policy; this is not a multi-user admin permissions implementation.

Billy's opportunity search is paginated, searchable and ranked for the current company. Imported records classified closed are excluded by default from his search, but remain available via the availability filter. `inspect_rfp` includes the complete saved catalog evidence and quality notes. No attachments are fetched as part of catalog import.

## Chat outcomes and RFP previews

Completed agent replies include receipts derived from successful saved tool results, plus links to updated company profiles and selected/recommended RFPs. Cards stay with the original turn, including existing chat history. `recommend` attaches 1–4 candidates without pursuing them; `pursue` attaches the selected RFP automatically. Failed tools never create success receipts. Original reply text and private workspace boundaries are preserved.

Saved original PDFs have a workspace-scoped `/api/documents/{id}/preview` endpoint. Poppler renders only page one at a maximum dimension of 720 pixels; the result is cached privately. Install `poppler-utils` on Ubuntu (included in `deploy/install-app.sh`) or `brew install poppler` on macOS. Rendering has a 15-second timeout and one job per workspace at a time. Missing PDFs or unavailable previews use agency/title cards; no invented logos or automatic source downloads.


### Autopilot preparation

Start Autopilot from RFPs to prepare one best-fit opportunity per run, or use Prepare with Autopilot inside a particular RFP. Billy reuses that workspace's company evidence, checks source documents and deadlines, saves cited requirements, drafts three response sections, and exports a review PDF without intermediate permission questions. Missing details remain explicit placeholders and review gaps. Source failures or no suitable opportunity are reported as blockers. Runs are bounded to 80 actions and the existing shared inference budget; Pause and Continue retain saved work. This is a user-started run, not an unattended recurring submission service.

The first nonempty section moves Researching to Drafting. Exporting all three sections moves preparation to Ready for review. Editing a section invalidates its old PDF and moves Ready for review back to Drafting. Closed/responded states are never automatically reopened. Autopilot filters expired saved deadlines, exposes days remaining, and asks the model to prioritize fit and feasible preparation time; precise closing times and unknown dates still require final source review.

Review and submit opens the PDF, response text, deadline, and unresolved requirements. The user confirms review before following the original source/submission instructions. No delivery integration is connected: this handoff does not submit, sign, email, purchase, or mark the RFP Responded.
