#!/usr/bin/env bash
set -euo pipefail

cd /opt/web_vpn_podman

cp env/web-vpn.env env/web-vpn.test.env
sed -i 's|^DB_PATH=.*|DB_PATH=/data/test-bot.db|' env/web-vpn.test.env
sed -i 's|^CONFIG_DIR=.*|CONFIG_DIR=/data/test-configs|' env/web-vpn.test.env
sed -i 's|^WG_CONFIG_PATH=.*|WG_CONFIG_PATH=/data/test-wg0.conf|' env/web-vpn.test.env
sed -i 's|^WG_MANAGED_PEERS_PATH=.*|WG_MANAGED_PEERS_PATH=/data/test-wg0-managed-peers.conf|' env/web-vpn.test.env
sed -i 's|^APPLY_CHANGES=.*|APPLY_CHANGES=false|' env/web-vpn.test.env
sed -i 's|^WEB_PORT=.*|WEB_PORT=8082|' env/web-vpn.test.env

cp data/bot.db data/test-bot.db
cp /etc/wireguard/wg0.conf data/test-wg0.conf
: > data/test-wg0-managed-peers.conf
mkdir -p data/test-configs

cat > compose.test.yaml <<'EOF'
services:
  web-vpn-portal:
    build:
      context: .
      dockerfile: ./Containerfile
    container_name: web-vpn-portal-test
    restart: always
    network_mode: host
    cap_add:
      - NET_ADMIN
      - NET_RAW
    security_opt:
      - label=disable
    env_file:
      - ./env/web-vpn.test.env
    volumes:
      - ./data:/data:Z
      - /etc/wireguard:/etc/wireguard:rw,rshared
EOF

cleanup() {
  podman-compose -f compose.test.yaml down >/dev/null 2>&1 || true
  podman rm -f web-vpn-portal-test >/dev/null 2>&1 || true
}
trap cleanup EXIT

podman rm -f web-vpn-portal-test >/dev/null 2>&1 || true
podman-compose -f compose.test.yaml up -d --build
sleep 3

echo -n "GET / => "
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8082/
echo -n "GET /admin => "
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8082/admin

invite_html="$(curl -sS -X POST -d 'password=_ZhuhL8yTU_6TvZleSSwzeZK&role=blue&uses=2' http://127.0.0.1:8082/admin/invite)"
invite="$(printf '%s' "$invite_html" | grep -oE 'BLUE-[A-Z0-9]+' | head -n1)"
if [[ -z "${invite}" ]]; then
  echo "Invite was not created" >&2
  exit 1
fi
echo "INVITE=${invite}"

redeem_html="$(curl -sS -X POST --data-urlencode 'display_name=podman-test-user' --data-urlencode "invite_code=${invite}" http://127.0.0.1:8082/redeem)"
printf '%s' "$redeem_html" | grep -q 'Конфигурация готова'
token="$(printf '%s' "$redeem_html" | grep -oE '/download\?token=[A-Za-z0-9_\-]+' | head -n1 | sed 's|/download?token=||')"
if [[ -z "${token}" ]]; then
  echo "Download token was not found" >&2
  exit 1
fi
echo "TOKEN=${token}"

echo -n "DOWNLOAD before restart => "
curl -sS -o /tmp/podman-test-download.conf -w '%{http_code}\n' "http://127.0.0.1:8082/download?token=${token}"
echo -n "CONFIG snippet => "
head -n 5 /tmp/podman-test-download.conf | tr '\n' '|' ; echo
echo -n "TEST CONFIG COUNT => "
find data/test-configs -maxdepth 1 -type f | wc -l
echo -n "MANAGED PEERS BYTES => "
wc -c < data/test-wg0-managed-peers.conf

podman-compose -f compose.test.yaml restart
sleep 3

echo -n "DOWNLOAD after restart => "
curl -sS -o /tmp/podman-test-download-2.conf -w '%{http_code}\n' "http://127.0.0.1:8082/download?token=${token}"
echo "CONTAINER STATUS =>"
podman ps --format 'table {{.Names}}\t{{.Status}}' | grep web-vpn-portal-test || true
echo "RECENT LOGS =>"
podman logs --tail 20 web-vpn-portal-test
