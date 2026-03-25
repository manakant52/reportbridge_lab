# ReportBridge Site

Отдельный статический прототип корпоративного сайта под легенду полигона `ReportBridge`.

Что внутри:

- `index.html` — главная
- `platform.html` — описание платформы
- `security.html` — Trust Center
- `careers.html` — вакансии и ссылка на PDF из первого шага walkthrough
- `styles.css` — общий стиль
- `script.js` — ASCII-анимация фона
- `Containerfile` — контейнер на `nginx:alpine`
- `compose.yaml` — podman/docker compose для сайта
- `nginx/default.conf` — конфиг виртуального хоста

Быстрый локальный запуск:

```bash
cd /home/manakant/reportbridge_site
python3 -m http.server 8090
```

После этого сайт будет доступен на:

```text
http://127.0.0.1:8090
```

## Запуск в контейнере

Сборка и запуск:

```bash
cd /home/manakant/reportbridge_site
podman-compose up -d --build
```

Проверка:

```bash
curl -H 'Host: www.reportbridge.test' http://127.0.0.1:8085/
```

Сайт внутри контейнера слушает `80`, наружу по compose проброшен `8085`.

Если перед ним будет внешний `nginx`, то он должен проксировать домен:

```text
www.reportbridge.test -> 127.0.0.1:8085
```
