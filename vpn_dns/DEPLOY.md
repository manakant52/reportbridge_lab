# Deployment Guide

Этот документ описывает чистый деплой WireGuard Web Portal на новый сервер.

Результат:

- WireGuard работает на хосте
- веб-портал выдает клиентские конфиги
- роли `red` и `blue` применяются через один `wg0`
- приложение можно запускать либо напрямую через systemd, либо в отдельном podman-стеке в `/opt/web_vpn_podman`

## 1. Требования

Нужен Linux-сервер с:

- root-доступом
- публичным IP
- `systemd`
- `iptables`
- `python3`
- `python3-venv`
- `wireguard-tools`
- `podman` и `podman-compose`, если нужен контейнерный вариант
- `dnsmasq`, если домены лабораторки должны резолвиться у VPN-клиентов

Примеры пакетов для Debian/Ubuntu:

```bash
apt update
apt install -y python3 python3-venv python3-pip wireguard wireguard-tools iptables podman podman-compose qrencode dnsmasq
```

## 2. Подготовка каталогов

Вариант без контейнера:

```bash
mkdir -p /opt/tg_vpn_bot/tg_vpn_bot_project
mkdir -p /var/lib/vpn_tg_bot/tg_vpn_bot_project/configs
```

Вариант с podman:

```bash
mkdir -p /opt/web_vpn_podman
mkdir -p /opt/web_vpn_podman/data/configs
mkdir -p /opt/web_vpn_podman/env
```

## 3. Настройка WireGuard на хосте

Создай серверные ключи:

```bash
wg genkey | tee /etc/wireguard/server_private.key | wg pubkey | tee /etc/wireguard/server_public.key
chmod 600 /etc/wireguard/server_private.key
chmod 600 /etc/wireguard/server_public.key
```

Подготовь `/etc/wireguard/wg0.conf`:

```ini
[Interface]
Address = 10.10.100.1/24, 10.10.110.1/24
ListenPort = 51820
PrivateKey = REPLACE_SERVER_PRIVATE_KEY

PostUp = sysctl -w net.ipv4.ip_forward=1
PostUp = iptables -A FORWARD -s 10.10.100.0/24 -d 10.10.10.0/24 -i wg0 -j ACCEPT
PostUp = iptables -A FORWARD -s 10.10.100.0/24 -d 10.10.0.0/16 -i wg0 -j DROP
PostUp = iptables -A FORWARD -s 10.10.100.0/24 -i wg0 -j ACCEPT
PostUp = iptables -A FORWARD -s 10.10.110.0/24 -d 10.10.10.0/24 -i wg0 -j ACCEPT
PostUp = iptables -A FORWARD -s 10.10.110.0/24 -d 10.10.20.0/24 -i wg0 -j ACCEPT
PostUp = iptables -A FORWARD -s 10.10.110.0/24 -d 10.10.30.0/24 -i wg0 -j ACCEPT
PostUp = iptables -A FORWARD -s 10.10.110.0/24 -d 10.10.0.0/16 -i wg0 -j DROP
PostUp = iptables -A FORWARD -s 10.10.110.0/24 -i wg0 -j ACCEPT
PostUp = iptables -A FORWARD -o wg0 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
PostUp = iptables -t nat -A POSTROUTING -s 10.10.100.0/24 -o eth0 -j MASQUERADE
PostUp = iptables -t nat -A POSTROUTING -s 10.10.110.0/24 -o eth0 -j MASQUERADE
PostUp = iptables -A INPUT -i wg0 -p udp --dport 53 -j ACCEPT
PostUp = iptables -A INPUT -i wg0 -p tcp --dport 53 -j ACCEPT

PostDown = iptables -D FORWARD -s 10.10.100.0/24 -d 10.10.10.0/24 -i wg0 -j ACCEPT
PostDown = iptables -D FORWARD -s 10.10.100.0/24 -d 10.10.0.0/16 -i wg0 -j DROP
PostDown = iptables -D FORWARD -s 10.10.100.0/24 -i wg0 -j ACCEPT
PostDown = iptables -D FORWARD -s 10.10.110.0/24 -d 10.10.10.0/24 -i wg0 -j ACCEPT
PostDown = iptables -D FORWARD -s 10.10.110.0/24 -d 10.10.20.0/24 -i wg0 -j ACCEPT
PostDown = iptables -D FORWARD -s 10.10.110.0/24 -d 10.10.30.0/24 -i wg0 -j ACCEPT
PostDown = iptables -D FORWARD -s 10.10.110.0/24 -d 10.10.0.0/16 -i wg0 -j DROP
PostDown = iptables -D FORWARD -s 10.10.110.0/24 -i wg0 -j ACCEPT
PostDown = iptables -D FORWARD -o wg0 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
PostDown = iptables -t nat -D POSTROUTING -s 10.10.100.0/24 -o eth0 -j MASQUERADE
PostDown = iptables -t nat -D POSTROUTING -s 10.10.110.0/24 -o eth0 -j MASQUERADE
PostDown = iptables -D INPUT -i wg0 -p udp --dport 53 -j ACCEPT
PostDown = iptables -D INPUT -i wg0 -p tcp --dport 53 -j ACCEPT

# BEGIN TG VPN MANAGED PEERS
# END TG VPN MANAGED PEERS
```

Подними интерфейс:

```bash
systemctl enable --now wg-quick@wg0
wg show wg0
```

## 4. Включение IP forwarding

