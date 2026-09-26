#!/bin/sh
# Run on a fresh Ubuntu/Debian Vultr VM as root from the checked-out repo.
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run as root.' >&2; exit 1; }
cd "$(dirname "$0")/.."
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y nginx
install -d -m 755 /var/www/rfp-agent
cp -R site/. /var/www/rfp-agent/
chmod -R a+rX /var/www/rfp-agent
install -m 644 deploy/nginx.conf /etc/nginx/sites-available/rfp-agent
ln -sfn /etc/nginx/sites-available/rfp-agent /etc/nginx/sites-enabled/default
nginx -t
systemctl enable nginx
systemctl restart nginx
