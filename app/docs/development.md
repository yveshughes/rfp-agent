# Local development and configuration

Run from the repository root. Keep local development separate from the live tunnel and production workspace. Importing `app.server` initializes tables, so choose the data directory before launching or importing it.

## Prerequisites

Use Python 3.12 and `uv` for the validated development environment. Node with `node --test` support is needed only for JavaScript tests. Install Poppler and Tesseract for document previews/image OCR:

```sh
# macOS
brew install poppler tesseract

# Ubuntu/Debian alternative
sudo apt-get install python3-venv poppler-utils tesseract-ocr
```

Then create the environment:

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r tests/requirements.txt
.venv/bin/python -m playwright install chromium
# On Linux, if browser system libraries are missing:
# .venv/bin/python -m playwright install-deps chromium
```

`tests/requirements.txt` includes application dependencies plus httpx. Runtime-only installations can use `app/requirements.txt`.

## Isolated local app

If 8081 is already used by the demo tunnel, use 8090 with an explicit allowed origin:

```sh
mkdir -p .private/dev
printf '[]\n' > .private/dev/sources.json
export BILLY_DATA_DIR="$PWD/.private/dev/workspace"
export BILLY_SOURCES="$PWD/.private/dev/sources.json"
export BILLY_ORIGINS='http://localhost:8090,http://127.0.0.1:8090'
.venv/bin/python -m uvicorn app.server:app --host 127.0.0.1 --port 8090
```

Open [the local workspace](http://localhost:8090/app/). Empty Sources is expected with this sample. Manual company facts, RFP records, uploads, drafts and review UI can be exercised without inference. Do not add `--workers`; use one process. `--reload` is optional during development but interrupts browser/agent tasks whenever code changes.

For a populated test directory, supply your own authorized JSON array. Minimal record shape:

```json
[{"id":1,"name":"Example agency","state_code":"CA","official_url":"https://example.org","procurement_url":"https://example.org/procurement"}]
```

This is a schema example, not a functioning procurement source. Keep IDs stable: watches/checks reference them. Source data is read at startup. Do not commit the private directory; an absent file yields an empty list, while malformed JSON prevents startup.

## Configuration reference

All secrets belong in the server environment, never frontend JavaScript or version control. The app does not automatically load `.env` files; keep local secret files under the ignored private folder and source them from your own launch command.

| Variable | Default / meaning |
|---|---|
| `BILLY_DATA_DIR` | `<repo>/.billy`; default workspace, registry, files, catalog and child companies |
| `BILLY_SOURCES` | `<repo>/rfpsonar-found-rfp-sources.json`; optional private JSON directory |
| `BILLY_WATCH_LIMIT` | `10`; per-company source allowance |
| `BILLY_ENVIRONMENT` | `This Mac`; display label, not routing configuration |
| `BILLY_ORIGINS` | localhost and 127.0.0.1 on ports 8080 and 8081, comma-separated; add the actual development origin |
| `VULTR_SERVERLESS_INFERENCE_API_KEY` | No default; enables main agent with the model ID |
| `BILLY_VULTR_MODEL` | No default; deployment baseline `glm-5.3`; must match returned provider model |
| `BILLY_INFERENCE_BUDGET_USD` | `100`; shared cumulative estimated usage/reservations, not a billing subscription or daily reset |
| `PLAYWRIGHT_BROWSERS_PATH` | Playwright default locally; `/opt/billy-browsers` on the VM |
| `META_API_KEY` / `MODEL_API_KEY` | Optional Meta transcription key for push-to-talk; first takes precedence |
| `GEMINI_API_KEY` | No default; enables live voice by letting the server mint Gemini Live session tokens |
| `BILLY_GEMINI_LIVE_MODEL` | `gemini-3.8-live`; Live API model locked into each voice token |
| `BILLY_GEMINI_VOICE` | Empty (provider default); server-wide Gemini prebuilt voice such as `Sulafat`. A workspace's Settings choice, stored in its `state` table, overrides it |

The main model endpoint is configured in `agent.py` as `https://api.vultrinference.com/v1`. The current estimator hard-codes $0.75 input / $3 output per million tokens as implementation assumptions. Do not treat this table as current provider pricing. Revalidate estimator/model compatibility before changing models; the budget is not an account-wide billing guarantee.

No keys are needed for the regression suite. For a live model experiment, obtain an authorized test key out of band, set a small intentional budget, and use disposable company data. Relevant evidence and conversation text are sent to the configured model provider.

## Frontend development

The backend serves `site/` directly; edit ES modules and CSS, then reload a disposable browser tab. There is no npm install or build. Most behavior is composed in `site/app/workspace.js`. Changing the module query version in the importer prevents stale cached code. Preserve customer drafts before reloading live tabs.

Static-only preview on 8080 is useful for the pitch, but `/app/` on that port always calls loopback 8081. For isolated app testing on 8090, use the backend's own `/app/` route rather than the static 8080 preview.

## Daily workflow

Run focused tests for the changed area, then the full suite for cross-cutting agent/data changes. Use synthetic evidence and a mocked provider for orchestration tests; never trigger live customer Autopilot just to test a control. Inspect `git diff --check` and the staged file list. Keep unrelated changes and private files out of commits. A commit or GitHub push does not automatically deploy the VM or public site.