Создай `/etc/sysctl.d/99-wireguard-forward.conf`:

```conf
net.ipv4.ip_forward=1
```

Применить:

```bash
sysctl --system
```

Проверка:

```bash
sysctl net.ipv4.ip_forward
```

Ожидается `net.ipv4.ip_forward = 1`.

## 5. Деплой приложения без контейнера

Скопируй проект в `/opt/tg_vpn_bot/tg_vpn_bot_project`.

Создай виртуальное окружение:

```bash
cd /opt/tg_vpn_bot/tg_vpn_bot_project
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Создай `.env`:

```env
DB_PATH=/var/lib/vpn_tg_bot/tg_vpn_bot_project/bot.db
CONFIG_DIR=/var/lib/vpn_tg_bot/tg_vpn_bot_project/configs
WG_INTERFACE=wg0
WG_CONFIG_PATH=/etc/wireguard/wg0.conf
WG_MANAGED_PEERS_PATH=/etc/wireguard/wg0-managed-peers.conf
WG_SERVER_PUBLIC_KEY=REPLACE_SERVER_PUBLIC_KEY
WG_ENDPOINT=SERVER_PUBLIC_IP:51820
WG_DNS=1.1.1.1
WG_DNS_RED=10.10.100.1
WG_DNS_BLUE=10.10.110.1
WG_ALLOWED_IPS_RED=0.0.0.0/0
WG_ALLOWED_IPS_BLUE=0.0.0.0/0
WG_CLIENT_IP_NETWORK_RED=10.10.100.0/24
WG_CLIENT_IP_START_RED=102
WG_CLIENT_IP_END_RED=220
WG_CLIENT_IP_NETWORK_BLUE=10.10.110.0/24
WG_CLIENT_IP_START_BLUE=102
WG_CLIENT_IP_END_BLUE=220
APPLY_CHANGES=true
DEFAULT_INVITE_USES=10
WEB_HOST=0.0.0.0
WEB_PORT=8080
WEB_TITLE=Портал доступа WireGuard
WEB_ADMIN_PASSWORD=CHANGE_ME
```

Установи systemd unit:

```bash
cp systemd.service /etc/systemd/system/tg-vpn-bot.service
systemctl daemon-reload
systemctl enable --now tg-vpn-bot.service
```

Проверка:

```bash
systemctl status tg-vpn-bot.service
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/
```

## 6. Деплой в podman

Этот проект можно запустить контейнером, но WireGuard все равно остается на хосте.

Причина:

- интерфейс `wg0` существует на хосте
- контейнер должен иметь доступ к `wg` и `wg-quick`
- контейнер должен иметь доступ к `/etc/wireguard`
- контейнер должен работать в `--network host`
- контейнер должен иметь `NET_ADMIN`

Используй отдельный каталог:

```bash
/opt/web_vpn_podman
```

Туда копируются файлы из каталога `podman/`.

Дальше:

```bash
cd /opt/web_vpn_podman
cp env/web-vpn.env.example env/web-vpn.env
```

Заполни `env/web-vpn.env`, затем:

```bash
podman-compose up -d --build
podman ps
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8081/
```

Если нужен автозапуск через systemd:

```bash
cp systemd/web-vpn-podman.service /etc/systemd/system/web-vpn-podman.service
systemctl daemon-reload
systemctl enable --now web-vpn-podman.service
```

## 7. Что проверить после деплоя

Проверки уровня приложения:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/admin
```

Важно: не используй `curl -I` для health-check этого приложения. `HEAD` сейчас не обрабатывается и вернет `404`, даже если обычный `GET` работает корректно.

Проверки WireGuard:

```bash
wg show wg0
ip a show wg0
ip route | grep 10.10.
```

Проверки firewall:

```bash
iptables -S FORWARD
iptables -t nat -S POSTROUTING
```

## 8. Проверка ролей

`red`:

- получает адрес из `10.10.100.0/24`
- должен иметь доступ только к `10.10.10.0/24` из внутренних сегментов
- должен иметь интернет

`blue`:

- получает адрес из `10.10.110.0/24`
- должен иметь доступ к `10.10.10.0/24`
- должен иметь доступ к `10.10.20.0/24`
- должен иметь доступ к `10.10.30.0/24`
- должен иметь интернет

## 8. Внутренний DNS для участников

Если участники должны открывать имена вида `www.reportbridge.test` и `status.reportbridge.test`, проще всего поднять `dnsmasq` на том же VPN-хосте.

Минимальная схема:

- `listen-address=10.10.100.1`
- `listen-address=10.10.110.1`
- `red` клиенты получают `DNS = 10.10.100.1`
- `blue` клиенты получают `DNS = 10.10.110.1`

Подробная инструкция вынесена в `DNS.md`.

## 9. Обновление

Без контейнера:

```bash
cd /opt/tg_vpn_bot/tg_vpn_bot_project
cp -r NEW_FILES/* .
. .venv/bin/activate
pip install -r requirements.txt
systemctl restart tg-vpn-bot.service
```

С podman:

```bash
cd /opt/web_vpn_podman
podman-compose down
podman-compose up -d --build
```

## 10. Откат

Откат без контейнера:

```bash
systemctl stop tg-vpn-bot.service
cp /etc/wireguard/wg0.conf.bak.TIMESTAMP /etc/wireguard/wg0.conf
systemctl restart wg-quick@wg0
```

Откат podman-варианта:

```bash
systemctl stop web-vpn-podman.service
podman-compose down
```
