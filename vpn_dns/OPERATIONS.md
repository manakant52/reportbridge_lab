# Operations Guide

Этот документ нужен для повседневного сопровождения сервиса после деплоя.

## Основные пути

- код без контейнера: `/opt/tg_vpn_bot/tg_vpn_bot_project`
- podman-стек: `/opt/web_vpn_podman`
- база данных: `/var/lib/vpn_tg_bot/tg_vpn_bot_project/bot.db`
- клиентские конфиги: `/var/lib/vpn_tg_bot/tg_vpn_bot_project/configs`
- WireGuard: `/etc/wireguard/wg0.conf`
- managed peers: `/etc/wireguard/wg0-managed-peers.conf`
- DNS конфиг: `/etc/dnsmasq.d/reportbridge.conf`

## Сервисы

Без контейнера:

```bash
systemctl status tg-vpn-bot.service
journalctl -u tg-vpn-bot.service -n 100 --no-pager
systemctl restart tg-vpn-bot.service
```

С podman:

```bash
systemctl status web-vpn-podman.service
journalctl -u web-vpn-podman.service -n 100 --no-pager
podman ps
podman logs web-vpn-portal
```

## Частые проверки

Проверить интерфейс:

```bash
wg show wg0
ip a show wg0
```

Проверить маршруты:

```bash
ip route | grep 10.10.
```

Проверить firewall:

```bash
iptables -S FORWARD
iptables -t nat -S POSTROUTING
```

Проверить DNS:

```bash
systemctl status dnsmasq
ss -luntp | grep :53
dig @10.10.100.1 www.reportbridge.test
dig @10.10.110.1 www.reportbridge.test
```

Проверить, что `red` заблокирован к локалке:

```bash
iptables -S FORWARD | grep 10.10.100.0/24
```

Проверить, что `blue` разрешен:

```bash
iptables -S FORWARD | grep 10.10.110.0/24
```

## Бэкапы

Минимум нужно сохранять:

- `.env`
- `wg0.conf`
- `bot.db`

Пример:

```bash
cp /etc/wireguard/wg0.conf /etc/wireguard/wg0.conf.bak.$(date +%Y%m%d%H%M%S)
cp /opt/tg_vpn_bot/tg_vpn_bot_project/.env /opt/tg_vpn_bot/tg_vpn_bot_project/.env.bak.$(date +%Y%m%d%H%M%S)
cp /var/lib/vpn_tg_bot/tg_vpn_bot_project/bot.db /var/lib/vpn_tg_bot/tg_vpn_bot_project/bot.db.bak.$(date +%Y%m%d%H%M%S)
```

## Обновление конфигурации

После изменения `.env`:

Без контейнера:

```bash
systemctl restart tg-vpn-bot.service
```

С podman:

```bash
cd /opt/web_vpn_podman
podman-compose up -d --build
```

После ручного изменения `wg0.conf`:

```bash
systemctl restart wg-quick@wg0
wg show wg0
```

Для проверки веба используй обычный `GET`, а не `HEAD`:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/
```

`curl -I` здесь не подходит, потому что приложение не обслуживает `HEAD`.

## Типовые проблемы

### Есть handshake, но нет интернета

Проверь:

- `net.ipv4.ip_forward = 1`
- есть `MASQUERADE`
- есть `FORWARD ACCEPT`

Команды:

```bash
sysctl net.ipv4.ip_forward
iptables -t nat -S POSTROUTING
iptables -S FORWARD
```

### `blue` не ходит в локалку

Проверь, что на `wg0` есть оба адреса:

```bash
ip a show wg0
```

Должно быть:

- `10.10.100.1/24`
- `10.10.110.1/24`

Проверь также правила:

```bash
iptables -S FORWARD | grep 10.10.110.0/24
```

### Ошибка с IP в БД

Если появляется `UNIQUE constraint failed: peers.vpn_ip`, значит схема БД не мигрирована или миграция откатилась.

Проверь индекс:

```bash
sqlite3 /var/lib/vpn_tg_bot/tg_vpn_bot_project/bot.db ".schema peers"
sqlite3 /var/lib/vpn_tg_bot/tg_vpn_bot_project/bot.db "PRAGMA index_list(peers);"
```

Ожидается частичный индекс для активных peer'ов, а не глобальный inline `UNIQUE`.

### Приложение выдает конфиг, но peer не появляется в `wg show`

Проверь:

- `APPLY_CHANGES=true`
- контейнер или сервис видит `wg` и `wg-quick`
- есть доступ к `/etc/wireguard/wg0.conf`

Проверки:

```bash
which wg
which wg-quick
grep APPLY_CHANGES /opt/tg_vpn_bot/tg_vpn_bot_project/.env
```

### Домены `reportbridge.test` не резолвятся у клиентов

Проверь:

- `dnsmasq` активен
- он слушает на `10.10.100.1` и/или `10.10.110.1`
- в клиентском конфиге выдан правильный `DNS`

Команды:

```bash
systemctl status dnsmasq
ss -luntp | grep :53
dig @10.10.100.1 www.reportbridge.test
dig @10.10.110.1 www.reportbridge.test
podman exec web-vpn-portal /bin/sh -lc 'printenv WG_DNS_RED; printenv WG_DNS_BLUE'
```

## Роли и политика доступа

`red`:

- пул `10.10.100.0/24`
- интернет разрешен
- из внутренних сетей разрешен только `10.10.10.0/24`
- DNS для новых конфигов: `10.10.100.1`

`blue`:

- пул `10.10.110.0/24`
- интернет разрешен
- разрешены `10.10.10.0/24`, `10.10.20.0/24`, `10.10.30.0/24`
- DNS для новых конфигов: `10.10.110.1`

Важно: ограничения делаются на сервере через firewall, а не только через клиентский `AllowedIPs`.

## Что менять осторожно

Не трогай без понимания:

- `WG_INTERFACE`
- `WG_CONFIG_PATH`
- `WG_MANAGED_PEERS_PATH`
- `APPLY_CHANGES`
- подсети `red` и `blue`, если уже есть выданные конфиги

Если надо менять подсети, лучше:

1. остановить выдачу
2. отозвать старые peer'ы
3. изменить `wg0.conf`, `.env` и правила firewall
4. поднять сервис заново
