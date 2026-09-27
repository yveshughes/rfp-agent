# Decisions, known risks and next work

This is an implementation handoff, not a promise that planned integrations exist. Review these decisions when changing the system rather than adding a second contradictory description to the README.

| Decision | Why it exists | When to revisit |
|---|---|---|
| Private single-owner service over SSH | Enables a working demonstration without claiming tenant security | Before anyone outside the trusted owner accesses company evidence |
| Separate runtime and DB/files per company | Binds jobs to the correct company's state; preserves default workspace compatibility | Before multi-process scaling or real authorization |
| Shared catalog, private pursuit/drafts | Discovery benefits every business; company relevance and response work stay local | When deduplication/update ownership needs richer semantics |
| Plain frontend modules | Small build footprint and direct inspectability | When UI complexity justifies a build system; preserve cache invalidation |
| SQLite + in-process tasks | Minimal infrastructure; persistent results with simple ownership | Before durable restarts, concurrent workers or larger volumes |
| Bounded model tool calls with stored receipts | Restricts actions and makes saved outcomes inspectable | As tool set grows; add tests and provenance before exposing mutations |
| Complete extracted-page reading and exact quotations | Reduces claims based on partial imported text | Add better document parsing/coverage evaluation; don't claim full original review from an extraction subset |
| Lexical feed ranking + model candidate judgment | Explainable initial matching without a vector stack | Measure relevance and deadline quality on an evaluation set before replacing it |
| Sequential Autopilot queue | Finishes preparation without blocking on review; one active RFP limits collisions | Before recurring auto-wake, parallel candidates or unattended delivery |
| Human review checks independent of drafting | A generated draft does not prove correctness | Preserve the distinction in any new readiness metric |
| Immutable review PDF | Keeps exact prior output and version provenance | Add templates/fonts/forms without overwriting historical copies |
| Optional voice adapter separate from main agent | Editable transcript keeps actions on the existing Send path | A future live voice integration needs interruption, transcript, tool and approval semantics |

## Priority work for a production handoff

1. **Identity and access:** authenticated HTTPS ingress, authorization on every workspace and file request, explicit admin permissions. NetBird remains a candidate access layer, not implemented tenant authorization.
2. **Durability:** encrypted off-VM backups, retention/restore drills, object storage if appropriate. Decide recovery objectives; current on-VM files alone do not meet disaster recovery.
3. **Durable execution:** recoverable job ownership, retry/idempotency semantics, restart policy and scheduler coordination. Do not solve this by increasing Uvicorn workers.
4. **Evidence and relevance evaluation:** fixtures plus live authorized source tests, date/timezone accuracy, unavailable portal behavior, incomplete extraction, stale company facts and model hallucination checks.
5. **Document security and output fidelity:** process/resource isolation for hostile files, scanned-PDF OCR, Unicode/font/layout support, required form/attachment assembly and page-limit validation. Current PDF extraction timeout cannot kill its backend thread.
6. **Observability and privacy:** structured run metrics, redacted logs, usage reconciliation, retention/erasure policies and workspace export. The current usage estimator is fixed-rate and approximate.
7. **Delivery:** only after requirements exist for exact-version approval, destination, attachment list, credentials, audit receipt and failure/retry behavior. No submission/email tool exists today; a review checkbox plus agency link is not delivery.
8. **Live voice and notifications:** provider selection/validation, interruption and action-review rules, notification preferences, and separately authorized external sends.

## Known engineering constraints

- Additive startup migrations have no version framework or downgrade tests.
- One service owns all companies. CPU/memory/disk/browser contention and a shared usage budget are real limits; no load or availability guarantee has been established.
- Continuous Autopilot does not automatically wake after exhaustion or resume after a restart. It skips handled items within a queue session; a new session may retry blocked items.
- Browser controls defend against many unwanted writes, but GET side effects and custom authenticated portals need targeted validation. No universal hostile-browser isolation is claimed.
- Prior successful receipts are preserved, but arbitrary failure boundaries are not guaranteed exactly-once execution. Inspect saved state before retrying.
- The generated PDF uses ReportLab Times-Roman. Exact agency typography, signatures, certifications, forms and attachments still require review.
- The older guided company/discussion conversation was removed on September 26, 2026. Agenda topics open Billy's question and hand the answer to main chat; profile edits, evidence links and follow-up tasks remain direct API actions.
- Historical local demo plans contain proposed features and account details. They are private records, not deployment instructions for a new engineer.

## Change documentation with code

For every material change: update capabilities, configuration/API contracts if affected, operational implications, tests, and the public technical explanation. Name actual limitations. Keep resolved implementation notes out of customer copy; preserve historical deployment receipts privately. Never mark a planned integration as implemented based only on a UI mock, queued task or generated animation.
