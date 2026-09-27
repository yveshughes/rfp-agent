# Operations, deployment and recovery

This runbook describes the private single-owner deployment. Get the actual host, authorized login and credentials from the owner through a secure channel. No host passwords, keys or customer data belong in this repository. Commands below are operator instructions, not an unattended deployment script.

## Deployment inventory

| Item | Deployed convention |
|---|---|
| Checkout | `/opt/rfp-agent` |
| Backend service | `billy.service`, non-root user/group `billy` |
| Private listener | `127.0.0.1:8787`, one Uvicorn process |
| Runtime data | `/var/lib/billy/workspace` |
| Private source directory | `/var/lib/billy/rfp-sources.json` |
| Inference environment | `/etc/billy/inference.env`, root-owned mode 600 |
| Browser binaries | `/opt/billy-browsers`, root-owned, not writable by `billy` |
| Public static root | `/var/www/rfp-agent`, nginx port 80 |
| Local demo access | SSH forward `127.0.0.1:8081 → server 127.0.0.1:8787` |

The public app HTML does not grant access to the private API. Keep that API off public nginx. The installers do not provide HTTPS, accounts, NetBird, off-VM backups or automatic Git deployment.

## First installation

Place the repository at `/opt/rfp-agent` before running the app installer; that path is hard-coded. On the Ubuntu/Debian VM:

```sh
cd /opt/rfp-agent
sudo sh deploy/install-app.sh
# Only when publishing the separate public pitch:
# sudo sh deploy/install.sh
```

The app installer installs Python dependencies, Chromium, Poppler and Tesseract; creates the service account/data directory; and enables the service. It uses system Python, so validate its version against dependencies. Running the installer on an already-running service does not replace the explicit restart/upgrade procedure below.

Create `/etc/billy` with restricted permissions and provide `inference.env` through the owner’s secret-management workflow. Configure the variables listed in [development](development.md). The service's environment file is optional: manual features start without a model key. Copy authorized source data to its private path with read access for `billy`; do not put it in the web root.

After provisioning the environment/source file, run `sudo systemctl restart billy` and verify `/api/agent` configuration and `/api/sources` count through the private connection. Both environment and source directory are loaded at process startup.

`deploy/billy-browser.apparmor` names an exact Chromium headless-shell revision. Compare it to the installed binary whenever Playwright changes. Keep the Chromium sandbox enabled; do not disable global namespace restrictions as a shortcut.

## Private access and tunnel recovery

For an authorized account with local-forwarding permission:

```sh
ssh -NT -L 127.0.0.1:8081:127.0.0.1:8787 \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
  AUTHORIZED_USER@YOUR_SERVER
```

Open `http://localhost:8081/app/`. SSH keepalives detect broken connections; this foreground command does **not** reconnect by itself. Do not start it if a background service already owns 8081. A disconnected Vultr web console does not necessarily mean the VM, app or SSH tunnel stopped.

The existing demo Mac uses an owner-approved launchd service named `com.rfpagent.demo-tunnel` with KeepAlive, a dedicated SSH key, strict host-key checking, and a forwarding-only server account restricted to `127.0.0.1:8787`. Its host-specific plist/key are outside Git. A new engineer needs a separately authorized account/key, not a copied private key. Recreating this service requires that explicit access provisioning step; do not weaken SSH restrictions to bypass it.

On the Mac where that service is installed:

```sh
launchctl print "gui/$(id -u)/com.rfpagent.demo-tunnel"
lsof -nP -iTCP:8081 -sTCP:LISTEN
# If the service is installed but its connection needs restarting:
launchctl kickstart -k "gui/$(id -u)/com.rfpagent.demo-tunnel"
curl --fail http://localhost:8081/w/default/api/agent
```

Inspect `~/Library/Logs/rfp-demo-tunnel.log` locally for host-key/authentication errors; do not paste credentials or unrestricted logs into shared documents. Keep the demo Mac awake using `caffeinate` during the demo if necessary. Launchd cannot keep a sleeping/disconnected laptop reachable; jobs themselves continue on the VM.

## Safe application update

