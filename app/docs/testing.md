# Verification and test strategy

## Automated tests

From the repository root, after installing `tests/requirements.txt`:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
node --test tests/*.test.mjs
node --check site/app/workspace.js
git diff --check
```

Tests mock model/provider calls and public fetches where appropriate; they are not live provider or portal certification. Set `BILLY_DATA_DIR` to a disposable temporary directory **before** importing the server, or leave it unset so tests select temporary data. Never run tests with a production `BILLY_DATA_DIR`. Private-directory-specific integration checks depend on local inputs and must not be treated as a clean-checkout requirement.

For one area:

```sh
.venv/bin/python -m unittest tests.test_autopilot -v
node --test tests/billy-motion.test.mjs
```

## Coverage map

| Tests | What failures usually mean |
|---|---|
| `test_agent`, `test_autopilot` | Tool discipline, citations/page reading, concise replies, budgeting, queue continuation, duplicate prevention, pause/resume, real saved sections/PDFs |
| `test_workspaces`, `test_db_connection` | Company scoping, shared ledger/catalog ownership, connection closure/transactions |
| `test_opportunities`, `test_opportunity_imports`, `test_workspace` | Discovery, feed evidence/fit, import visibility/idempotency, source filters, browser/API guards |
| `test_company*`, `test_discussion*` | Fact provenance, direct edits, evidence links, follow-ups, attachment parsing, website learning and agenda openers |
| `test_rfp_workspace`, `test_response_pdf` | Optimistic versions, manual review progress, PDF immutability/staleness |
| `test_chat_outcomes`, `test_document_*` | Honest successful-action receipts, original previews, read progress and scopes |
| `*.test.mjs` | Motion precedence, chat cards/attachments/suggestions, agenda rendering, document activity, audio encoding, live-voice PCM conversion and function bridge |

The sequential Autopilot regression generates two actual review PDFs in a temporary workspace with a fake action provider. It asserts Researching visibility before drafts, immediate continuation, saved queue items and exclusion from reselection. Separate regressions cover blocked-item advance, whole-workspace stop, pause/resume and upgrading an already-ready single-response job without changing its PDF. This tests the orchestration, not how well a live model chooses bids.

## Browser smoke test

Use a disposable local company and synthetic public/source fixtures. For workflow behavior:

1. Open the app, create/select a company, confirm all file/API links retain its workspace scope.
2. Upload a small synthetic proposal through chat; confirm original preservation, preview and Company Profile entry. Remove a staged attachment before Send to check it is not sent.
3. Open Sources, select two states, and verify union filtering and watch persistence.
4. Start test Autopilot against two synthetic candidates with a fake model/fetch. Confirm active Autopilot label, first row at Researching, then Drafting/Ready for review, and next row appearing without another click or reload.
5. Pause mid-item and continue. Confirm the selection and queue history survive. Do not treat an animation alone as proof of backend work.
6. Open a ready RFP's review dialog. Check the current PDF, flagged details, manual checkbox and agency link. Do not follow through with a real submission.
7. Click a Ready-for-review badge and confirm the Response canvas opens. Scroll through all sections, edit and save, then reload to verify persistence and intact review checks. Test a partial save failure and navigation while a save is pending. Edit one saved section. Confirm the old PDF becomes stale and status returns to Drafting. Test a stale version conflict from another local session.
8. Switch companies; verify documents, selected RFP and chat remain distinct. Watcher/catalog sharing should not copy private draft content.

For a real-provider validation, obtain explicit authorized inputs and spend scope, use an isolated workspace and record source evidence, model ID, actual tool outcomes, PDF and gaps. Do not turn a fixed fixture run into a claim of real portal/model reliability.

## Documentation checks

Check relative Markdown links, endpoint names, environment defaults, dependency pins and referenced files against the repository. Render the technical HTML and workflow diagram. Run local startup/read-only API smoke checks using the documented commands, without production secrets. A docs-only change normally does not require repeating every backend test; broaden checks when executable examples or behavior changes warrant it.

## Release record

Record the exact code revision, checks run, live read-only verification, any skipped check and known limits in private deployment receipts. Avoid hard-coding a growing test count as a product capability. Current tests remain the source of truth. Browser fixtures, screenshots, credentials and user PDFs are not release artifacts for Git.

`tests/response-canvas.test.mjs` covers changed-section saves, original versions/checklists, validation before writes, partial failures and refreshing untouched draft caches.
