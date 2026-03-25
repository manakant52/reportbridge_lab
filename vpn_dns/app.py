import base64
import hmac
import html
import io
import ipaddress
import os
import secrets
import sqlite3
import subprocess
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

import qrcode

DB_PATH = Path(os.getenv("DB_PATH", "/var/lib/vpn_tg_bot/bot.db"))
CONFIG_DIR = Path(os.getenv("CONFIG_DIR", "/var/lib/vpn_tg_bot/configs"))
WG_INTERFACE = os.getenv("WG_INTERFACE", "wg0")
WG_CONFIG_PATH = Path(os.getenv("WG_CONFIG_PATH", "/etc/wireguard/wg0.conf"))
WG_MANAGED_PEERS_PATH = Path(os.getenv("WG_MANAGED_PEERS_PATH", "/etc/wireguard/wg0-managed-peers.conf"))
WG_SERVER_PUBLIC_KEY = os.getenv("WG_SERVER_PUBLIC_KEY", "")
WG_ENDPOINT = os.getenv("WG_ENDPOINT", "vpn.example.com:51820")
WG_DNS = os.getenv("WG_DNS", "1.1.1.1")
WG_DNS_RED = os.getenv("WG_DNS_RED", WG_DNS)
WG_DNS_BLUE = os.getenv("WG_DNS_BLUE", WG_DNS)
WG_ALLOWED_IPS_RED = os.getenv("WG_ALLOWED_IPS_RED", "0.0.0.0/0")
WG_ALLOWED_IPS_BLUE = os.getenv("WG_ALLOWED_IPS_BLUE", "0.0.0.0/0")
WG_CLIENT_IP_NETWORK_RED = os.getenv("WG_CLIENT_IP_NETWORK_RED", "10.10.100.0/24")
WG_CLIENT_IP_START_RED = int(os.getenv("WG_CLIENT_IP_START_RED", "101"))
WG_CLIENT_IP_END_RED = int(os.getenv("WG_CLIENT_IP_END_RED", "220"))
WG_CLIENT_IP_NETWORK_BLUE = os.getenv("WG_CLIENT_IP_NETWORK_BLUE", "10.10.110.0/24")
WG_CLIENT_IP_START_BLUE = int(os.getenv("WG_CLIENT_IP_START_BLUE", "101"))
WG_CLIENT_IP_END_BLUE = int(os.getenv("WG_CLIENT_IP_END_BLUE", "220"))
APPLY_CHANGES = os.getenv("APPLY_CHANGES", "false").lower() == "true"
DEFAULT_INVITE_USES = int(os.getenv("DEFAULT_INVITE_USES", "1"))
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))
WEB_ADMIN_PASSWORD = os.getenv("WEB_ADMIN_PASSWORD", "")
WEB_TITLE = os.getenv("WEB_TITLE", "Портал доступа WireGuard")
DOWNLOAD_TOKEN_BYTES = 24


def ensure_dirs() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    WG_MANAGED_PEERS_PATH.parent.mkdir(parents=True, exist_ok=True)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def html_escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, ddl: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")}
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")


def peers_table_has_inline_vpn_unique(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='peers'"
    ).fetchone()
    if not row or not row[0]:
        return False
    normalized_sql = row[0].upper().replace("\n", " ")
    return "VPN_IP TEXT UNIQUE" in normalized_sql


def migrate_peers_table(conn: sqlite3.Connection) -> None:
    if not peers_table_has_inline_vpn_unique(conn):
        return
    conn.execute("DROP INDEX IF EXISTS idx_peers_active_vpn_ip")
    conn.execute(
        """
        CREATE TABLE peers_new (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            display_name TEXT,
            role TEXT NOT NULL DEFAULT 'red',
            vpn_ip TEXT NOT NULL,
            public_key TEXT NOT NULL,
            private_key TEXT NOT NULL,
            preshared_key TEXT NOT NULL,
            invite_code TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            revoked_at TEXT,
            access_token TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO peers_new (
            telegram_id, username, display_name, role, vpn_ip, public_key, private_key,
            preshared_key, invite_code, status, created_at, updated_at, revoked_at, access_token
        )
        SELECT
            telegram_id, username, display_name, role, vpn_ip, public_key, private_key,
            preshared_key, invite_code, status, created_at, updated_at, revoked_at, access_token
        FROM peers
        """
    )
    conn.execute("DROP TABLE peers")
    conn.execute("ALTER TABLE peers_new RENAME TO peers")


