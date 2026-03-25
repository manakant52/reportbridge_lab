# DNS Guide

Этот документ описывает развертывание внутреннего DNS для участников стенда на той же машине, где уже работает WireGuard.

Рекомендуемый стек:

- `dnsmasq`
- слушает на адресах `wg0`
- отдает домены `reportbridge.test`
- используется клиентами WireGuard как DNS-сервер

## 1. Когда это нужно

Если участники должны открывать:

- `www.reportbridge.test`
- `status.reportbridge.test`
- `api.reportbridge.test`
- `git.reportbridge.test`
- `ci.reportbridge.test`
- `secrets.reportbridge.test`

то удобнее не править `hosts`, а поднять внутренний DNS на VPN-хосте.

## 2. Установка

Для Debian/Ubuntu:

```bash
apt update
apt install -y dnsmasq
```

## 3. Определи адреса `wg0`

Проверка:

```bash
ip -4 addr show wg0
```

В текущей схеме проекта:

- `10.10.100.1/24`
- `10.10.110.1/24`

Если адреса отличаются, используй реальные адреса своего `wg0`.

## 4. Конфиг `dnsmasq`

Создай файл:

```bash
nano /etc/dnsmasq.d/reportbridge.conf
```

Содержимое:

```conf
interface=wg0
bind-interfaces

listen-address=10.10.100.1
listen-address=10.10.110.1

domain-needed
bogus-priv
no-resolv

server=1.1.1.1
server=8.8.8.8

address=/www.reportbridge.test/10.10.10.2
address=/status.reportbridge.test/10.10.10.2
address=/api.reportbridge.test/10.10.10.2
address=/git.reportbridge.test/10.10.10.2
address=/ci.reportbridge.test/10.10.10.2
address=/secrets.reportbridge.test/10.10.10.2
address=/grafana.reportbridge.test/10.10.30.10
```

Если все опубликованные web-сервисы идут через один `edge` reverse proxy, это нормально: несколько имен могут резолвиться в один и тот же IP.

Важно:

- не указывай `listen-address`, которого нет на хосте
- если, например, `10.10.101.1` не висит на `wg0`, `dnsmasq` не запустится

## 5. Открой DNS на firewall

Если DNS живет на этой же VPN-машине, то разреши доступ к порту `53` с `wg0`.

В `wg0.conf`:

```ini
PostUp = iptables -A INPUT -i wg0 -p udp --dport 53 -j ACCEPT
PostUp = iptables -A INPUT -i wg0 -p tcp --dport 53 -j ACCEPT

PostDown = iptables -D INPUT -i wg0 -p udp --dport 53 -j ACCEPT
PostDown = iptables -D INPUT -i wg0 -p tcp --dport 53 -j ACCEPT
```

Если правила уже применяются вручную, все равно лучше держать их в `wg0.conf`, чтобы они переживали restart интерфейса.

## 6. Запуск

```bash
systemctl restart dnsmasq
systemctl enable dnsmasq
systemctl status dnsmasq
```

## 7. Проверка

На сервере:

```bash
ss -luntp | grep :53
dig @10.10.100.1 www.reportbridge.test
dig @10.10.110.1 www.reportbridge.test
dig @10.10.100.1 status.reportbridge.test
```

Ожидается `NOERROR` и нужные внутренние IP в `ANSWER SECTION`.

## 8. Как выдать DNS клиентам WireGuard

В проекте поддерживается role-based DNS:

- `red` -> `WG_DNS_RED=10.10.100.1`
- `blue` -> `WG_DNS_BLUE=10.10.110.1`

Если код еще не обновлен, можно временно использовать единый:

- `WG_DNS=10.10.100.1`

Но правильнее именно разделение по ролям.

## 9. Podman env

В `env/web-vpn.env` для podman-версии:

```env
WG_DNS=1.1.1.1
WG_DNS_RED=10.10.100.1
WG_DNS_BLUE=10.10.110.1
```

После изменения env пересоздай контейнер:

```bash
cd /opt/web_vpn_podman
podman-compose down
podman-compose up -d --build
```

Проверка:

```bash
podman exec web-vpn-portal /bin/sh -lc 'printenv WG_DNS_RED; printenv WG_DNS_BLUE'
```

## 10. Как это сочетается с опубликованными сайтами

DNS решает только имя в IP.

Он не умеет хранить порт.

То есть запись:

```text
www.reportbridge.test -> 10.10.10.2
```

не означает:

```text
www.reportbridge.test -> 10.10.10.2:8085
```

Если сайт крутится в контейнере на `8085`, нужен внешний reverse proxy:

- `nginx` на хосте
- он слушает `80/443`
- проксирует `www.reportbridge.test` в `127.0.0.1:8085`

Только после этого участники смогут открывать сайт просто по имени без явного `:8085`.
