# Data model and API contracts

## Persistence layout

```text
BILLY_DATA_DIR/
  workspace.sqlite3             default company + workspace registry + usage ledger
  catalog.sqlite3               shared opportunity batches/items
  <document-id>.<extension>     default company originals / saved source text
  previews/                     generated first-page previews
  response-pdfs/<id>.pdf         immutable generated review copies
  companies/<workspace-id>/
    workspace.sqlite3           company-specific state
    <document-id>.<extension>
    previews/
    response-pdfs/
```

Preview folder spelling and file naming are defined in `document_previews.py`; thumbnails are derived caches. Back up the entire data tree, not only SQLite. The source directory is separate and must be backed up according to its access policy. Browser cookies/context are temporary and not restored after a restart.

## Table ownership

| Domain | Tables | Notes |
|---|---|---|
| Company registry | `workspaces` | Default DB only; `default` plus generated 32-character IDs |
| Shared ingestion | `catalog_batches`, `catalog_items` | Shared catalog DB; digest/URL deduplication and batch visibility |
| Catalog links | `opportunity_catalog_links` | Company DB maps shared entries to local records |
| Pipeline | `rfps`, `discovered_rfps` | Discovery starts unpursued; My RFPs includes pursued/manual records |
| Sources/research | `watches`, `checks`, `source_scans`, `opportunity_sources`, `opportunity_reviews`, `rfp_source_pages` | Preserve source failures, saved evidence and allowed attachment links |
| Files | `documents` | Original filename, association, hash, extraction ranges, text, media type and source URL |
| Company knowledge | `company_facts`, `company_web_pages`, `company_web_evidence` | Evidence/status attached to saved facts |
| Profile history and agenda | `company_messages`, `company_tasks`, `discussion_messages` | Per-field audit trail of edits/evidence/tasks, queued follow-ups, and agenda opening questions by company field or RFP section; older `company_dialogue`, `discussion_context` and `discussion_outcomes` tables are unused |
| Main agent | `agent_runs`, `agent_messages`, `agent_steps`, `agent_read_pages`, `agent_message_documents`, `agent_analysis`, `agent_modes` | Persistent run/selected RFP, action receipts, source-read progress and mode |
| Sequential queue | `agent_queues`, `agent_queue_items` | Run → session; completed/blocked items retained across Continue |
| Usage | `agent_usage` | All company runtimes use default DB ledger; reservations remain if no actual usage is returned |
| Response | `response_sections`, `response_notes`, `response_pdfs` | Versions/checks and immutable PDF versions/page counts |
| UI/history | `events`, `state` | Activity and saved research; not a delivery receipt |

Schemas are created and extended during module registration with `CREATE TABLE IF NOT EXISTS` and selected column checks. There is no migration framework or downgrade runner. Back up first, add compatible migrations, and test existing databases before shipping schema changes. Do not replace a database to “fix” a schema issue.

## Scope and access

Global registry: `/api/workspaces`. Workspace API: `/w/<workspace-id>/api/...`. Unprefixed `/api/...` retains compatibility with the default workspace. The frontend uses `/app/?workspace=<id>#/<view>`; changing a hash is navigation, not an API call.

Host must be `localhost`, `127.0.0.1` or the test host. An Origin, if supplied, must be allowed. Writes need `X-Billy-Client: workspace`; CORS allows GET/POST/OPTIONS. These are private-connection protections, **not identity checks**. Never give an untrusted user an arbitrary workspace ID and consider the data protected.

Use FastAPI request models and route implementations as the authoritative payload schema. Most updates are POST. Validation errors are normally 422; unknown records 404; task ownership/stale versions 409; private-access rejection 403. Some tool-level validation errors are returned to the model as tool results rather than HTTP responses.

## Endpoint map

All paths below start at the selected workspace API unless marked global.

| Area | Routes |
|---|---|
| Registry (global) | `GET/POST /api/workspaces` |
| Snapshot | `GET /state`, `GET /agent` |
| Sources | `GET /sources?q=&state=CA,NV&offset=&limit=&watched=`, `POST /sources/{id}/watch` |
| Source scan/feed | `POST /research`, `POST /tour` (ask for a browser review cycle of the watched listings; Start Autopilot asks automatically; runs whenever the browser is free), `GET /opportunities`, `POST /opportunities/refresh`, `POST /opportunities/{id}/pursue` |
| Shared imports (administrative) | `GET/POST /opportunity-imports`, `POST /opportunity-imports/{id}/visibility` |
| Browser | `GET /browser/frame`, `POST /browser/control`, `/browser/action`, `/browser/approval` |
| RFPs | `GET/POST /rfps`, `POST /rfps/{id}`, `GET /rfps/{id}/workspace`, `POST /rfps/{id}/sections/{section}`, `POST /rfps/{id}/discussion/{section}` |
| Originals | `POST /documents` (multipart PDF/range), `POST /rfps/{id}/documents/download`, `GET /documents/{id}`, `/documents/{id}/file`, `/documents/{id}/preview` |
| Company | `GET /company`, `POST /company/facts/{field}`, `/company/evidence`, `/company/tasks/{id}`, `/company/attachments` (multipart) |
| Conversation | `GET /discussion/config`, `/discussion/agenda`, `POST /discussion` (records an opening question only), `/discussion/transcribe` |
| Live voice | `GET /voice/config` (readiness, current voice and its source, the 30 prebuilt voices), `POST /voice/settings` (choose this workspace's voice; empty restores the default; applies to the next call), `POST /voice/sample` (a short Billy line in a voice as WAV, generated by Gemini text-to-speech once per voice and cached under `voice-samples/`), `POST /voice/sample` (a short Billy line in a voice as WAV, generated by Gemini text-to-speech once per voice and cached under `voice-samples/`), `POST /voice/token` (mints a single-use Gemini Live token with the full session setup locked in: model, audio, voice, Billy's instruction and functions) |
| Agent controls | `POST /agent/message`, `/agent/pause`, `/agent/resume` |
| Review | `GET /response-pdfs`, `/response-pdfs/{id}`, `/rfps/{id}/review` |

