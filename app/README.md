# Billy workspace

A single-owner app with a six-section UI and a shared Chromium research browser. The API persists source checks, page text, PDF imports and activity in SQLite. Source lookup and scoped company-profile conversations in Chats are deterministic; open-ended chat, semantic matching, proposal drafting and voice editing still need a model integration.

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

Then open http://localhost:8081/app/, or use the local static UI at http://localhost:8080/app/. The browser, imported PDFs and database are on Vultr when using this tunnel. No new publicly reachable API port is needed. Do not proxy this API to public nginx until authenticated HTTPS/NetBird access and workspace authorization have been implemented. There is one shared workspace, not tenant isolation.

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

Facts are marked Reported by you, Unknown, Gap reported, or Evidence linked. Only an explicitly selected existing PDF and valid original page create an evidence link. Corrections clear previous citations. Task completion does not independently verify coverage. Main Chats can continue a scoped company conversation; its active field persists across reloads in session storage.

The illustrative $5M insurance question offers research after a negative answer and queues research only after acceptance. Yes/unsure answers queue verification. Follow-ups appear in Billy’s activity panel; they do not execute automatically. Automatic extraction of policy details, independent policy verification, general model reasoning and voice are not implemented. No insurer is contacted or policy purchased by these endpoints.
