# RFP Agent — Billy

Billy helps a business turn its existing company knowledge into responses to relevant RFPs. It discovers opportunities, reads source documents, saves cited company facts and requirement gaps, drafts responses, and generates PDFs for human review.

**Current implementation:** a private, single-owner workspace with multiple company profiles, running on a Vultr VM. Main chat and Autopilot use Vultr Serverless Inference. Continuous Autopilot prepares suitable RFPs one after another; final submission remains with the user. This is a working prototype, not a public multi-tenant service.

Built for the Vultr Agent Arena Hackathon 2026 · Future of Work.

## New engineer? Start here

1. Read the [engineering handoff](app/README.md) for the reading order and system boundaries.
2. Follow [local development](app/docs/development.md) to run an isolated workspace.
3. Read [architecture](app/docs/architecture.md), then [data and API contracts](app/docs/data-api.md).
4. Use the [operations runbook](app/docs/operations.md) before touching the deployment or customer data.

[Capabilities and limitations](app/docs/capabilities.md) · [Testing](app/docs/testing.md) · [Decisions and next work](app/docs/decisions.md)

These documents describe implementation baseline `4140a21` (September 26, 2026). Source code remains authoritative; environment-specific receipts and credentials are not in Git.

## Run the app locally

Requires Python 3.12, `uv`, and the system packages described in the development guide.

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r tests/requirements.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m uvicorn app.server:app --host 127.0.0.1 --port 8081
```

Open [the workspace](http://localhost:8081/app/). Without inference credentials, manual workspace features remain available. Without a supplied source directory, Sources is empty; the private directory is intentionally excluded from this repository. Do not run a local server on 8081 while a deployment tunnel owns that port.

For the **static pitch only**, with no application backend:

```sh
python3 -m http.server 8080 --directory site
```

Open [the pitch](http://localhost:8080/) or [technical overview](http://localhost:8080/technical/). A static preview is not a connected backend. On port 8080, the app frontend points its API at loopback port 8081.

## Repository map

| Path | Purpose |
|---|---|
| `app/` | Python API, agent orchestration, evidence processing, SQLite persistence |
| `app/docs/` | Versioned engineering handoff and operating procedures |
| `site/app/` | Plain JavaScript workspace UI; no frontend build step |
| `site/technical/`, `site/assets/workflow.mmd` | Public technical explanation and workflow diagram |
| `site/` | Public pitch, shared assets, technical page and app frontend |
| `deploy/` | Separate public nginx and private systemd installers |
| `tests/` | Python and Node regression tests |

Private working folders such as `planning/`, `research/`, root `docs/`, `.private/`, recordings and datasets are ignored. Root `docs/` can contain user proposal files; it is **not** the engineering documentation folder. Never force-add these folders to make a handoff “complete.”

## Deployment and access

`deploy/install.sh` publishes only `site/` through nginx. `deploy/install-app.sh` installs the private API as a non-root systemd service on port 8787, which the firewall exposes only on the NetBird interface. Reach it through NetBird: the authenticated reverse-proxy Service over HTTPS, or peer-to-peer from an enrolled machine at the VM’s NetBird address. SSH remains for administration. Per-user accounts and tenant authorization inside the app are not implemented; NetBird’s login is the gate. See the [runbook](app/docs/operations.md); do not expose the private API through public nginx.

## Evidence and delivery boundaries

Company facts retain document, website or user-statement provenance. A quotation is evidence of what the source says, not independent verification of current insurance, staffing, rates or eligibility. Review PDFs preserve saved section versions; manual review is still required. Billy has no submission, email, signing, purchasing, shell or arbitrary HTTP tool. The review handoff opens agency instructions; it does not send a bid.

The historical demo directory contains 6,222 records. That is not a count of verified portals, active opportunities or integrations. Use your own authorized source data via `BILLY_SOURCES`.

## License and assets

Code: MIT. The proprietary source directory and private proposals are not included or licensed by this repository. Billy’s generated imagery and animation illustrate his activity; they are not proof of a completed action or contract award. The original hero animation used Higgsfield / Seedance 2.0. The GitHub mark is from Primer Octicons; its notice is in `site/assets/github-LICENSE.txt`. No endorsement by demonstration proposal owners is implied.