PDF export is an agent tool backed by `register_response_pdf`; there is no public “submit” endpoint. Read-only requests may synchronize shared catalog records or generate/cache a preview, so do not assume GET means zero internal persistence.

## Representative contracts

Start continuous preparation (this spends inference budget and writes drafts):

```json
{
  "request_id": "unique-request-id",
  "text": "Keep preparing suitable RFPs for my review; do not submit.",
  "autopilot": true,
  "continuous": true
}
```

For a single RFP use `continuous: false` and `context: {"rfp_id":"..."}`. Ordinary chat can include `document_ids` (up to five saved company attachment IDs). Duplicate request IDs return existing state. Upload the attachment first; chat references its saved ID rather than re-uploading bytes.

`POST /agent/pause` accepts `{}`. `POST /agent/resume` accepts `{}` to preserve mode or `{"continuous":true}` to enable the queue on an interrupted/paused/error Autopilot run. It is not a start endpoint for completed runs. A new `/agent/message` starts a new queue session. One run record may be reused across turns; do not equate run ID with one request or one queue session.

`GET /agent` includes `run.status`, `run.rfp_id`, `run.autopilot`, `run.continuous`, `run.blocked_reason`, `run.queue_items`, the most recent 60 messages with `run.total_messages` and `run.messages_truncated`, successful-action-derived outcomes, the steps belonging to those messages, document review and usage. Run states are `running`, `waiting`, `complete`, `paused`, `interrupted`, `error`. `complete` means that turn stopped; check `blocked_reason` and review readiness before claiming success. Queue items use `ready` or `blocked`; the currently selected item lives on the run until it finishes.

The Response canvas uses the existing section POST route, saving changed sections sequentially rather than as an atomic transaction. On partial failure, completed saves remain saved and unsaved edits are retained. A 409 exposes the newer version and offers an explicit discard/reload action; no automatic overwrite occurs. Saving does not regenerate the review PDF.

Response-section POST requires `title`, `body`, `checks` and `version`. A stale version returns 409. Read the workspace before editing and preserve existing checklist items. A review response reports `ready`, `expired`, `closed`, `pdf`, `gaps`, `sections` and `submission_connected: false`. `ready` requires a current file matching section versions/title, nonempty sections and no supplied past deadline or terminal status. A missing deadline is allowed and still needs confirmation; readiness is not deadline verification or an eligibility/compliance verdict.

## Evidence invariants and limits

- Retain the complete original; extraction range/text is a separate representation. Company documents have `rfp_id = NULL`.
- PDF imports: 25 MB, up to 100 extracted pages; automatic imports take the first 100. Range import uses original 1-based page numbers. PDF text is capped per page; encrypted/unreadable files fail.
- Agent reads: up to eight pages per call, with pagination/size guards; PDF page text is stored up to 50,000 characters. Analysis requires reading all extracted RFP pages; reused company documents already being read must be fully read before drafting. Read markers belong to the current user turn and are cleared when a new message starts, so a later request re-reads what it cites; one continuous Autopilot request counts as one turn. This does not prove all original pages were extracted or every attachment was found.
- Exact source quotations and document/RFP association are checked. Website/text excerpt numbers are not PDF page numbers. OCR is not proof of an unseen logo, signature or layout.
- Images: 20 megapixels maximum, normalized to at most 3000×3000 for English OCR. DOCX/text extraction is bounded; original remains. Scanned PDF OCR is not implemented.
- RFP source reads: only saved URL/recorded links, public-address validation; eight calls between ask/finish boundaries. HTML source text is bounded at 120,000 characters and marked when clipped.
- Imports: at most 1,000 candidates per batch. Hidden shared batches retain pursued company work. Visibility is reversible, not deletion.
- Review copies are immutable; section/title changes make old copies stale. Human review flags remain independent from automatic preparation status.