1. Run the relevant tests and review the staged files. Commit only the intended changes. Record both current and target commit IDs.
2. Read `/api/workspaces` and each company's `/w/<id>/api/agent` and `/state`. Wait for work to finish or arrange a pause before a restart. A browser job can be active even when the model is idle.
3. Back up databases **and files** before schema/data changes. Keep originals and existing drafts intact.
4. Transfer the reviewed commit via the normal remote or a private Git bundle. Check a clean server working tree; use `git merge --ff-only`. Do not `git reset --hard` over unexplained server changes.
5. If dependencies changed, use the idle maintenance window to stop the service and run `/opt/rfp-agent/.venv/bin/pip install -r app/requirements.txt` from the checkout. If Playwright changed, also run `/opt/rfp-agent/.venv/bin/python -m playwright install-deps chromium` and `PLAYWRIGHT_BROWSERS_PATH=/opt/billy-browsers /opt/rfp-agent/.venv/bin/python -m playwright install chromium` as the administrator. Preserve root ownership/non-service-writable browser files, update the exact AppArmor binary path, and reload that profile before starting. Validate these changes in staging first.
6. Restart `billy` only for backend/dependency changes, after the idle check. Static app assets are served from the checkout; a frontend-only update does not need a backend restart. Explicitly update the public static copy if that is in scope.
7. Verify service state, scoped API responses, assets and a read-only browser workflow. Do not launch customer work merely for deployment QA. Existing interrupted agent runs need Continue when authorized.

Example diagnostics on the server:

```sh
sudo systemctl status billy --no-pager
sudo journalctl -u billy -n 80 --no-pager
git -C /opt/rfp-agent rev-parse --short HEAD
curl --fail http://127.0.0.1:8787/w/default/api/agent
```

A GitHub push does not update either server checkout or nginx's static copy. A private bundle must include only committed code/docs, not runtime data. Public static updates copy only `site/`; never serve the repository root.

## Backup and restore

There is no scheduled off-VM backup in the application. Existing on-VM pre-change backups are useful rollback points but do not protect against VM loss. Establish an authorized encrypted off-VM destination and retention policy before production use.

For a coherent complete backup, arrange an idle window and stop the service, then archive the whole workspace tree. Include the private source file separately if permitted; retain service configuration and credentials in their proper secure store. Example on the VM:

```sh
sudo systemctl stop billy
backup_dir="/var/lib/billy/backups/$(date -u +%Y%m%dT%H%M%SZ)"
sudo install -d -m 700 "$backup_dir"
sudo tar -C /var/lib/billy -czf "$backup_dir/workspace.tar.gz" workspace
sudo chmod 600 "$backup_dir/workspace.tar.gz"
sudo systemctl start billy
```

If an archive step fails, resolve it and restart the service; this command sequence is not an automatic error-recovery script. For an online database-only snapshot, use SQLite's backup API, not a raw copy of an active database. Database-only snapshots do not include originals/PDFs and are insufficient for disaster recovery.

Restore to a **new staging directory first**, extract the archive, run `PRAGMA integrity_check` on every SQLite file, and check original/generated files referenced by the databases. Test the staged data in a separate local environment with model credentials disabled. Only then arrange a service stop and swap the validated data directory, keeping the old one for rollback and restoring ownership to `billy:billy`. Verify every company, attachments, drafts and PDFs before resuming jobs. Do not restore production data into public paths or commit it to Git.

Code rollback is not schema rollback. Additive schema changes may tolerate older code, but verify the specific revision against a staged database first. Restore matched data only when required and authorized; never discard newer customer work automatically.

## Troubleshooting

| Symptom | Check / response |
|---|---|
| Local page refuses connection | Listener on 8081, launchd/SSH logs, server service; avoid competing tunnels |
| Page loads but API rejects requests | Correct host/origin/port and `X-Billy-Client` for writes; workspace prefix; stale static 8080 app pointing at wrong backend |
| Billy idle/disconnected | `/agent` config/status and `/state`; distinguish no job, missing model config, browser handoff and network failure |
| Autopilot stopped | Read `error`, `blocked_reason`, queue items and recent tool results; no matches is different from model/budget failure |
| Service restarted during work | Run becomes interrupted; Continue retains evidence, selection and queue; watchers restart independently |
| PDF exists but old version | Read section versions/title and `/review`; edit → regenerate; don't relabel an old PDF current |
| Review progress shows 0% with a draft | It measures human checklist review, not whether the draft was written |
| Missing thumbnail/OCR | Poppler/Tesseract installed and executable; extraction note; unsupported file versus failed original; no fake preview fallback |
| Source 403/partial or no RFP matches | Actual source evidence, watch scans, profile completeness, availability/deadline; never report blocked sources as checked |
| Browser won't launch | Pinned Playwright binary, OS libraries, AppArmor revision, ownership and sandbox; no `--no-sandbox` workaround |
| Too many open files | Use `ClosingConnection` context factories; inspect descriptors and browser tasks; restarting alone does not fix a leak |
| Inference budget exhausted | Shared default-ledger totals/reservations; inspect before authorizing a new limit; don't delete usage to bypass it |
| Data seems to belong to another company | Stop mutations; check scoped API/resource URLs and runtime binding; do not “fix” by moving customer records |

Logs, prompts and tool results can contain company evidence. Redact before sharing. The app has no log rotation, retention policy or customer-data erasure workflow of its own; these need explicit operational design.
