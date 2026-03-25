#!/usr/bin/env bash
set -euo pipefail

cd /opt/web_vpn_podman

cleanup() {
  podman-compose -f compose.test.yaml down >/dev/null 2>&1 || true
  podman rm -f web-vpn-portal-test >/dev/null 2>&1 || true
}
trap cleanup EXIT

podman rm -f web-vpn-portal-test >/dev/null 2>&1 || true
podman-compose -f compose.test.yaml up -d
sleep 3

echo "ROOT=$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8082/)"
echo "ADMIN=$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8082/admin)"

curl -sS -X POST -d 'password=_ZhuhL8yTU_6TvZleSSwzeZK&role=blue&uses=2' http://127.0.0.1:8082/admin/invite > /tmp/podman-invite.html
echo "INVITE_MATCHES:"
grep -oE 'BLUE-[A-Z0-9]{10}' /tmp/podman-invite.html | head || true
echo "HTML_HEAD:"
head -n 60 /tmp/podman-invite.html
