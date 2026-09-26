#!/bin/sh
# Private single-owner service; expose through a local SSH tunnel until authenticated ingress is configured.
set -eu
cd "$(dirname "$0")/.."
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv
id billy >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/billy --shell /usr/sbin/nologin billy
python3 -m venv /opt/rfp-agent/.venv
/opt/rfp-agent/.venv/bin/pip install -r app/requirements.txt
/opt/rfp-agent/.venv/bin/python -m playwright install-deps chromium
install -d -m 700 -o billy -g billy /var/lib/billy/workspace
PLAYWRIGHT_BROWSERS_PATH=/opt/billy-browsers /opt/rfp-agent/.venv/bin/python -m playwright install chromium
chown -R root:root /opt/billy-browsers
chmod -R go-w /opt/billy-browsers
if command -v apparmor_parser >/dev/null 2>&1; then
    install -m 644 deploy/billy-browser.apparmor /etc/apparmor.d/billy-browser
    apparmor_parser -r /etc/apparmor.d/billy-browser
fi
cat > /etc/systemd/system/billy.service <<'EOF'
[Unit]
Description=Billy private research workspace
After=network-online.target
Wants=network-online.target
[Service]
User=billy
Group=billy
WorkingDirectory=/opt/rfp-agent
Environment=BILLY_DATA_DIR=/var/lib/billy/workspace
Environment=BILLY_SOURCES=/var/lib/billy/rfp-sources.json
Environment="BILLY_ENVIRONMENT=Vultr · Silicon Valley"
Environment=PYTHONUNBUFFERED=1
Environment=PLAYWRIGHT_BROWSERS_PATH=/opt/billy-browsers
ExecStart=/opt/rfp-agent/.venv/bin/uvicorn app.server:app --host 127.0.0.1 --port 8787
Restart=on-failure
RestartSec=3
UMask=0077
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now billy
