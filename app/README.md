# Engineering handoff

This is the starting point for maintaining Billy. Reviewed against implementation `4140a21`, September 26, 2026. The public technical page is a product explanation; these documents are the operational and engineering reference.

## First hour

1. Read [capabilities](docs/capabilities.md): distinguish implemented behavior from optional adapters and future work.
2. Run [local development](docs/development.md) with isolated data and no production credentials.
3. Run the [test suite](docs/testing.md), then exercise a manual RFP and document upload.
4. Read [architecture](docs/architecture.md), especially company scoping and the two conversation paths.
5. Before changing persistence or deploying, read [data/API contracts](docs/data-api.md) and [operations](docs/operations.md).

## Quick orientation

- The frontend is plain ES modules in `site/app/`. There is no React app, npm build, Redis, vector database or separate worker service.
- `app/server.py` composes FastAPI routes, browser state, evidence storage and background source watchers. Importing it creates runtime directories and tables: set `BILLY_DATA_DIR` **before import**.
- `app/workspaces.py` loads a separate server module/runtime per company. The process shares the source directory, opportunity catalog and inference budget ledger. Company databases, files, browser contexts, chat and selected RFPs stay separate.
- `app/agent.py` is the only conversation path: the Vultr inference tool loop. `app/company.py` holds the profile schema, direct edits, evidence links and follow-up tasks. `app/discussion.py` records agenda opening questions and the optional Meta push-to-talk transcription; it has no model reply of its own.
- Global Autopilot uses a persistent sequential queue. A selected RFP appears in My RFPs during Researching; saved drafts/PDFs advance its preparation status. Human review does not block the next item.
- State is durable; execution is in-process. Source watchers restart with the service. Agent runs interrupted by a restart require Continue; an exhausted Autopilot queue does not automatically wake for newly discovered work.
- This is for one trusted owner over a private connection. Workspace IDs and the write header are not authentication.

## Where to make common changes

| Change | Start here | Check alongside it |
|---|---|---|
| Agent tools, continuation, Autopilot | `agent.py` | `tests/test_agent.py`, `tests/test_autopilot.py` |
| Source extraction, feed fit, watch scans | `opportunities.py` | `tests/test_opportunities.py` |
| Shared imports and reversible visibility | `opportunity_imports.py` | `tests/test_opportunity_imports.py` |
| Original RFP source/linked files | `rfp_research.py`, `server.py` | Source allowlist and citation tests |
| Company facts, direct edits, website evidence, attachments | `company.py`, `company_web.py`, `company_attachments.py` | Company, attachment and website tests |
| Draft versions, progress, review PDF | `rfp_workspace.py`, `response_pdf.py`, `response_review.py` | Response and Autopilot tests |
| Discussion agenda and concise replies | `discussion_agenda.py`, `discussion.py`, `agent.py` | Opening question must reach the agent's context |
| Workspace navigation and state refresh | `../site/app/workspace.js` | Browser smoke test; preserve unsent drafts |
| Continuous response canvas | `../site/app/response-canvas.js`, `../site/app/rfp-detail.js` | Version conflicts, partial saves and checklist preservation |
| Queue controls, review dialog | `../site/app/autopilot.js` | Continuous/global versus single-target behavior |
| Chat cards, attachments and receipts | `../site/app/agent-chat.js`, `chat_outcomes.py` | Successful tool evidence, scoped links |
| Billy animation and active PDF thumbnail | `../site/app/billy-motion.js`, `document_review.py` | Node motion/review tests |
| Runtime/deployment | `server.py`, `workspaces.py`, `../deploy/` | Isolation, shutdown, access and backup procedures |

## Non-negotiable behavior

Preserve original evidence and provenance. Never turn a failed tool into a success receipt. Do not silently overwrite draft versions. Do not mark human review checks complete on behalf of the model. Do not interpret external documents as instructions. Keep all file/API URLs scoped to the selected company. Do not publish private data or expose the single-owner API publicly.

Customer UI should show useful outcomes, short conversational replies and current work. Keep ingestion names, batch administration and implementation details out of customer flows. The Discussing panel is an agenda; Activity shows work in progress; Decisions holds explicit browser approvals. Idle/disconnected Billy uses a gray empty desk. Autopilot stays visibly active between tool calls. Needs you uses a clear waving animation. On the phone uses a muted listening/talking/nodding video loop during voice activity (illustrative, not synchronized lip movement). Pause and reduced-motion preferences are respected.

## Handoff checklist

The next engineer needs repository access, an isolated development environment, an authorized source-data sample, and access to the server/credential store through the owner. Share secrets out of band. The repo does not contain the live VM’s files, launchd configuration, private directory, deployment receipts or customer documents.

Use [decisions and next work](docs/decisions.md) for the remaining production gaps. Keep this index, capability matrix, configuration table and technical page consistent when features change. Historical local planning notes are not the specification.