def init_db() -> None:
    ensure_dirs()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS invites (
                code TEXT PRIMARY KEY,
                role TEXT NOT NULL DEFAULT 'red',
                max_uses INTEGER NOT NULL DEFAULT 1,
                used_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                created_by TEXT,
                expires_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS peers (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                display_name TEXT,
                role TEXT NOT NULL DEFAULT 'red',
                vpn_ip TEXT NOT NULL,
                public_key TEXT NOT NULL,
                private_key TEXT NOT NULL,
                preshared_key TEXT NOT NULL,
                invite_code TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                revoked_at TEXT
            )
            """
        )
        ensure_column(conn, "peers", "access_token", "TEXT")
        migrate_peers_table(conn)
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_peers_access_token ON peers(access_token)")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_peers_active_vpn_ip ON peers(vpn_ip) WHERE status='active'"
        )
        conn.commit()


@contextmanager
def db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def run_wg(cmd: list[str], input_text: Optional[str] = None) -> str:
    result = subprocess.run(
        cmd,
        input=input_text,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def generate_private_key() -> str:
    return run_wg(["wg", "genkey"])


def generate_public_key(private_key: str) -> str:
    return run_wg(["wg", "pubkey"], input_text=private_key)


def generate_psk() -> str:
    return run_wg(["wg", "genpsk"])


def get_role_settings(role: str) -> dict[str, object]:
    if role == "blue":
        return {
            "dns": WG_DNS_BLUE,
            "allowed_ips": WG_ALLOWED_IPS_BLUE,
            "network": WG_CLIENT_IP_NETWORK_BLUE,
            "start": WG_CLIENT_IP_START_BLUE,
            "end": WG_CLIENT_IP_END_BLUE,
        }
    return {
        "dns": WG_DNS_RED,
        "allowed_ips": WG_ALLOWED_IPS_RED,
        "network": WG_CLIENT_IP_NETWORK_RED,
        "start": WG_CLIENT_IP_START_RED,
        "end": WG_CLIENT_IP_END_RED,
    }


def allocate_ip(conn: sqlite3.Connection, role: str) -> str:
    settings = get_role_settings(role)
    network = ipaddress.ip_network(str(settings["network"]), strict=False)
    used = {row[0] for row in conn.execute("SELECT vpn_ip FROM peers WHERE status='active'").fetchall()}
    for host in range(int(settings["start"]), int(settings["end"]) + 1):
        candidate = str(network.network_address + host)
        if candidate not in used:
            return candidate
    raise RuntimeError("В пуле больше нет свободных IP-адресов")


def render_client_config(private_key: str, address: str, preshared_key: str, role: str) -> str:
    if not WG_SERVER_PUBLIC_KEY:
        raise RuntimeError("Не задан WG_SERVER_PUBLIC_KEY")
    settings = get_role_settings(role)
    allowed_ips = str(settings["allowed_ips"])
    dns = str(settings["dns"])
    return (
        "[Interface]\n"
        f"PrivateKey = {private_key}\n"
        f"Address = {address}/32\n"
        f"DNS = {dns}\n\n"
        "[Peer]\n"
        f"PublicKey = {WG_SERVER_PUBLIC_KEY}\n"
        f"PresharedKey = {preshared_key}\n"
        f"AllowedIPs = {allowed_ips}\n"
        f"Endpoint = {WG_ENDPOINT}\n"
        "PersistentKeepalive = 25\n"
    )


def write_client_config(peer_id: int, config_text: str) -> Path:
    path = CONFIG_DIR / f"{peer_id}.conf"
    path.write_text(config_text, encoding="utf-8")
    return path


def render_peer_block(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        "SELECT public_key, preshared_key, vpn_ip, display_name, telegram_id FROM peers WHERE status='active' ORDER BY vpn_ip"
    ).fetchall()
    lines = ["# BEGIN TG VPN MANAGED PEERS"]
    for row in rows:
        lines.extend(
            [
                f"# {row['display_name']} ({row['telegram_id']})",
                "[Peer]",
                f"PublicKey = {row['public_key']}",
                f"PresharedKey = {row['preshared_key']}",
                f"AllowedIPs = {row['vpn_ip']}/32",
                "",
            ]
        )
    lines.append("# END TG VPN MANAGED PEERS")
    return "\n".join(lines).strip() + "\n"


def apply_wireguard(conn: sqlite3.Connection) -> None:
    block = render_peer_block(conn)
    WG_MANAGED_PEERS_PATH.write_text(block, encoding="utf-8")
    if not APPLY_CHANGES:
        return
    if not WG_CONFIG_PATH.exists():
        raise RuntimeError(f"Не найден конфиг WireGuard: {WG_CONFIG_PATH}")
    base = WG_CONFIG_PATH.read_text(encoding="utf-8")
    start_marker = "# BEGIN TG VPN MANAGED PEERS"
    end_marker = "# END TG VPN MANAGED PEERS"
    if start_marker in base and end_marker in base:
        before = base.split(start_marker, 1)[0]
        after = base.split(end_marker, 1)[1]
        merged = before + block + after
    else:
        merged = base.rstrip() + "\n\n" + block
    WG_CONFIG_PATH.write_text(merged, encoding="utf-8")
    subprocess.run(
        [
            "bash",
            "-lc",
            f"wg syncconf {WG_INTERFACE} <(wg-quick strip {WG_INTERFACE})",
        ],
        check=True,
    )


def generate_peer_id(conn: sqlite3.Connection) -> int:
    while True:
        peer_id = secrets.randbelow(900000000) + 100000000
        exists = conn.execute("SELECT 1 FROM peers WHERE telegram_id=?", (peer_id,)).fetchone()
        if not exists:
            return peer_id


def generate_access_token() -> str:
    return secrets.token_urlsafe(DOWNLOAD_TOKEN_BYTES)


def create_invite(conn: sqlite3.Connection, created_by: str, uses: int, role: str) -> str:
    invite_role = role if role in {"red", "blue"} else "red"
    prefix = invite_role.upper()
    code = f"{prefix}-{secrets.token_urlsafe(6).replace('-', '').replace('_', '').upper()[:10]}"
    conn.execute(
        "INSERT INTO invites(code, role, max_uses, status, created_at, created_by) VALUES (?, ?, ?, 'active', ?, ?)",
        (code, invite_role, uses, utcnow(), created_by),
    )
    return code


def validate_invite(conn: sqlite3.Connection, code: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM invites WHERE code=?", (code.upper(),)).fetchone()
    if not row:
        raise RuntimeError("Инвайт-код не найден")
    if row["status"] != "active":
        raise RuntimeError("Инвайт-код неактивен")
    if row["used_count"] >= row["max_uses"]:
        raise RuntimeError("У инвайт-кода закончились активации")
    return row


def get_peer_by_token(conn: sqlite3.Connection, token: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM peers WHERE access_token=? AND status='active'", (token,)).fetchone()


def issue_peer(conn: sqlite3.Connection, display_name: str, invite_code: str) -> sqlite3.Row:
    invite = validate_invite(conn, invite_code)
    role = invite["role"] if invite["role"] in {"red", "blue"} else "red"
    private_key = generate_private_key()
    public_key = generate_public_key(private_key)
    preshared_key = generate_psk()
    vpn_ip = allocate_ip(conn, role)
    now = utcnow()
    peer_id = generate_peer_id(conn)
    access_token = generate_access_token()
    safe_name = " ".join(display_name.split())[:120] or f"web-{peer_id}"
    conn.execute(
        """
        INSERT INTO peers(
            telegram_id, username, display_name, role, vpn_ip, public_key, private_key,
            preshared_key, invite_code, status, created_at, updated_at, access_token
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
        """,
        (
            peer_id,
            "",
            safe_name,
            role,
            vpn_ip,
            public_key,
            private_key,
            preshared_key,
            invite["code"],
            now,
            now,
            access_token,
        ),
    )
    conn.execute("UPDATE invites SET used_count = used_count + 1 WHERE code=?", (invite["code"],))
    apply_wireguard(conn)
    row = conn.execute("SELECT * FROM peers WHERE telegram_id=?", (peer_id,)).fetchone()
    if row is None:
        raise RuntimeError("Не удалось создать профиль")
    config_text = render_client_config(row["private_key"], row["vpn_ip"], row["preshared_key"], row["role"])
    write_client_config(peer_id, config_text)
    return row


def revoke_peer(conn: sqlite3.Connection, peer_id: int) -> None:
    now = utcnow()
    conn.execute(
        "UPDATE peers SET status='revoked', revoked_at=?, updated_at=?, access_token=NULL WHERE telegram_id=? AND status='active'",
        (now, now, peer_id),
    )
    apply_wireguard(conn)


def rotate_peer(conn: sqlite3.Connection, peer_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM peers WHERE telegram_id=?", (peer_id,)).fetchone()
    if not row:
        raise RuntimeError("Профиль не найден")
    private_key = generate_private_key()
    public_key = generate_public_key(private_key)
    preshared_key = generate_psk()
    now = utcnow()
    access_token = generate_access_token()
    conn.execute(
        "UPDATE peers SET public_key=?, private_key=?, preshared_key=?, status='active', revoked_at=NULL, updated_at=?, access_token=? WHERE telegram_id=?",
        (public_key, private_key, preshared_key, now, access_token, peer_id),
    )
    apply_wireguard(conn)
    row = conn.execute("SELECT * FROM peers WHERE telegram_id=?", (peer_id,)).fetchone()
    if row is None:
        raise RuntimeError("Не удалось перевыпустить профиль")
    config_text = render_client_config(row["private_key"], row["vpn_ip"], row["preshared_key"], row["role"])
    write_client_config(peer_id, config_text)
    return row


def get_config_file(peer_id: int) -> Path:
    path = CONFIG_DIR / f"{peer_id}.conf"
    if not path.exists():
        raise RuntimeError("Файл конфигурации не найден")
    return path


def build_qr_png(text: str) -> bytes:
    image = qrcode.make(text)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def make_absolute_url(environ: dict, path: str) -> str:
    host = environ.get("HTTP_HOST") or f"{WEB_HOST}:{WEB_PORT}"
    scheme = environ.get("HTTP_X_FORWARDED_PROTO", environ.get("wsgi.url_scheme", "http"))
    return f"{scheme}://{host}{path}"


def parse_post(environ: dict) -> dict[str, str]:
    try:
        length = int(environ.get("CONTENT_LENGTH") or "0")
    except ValueError:
        length = 0
    body = environ["wsgi.input"].read(length) if length > 0 else b""
    raw = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    return {key: values[0] for key, values in raw.items()}


def response(start_response, status: str, body: bytes, content_type: str = "text/html; charset=utf-8"):
    start_response(status, [("Content-Type", content_type), ("Content-Length", str(len(body)))])
    return [body]


def redirect(start_response, location: str):
    start_response("303 See Other", [("Location", location), ("Content-Length", "0")])
    return [b""]


def render_layout(title: str, body: str) -> bytes:
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html_escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f3efe6;
      --panel: rgba(255,255,255,0.92);
      --ink: #1f2937;
      --muted: #5f6b7a;
      --accent: #0f766e;
      --accent-2: #164e63;
      --danger: #b91c1c;
      --border: rgba(15, 23, 42, 0.12);
      --shadow: 0 24px 60px rgba(15, 23, 42, 0.15);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", Tahoma, sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(20, 184, 166, 0.18), transparent 28%),
        radial-gradient(circle at top right, rgba(14, 116, 144, 0.18), transparent 26%),
        linear-gradient(180deg, #f6f3eb 0%, #efe7d8 100%);
      min-height: 100vh;
    }}
    .shell {{
      width: min(1080px, calc(100% - 32px));
      margin: 32px auto;
      display: grid;
      gap: 20px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 24px;
      padding: 24px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(10px);
    }}
    h1, h2, h3 {{ margin: 0 0 12px; }}
    p {{ margin: 0 0 14px; line-height: 1.5; color: var(--muted); }}
    form {{ display: grid; gap: 12px; }}
    label {{ font-size: 14px; font-weight: 600; color: var(--ink); }}
    input, textarea, select {{
      width: 100%;
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 12px 14px;
      font: inherit;
      background: #fff;
      color: var(--ink);
    }}
    textarea {{
      min-height: 260px;
      resize: vertical;
      font-family: "SFMono-Regular", Consolas, monospace;
      font-size: 13px;
    }}
    button, .button {{
      display: inline-block;
      border: none;
      border-radius: 999px;
      padding: 12px 18px;
      font: inherit;
      font-weight: 700;
      text-decoration: none;
      color: #fff;
      background: linear-gradient(135deg, var(--accent), var(--accent-2));
      cursor: pointer;
    }}
    .button.secondary {{
      background: #fff;
      color: var(--ink);
      border: 1px solid var(--border);
    }}
    .grid {{
      display: grid;
      gap: 18px;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    }}
    .hero {{
      padding: 36px;
      display: grid;
      gap: 14px;
    }}
    .badge {{
      display: inline-flex;
      width: fit-content;
      padding: 6px 10px;
      border-radius: 999px;
      background: rgba(15, 118, 110, 0.12);
      color: var(--accent-2);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}
    .message {{
      padding: 12px 14px;
      border-radius: 14px;
      font-weight: 600;
    }}
    .message.error {{
      background: rgba(185, 28, 28, 0.1);
      color: var(--danger);
    }}
    .table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    .table th, .table td {{
      padding: 10px 8px;
      border-bottom: 1px solid var(--border);
      text-align: left;
      vertical-align: top;
    }}
    .muted {{ color: var(--muted); }}
    .inline {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: center;
    }}
    code {{
      font-family: "SFMono-Regular", Consolas, monospace;
      background: rgba(15, 23, 42, 0.06);
      border-radius: 8px;
      padding: 2px 6px;
    }}
    img.qr {{
      width: min(320px, 100%);
      border-radius: 20px;
      border: 1px solid var(--border);
      background: #fff;
      padding: 12px;
    }}
    @media (max-width: 640px) {{
      .shell {{
        width: min(100% - 20px, 1080px);
        margin: 16px auto;
      }}
      .card, .hero {{
        padding: 18px;
      }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    {body}
  </main>
</body>
</html>"""
    return page.encode("utf-8")


def home_page(error: str = "") -> bytes:
    error_block = f'<div class="message error">{html_escape(error)}</div>' if error else ""
    body = f"""
    <section class="card hero">
      <span class="badge">Веб-портал WireGuard</span>
      <h1>{html_escape(WEB_TITLE)}</h1>
      <p>Активируй инвайт-код и получи WireGuard-конфиг прямо на этой странице.</p>
    </section>
    <section class="grid">
      <div class="card">
        <h2>Получить доступ</h2>
        <p>Введи инвайт-код. Портал создаст WireGuard-профиль и сразу покажет конфиг и QR-код.</p>
        {error_block}
        <form method="post" action="/redeem">
          <div>
            <label for="display_name">Имя</label>
            <input id="display_name" name="display_name" placeholder="Иван Иванов" maxlength="120">
          </div>
          <div>
            <label for="invite_code">Инвайт-код</label>
            <input id="invite_code" name="invite_code" placeholder="RED-XXXXXXXXXX" maxlength="32" required>
          </div>
          <button type="submit">Получить конфиг</button>
        </form>
      </div>
      <div class="card">
        <h2>Админка</h2>
        <p>Во встроенной админке можно создавать инвайты, отзывать профили и перевыпускать ключи.</p>
        <a class="button secondary" href="/admin">Открыть админку</a>
      </div>
    </section>
    """
    return render_layout(WEB_TITLE, body)


def success_page(environ: dict, row: sqlite3.Row) -> bytes:
    config_path = get_config_file(row["telegram_id"])
    config_text = config_path.read_text(encoding="utf-8")
    qr_b64 = base64.b64encode(build_qr_png(config_text)).decode("ascii")
    download_url = make_absolute_url(environ, f"/download?token={row['access_token']}")
    body = f"""
    <section class="card hero">
      <span class="badge">Профиль создан</span>
      <h1>Конфигурация готова</h1>
      <p>WireGuard-профиль создан. Сохрани конфиг сейчас. Прямая ссылка на скачивание привязана к токену этого профиля.</p>
    </section>
    <section class="grid">
      <div class="card">
        <h2>Данные подключения</h2>
        <p><strong>Имя:</strong> {html_escape(row["display_name"])}</p>
        <p><strong>VPN IP:</strong> <code>{html_escape(row["vpn_ip"])}</code></p>
        <p><strong>Ссылка на скачивание:</strong><br><code>{html_escape(download_url)}</code></p>
        <div class="inline">
          <a class="button" href="/download?token={html_escape(row['access_token'])}">Скачать .conf</a>
          <a class="button secondary" href="/">Назад</a>
        </div>
      </div>
      <div class="card">
        <h2>QR-код</h2>
        <p>Его можно сразу отсканировать в мобильном клиенте WireGuard.</p>
        <img class="qr" src="data:image/png;base64,{qr_b64}" alt="QR-код WireGuard">
      </div>
    </section>
    <section class="card">
      <h2>Текст конфига</h2>
      <textarea readonly>{html_escape(config_text)}</textarea>
    </section>
    """
    return render_layout("Конфигурация готова", body)


def admin_login_page(error: str = "") -> bytes:
    info = "<p>Задай <code>WEB_ADMIN_PASSWORD</code> в <code>.env</code>, чтобы включить действия администратора.</p>" if not WEB_ADMIN_PASSWORD else ""
    error_block = f'<div class="message error">{html_escape(error)}</div>' if error else ""
    body = f"""
    <section class="card hero">
      <span class="badge">Админка</span>
      <h1>Управление порталом</h1>
      <p>Создавай инвайты и управляй выданными профилями.</p>
    </section>
    <section class="card">
      {info}
      {error_block}
      <form method="post" action="/admin">
        <div>
          <label for="password">Пароль администратора</label>
          <input id="password" name="password" type="password" required>
        </div>
        <button type="submit">Открыть панель</button>
      </form>
    </section>
    """
    return render_layout("Вход в админку", body)


def admin_authorized(password: str) -> bool:
    if not WEB_ADMIN_PASSWORD:
        return False
    return hmac.compare_digest(password, WEB_ADMIN_PASSWORD)


def admin_dashboard(password: str, message: str = "", error: str = "") -> bytes:
    with db_conn() as conn:
        invites = conn.execute(
            "SELECT code, role, max_uses, used_count, status, created_at, created_by FROM invites ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
        peers = conn.execute(
            "SELECT telegram_id, display_name, role, vpn_ip, status, updated_at, invite_code FROM peers ORDER BY updated_at DESC LIMIT 50"
        ).fetchall()

    invite_rows = "".join(
        f"<tr><td><code>{html_escape(row['code'])}</code></td><td>{html_escape(row['role'])}</td><td>{row['used_count']} / {row['max_uses']}</td><td>{html_escape(row['status'])}</td><td>{html_escape(row['created_by'] or '')}</td><td>{html_escape(row['created_at'])}</td></tr>"
        for row in invites
    ) or '<tr><td colspan="6" class="muted">Инвайтов пока нет.</td></tr>'

    peer_rows = "".join(
        (
            "<tr>"
            f"<td><code>{row['telegram_id']}</code></td>"
            f"<td>{html_escape(row['display_name'])}</td>"
            f"<td>{html_escape(row['role'])}</td>"
            f"<td><code>{html_escape(row['vpn_ip'])}</code></td>"
            f"<td>{html_escape(row['status'])}</td>"
            f"<td>{html_escape(row['invite_code'] or '')}</td>"
            f"<td>{html_escape(row['updated_at'])}</td>"
            "<td>"
            '<form method="post" action="/admin/revoke">'
            f'<input type="hidden" name="password" value="{html_escape(password)}">'
            f'<input type="hidden" name="peer_id" value="{row["telegram_id"]}">'
            '<button type="submit">Отозвать</button>'
            "</form>"
            '<form method="post" action="/admin/rotate">'
            f'<input type="hidden" name="password" value="{html_escape(password)}">'
            f'<input type="hidden" name="peer_id" value="{row["telegram_id"]}">'
            '<button type="submit" class="secondary">Перевыпустить</button>'
            "</form>"
            "</td>"
            "</tr>"
        )
        for row in peers
    ) or '<tr><td colspan="8" class="muted">Профилей пока нет.</td></tr>'

    notices = []
    if message:
        notices.append(f'<div class="message">{html_escape(message)}</div>')
    if error:
        notices.append(f'<div class="message error">{html_escape(error)}</div>')
    notice_block = "".join(notices)

    body = f"""
    <section class="card hero">
      <span class="badge">Панель администратора</span>
      <h1>Управление доступом</h1>
      <p>Создавай инвайты и управляй выданными WireGuard-профилями.</p>
    </section>
    <section class="card">
      {notice_block}
      <form method="post" action="/admin/invite">
        <input type="hidden" name="password" value="{html_escape(password)}">
        <div class="inline">
          <div style="flex:1; min-width:220px;">
            <label for="role">Роль</label>
            <select id="role" name="role">
              <option value="red">red</option>
              <option value="blue">blue</option>
            </select>
          </div>
          <div style="flex:1; min-width:220px;">
            <label for="uses">Количество активаций</label>
            <input id="uses" name="uses" type="number" min="1" value="{DEFAULT_INVITE_USES}">
          </div>
          <button type="submit">Создать инвайт</button>
        </div>
      </form>
    </section>
    <section class="card">
      <h2>Последние инвайты</h2>
      <table class="table">
        <thead>
          <tr><th>Код</th><th>Роль</th><th>Использовано</th><th>Статус</th><th>Кем создан</th><th>Создан</th></tr>
        </thead>
        <tbody>{invite_rows}</tbody>
      </table>
    </section>
    <section class="card">
      <h2>Профили</h2>
      <table class="table">
        <thead>
          <tr><th>ID</th><th>Имя</th><th>Роль</th><th>VPN IP</th><th>Статус</th><th>Инвайт</th><th>Обновлен</th><th>Действия</th></tr>
        </thead>
        <tbody>{peer_rows}</tbody>
      </table>
    </section>
    """
    return render_layout("Панель администратора", body)


def handle_redeem(environ: dict, start_response):
    form = parse_post(environ)
    invite_code = form.get("invite_code", "").strip().upper()
    display_name = form.get("display_name", "").strip()
    if not invite_code:
        return response(start_response, "400 Bad Request", home_page("Нужно указать инвайт-код"))
    with db_conn() as conn:
        try:
            row = issue_peer(conn, display_name, invite_code)
        except Exception as exc:
            return response(start_response, "400 Bad Request", home_page(str(exc)))
    return response(start_response, "200 OK", success_page(environ, row))


def handle_download(environ: dict, start_response):
    token = parse_qs(environ.get("QUERY_STRING", "")).get("token", [""])[0]
    if not token:
        return response(start_response, "400 Bad Request", render_layout("Нет токена", "<section class='card'><h1>Не передан токен.</h1></section>"))
    with db_conn() as conn:
        row = get_peer_by_token(conn, token)
        if row is None:
            return response(start_response, "404 Not Found", render_layout("Не найдено", "<section class='card'><h1>Ссылка на конфиг недействительна или уже устарела.</h1></section>"))
    config_path = get_config_file(row["telegram_id"])
    config_bytes = config_path.read_bytes()
    headers = [
        ("Content-Type", "text/plain; charset=utf-8"),
        ("Content-Length", str(len(config_bytes))),
        ("Content-Disposition", f'attachment; filename="wg-{row["telegram_id"]}.conf"'),
    ]
    start_response("200 OK", headers)
    return [config_bytes]


def handle_admin(environ: dict, start_response):
    if environ["REQUEST_METHOD"] == "GET":
        return response(start_response, "200 OK", admin_login_page())
    form = parse_post(environ)
    password = form.get("password", "")
    if not admin_authorized(password):
        return response(start_response, "403 Forbidden", admin_login_page("Неверный пароль"))
    return response(start_response, "200 OK", admin_dashboard(password))


def handle_admin_invite(environ: dict, start_response):
    form = parse_post(environ)
    password = form.get("password", "")
    if not admin_authorized(password):
        return response(start_response, "403 Forbidden", admin_login_page("Неверный пароль"))
    role = form.get("role", "red").strip().lower()
    if role not in {"red", "blue"}:
        return response(start_response, "400 Bad Request", admin_dashboard(password, error="Некорректная роль"))
    try:
        uses = max(1, int(form.get("uses", str(DEFAULT_INVITE_USES))))
    except ValueError:
        return response(start_response, "400 Bad Request", admin_dashboard(password, error="Количество активаций должно быть числом"))
    with db_conn() as conn:
        code = create_invite(conn, "web-admin", uses, role)
    return response(start_response, "200 OK", admin_dashboard(password, message=f"Инвайт создан: {code}"))


def handle_admin_revoke(environ: dict, start_response):
    form = parse_post(environ)
    password = form.get("password", "")
    if not admin_authorized(password):
        return response(start_response, "403 Forbidden", admin_login_page("Неверный пароль"))
    try:
        peer_id = int(form.get("peer_id", ""))
    except ValueError:
        return response(start_response, "400 Bad Request", admin_dashboard(password, error="Некорректный ID профиля"))
    with db_conn() as conn:
        revoke_peer(conn, peer_id)
    return response(start_response, "200 OK", admin_dashboard(password, message=f"Профиль {peer_id} отозван"))


def handle_admin_rotate(environ: dict, start_response):
    form = parse_post(environ)
    password = form.get("password", "")
    if not admin_authorized(password):
        return response(start_response, "403 Forbidden", admin_login_page("Неверный пароль"))
    try:
        peer_id = int(form.get("peer_id", ""))
    except ValueError:
        return response(start_response, "400 Bad Request", admin_dashboard(password, error="Некорректный ID профиля"))
    try:
        with db_conn() as conn:
            row = rotate_peer(conn, peer_id)
    except Exception as exc:
        return response(start_response, "400 Bad Request", admin_dashboard(password, error=str(exc)))
    return response(
        start_response,
        "200 OK",
        admin_dashboard(password, message=f"Профиль {peer_id} перевыпущен. Новый токен: {row['access_token']}"),
    )


def app(environ: dict, start_response):
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()
    try:
        if path == "/" and method == "GET":
            return response(start_response, "200 OK", home_page())
        if path == "/redeem" and method == "POST":
            return handle_redeem(environ, start_response)
        if path == "/download" and method == "GET":
            return handle_download(environ, start_response)
        if path == "/admin" and method in {"GET", "POST"}:
            return handle_admin(environ, start_response)
        if path == "/admin/invite" and method == "POST":
            return handle_admin_invite(environ, start_response)
        if path == "/admin/revoke" and method == "POST":
            return handle_admin_revoke(environ, start_response)
        if path == "/admin/rotate" and method == "POST":
            return handle_admin_rotate(environ, start_response)
        return response(
            start_response,
            "404 Not Found",
            render_layout("Не найдено", "<section class='card'><h1>Страница не найдена</h1><a class='button secondary' href='/'>Назад</a></section>"),
        )
    except Exception as exc:
        return response(
            start_response,
            "500 Internal Server Error",
            render_layout("Ошибка сервера", f"<section class='card'><h1>Ошибка сервера</h1><p>{html_escape(exc)}</p></section>"),
        )


def main() -> None:
    init_db()
    server = make_server(WEB_HOST, WEB_PORT, app)
    print(f"Веб-портал запущен на http://{WEB_HOST}:{WEB_PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
