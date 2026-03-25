# Workspace Layout

Основной локальный workspace проекта:

- `vpn_dns/` — WireGuard-портал, podman-стек, конфиги и документация по DNS
- `site/` — корпоративный сайт `ReportBridge` и его контейнерный `nginx:alpine` стек

Текущая логика:

- дальнейшую работу по VPN, ролям, podman и внутреннему DNS вести в `vpn_dns/`
- дальнейшую работу по публичному сайту и фронтенду вести в `site/`

## Структура

```text
remote_tg_vpn_bot/
├── vpn_dns/
│   ├── app.py
│   ├── .env.example
│   ├── README.md
│   ├── DEPLOY.md
│   ├── OPERATIONS.md
│   ├── DNS.md
│   ├── requirements.txt
│   ├── systemd.service
│   ├── wg0.conf
│   ├── 99-wireguard-forward.conf
│   └── podman/
│       ├── Containerfile
│       ├── compose.yaml
│       ├── entrypoint.sh
│       ├── deploy.sh
│       ├── debug_podman_invite.sh
│       ├── test_podman_isolated.sh
│       ├── env/
│       │   └── web-vpn.env.example
│       └── systemd/
│           └── web-vpn-podman.service
├── site/
│   ├── index.html
│   ├── platform.html
│   ├── security.html
│   ├── careers.html
│   ├── styles.css
│   ├── script.js
│   ├── build_exercise_pdf.py
│   ├── Containerfile
│   ├── compose.yaml
│   ├── README.md
│   ├── nginx/
│   │   └── default.conf
│   └── assets/
│       └── DevOps_Migration_Exercise.pdf
└── ...
```

## Примечание

Старые файлы в корне `remote_tg_vpn_bot/` пока оставлены, чтобы ничего не ломать задним числом.
Рабочими каталогами для следующего этапа считай:

- `vpn_dns/`
- `site/`
