#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="${1:-/opt/web_vpn_podman}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

mkdir -p "${TARGET_DIR}"
mkdir -p "${TARGET_DIR}/data/configs"
mkdir -p "${TARGET_DIR}/env"
mkdir -p "${TARGET_DIR}/systemd"

install -m 0644 "${PROJECT_ROOT}/app.py" "${TARGET_DIR}/app.py"
install -m 0644 "${PROJECT_ROOT}/requirements.txt" "${TARGET_DIR}/requirements.txt"
install -m 0644 "${PROJECT_ROOT}/podman/Containerfile" "${TARGET_DIR}/Containerfile"
install -m 0644 "${PROJECT_ROOT}/podman/compose.yaml" "${TARGET_DIR}/compose.yaml"
install -m 0755 "${PROJECT_ROOT}/podman/entrypoint.sh" "${TARGET_DIR}/entrypoint.sh"
install -m 0644 "${PROJECT_ROOT}/podman/env/web-vpn.env.example" "${TARGET_DIR}/env/web-vpn.env.example"
install -m 0644 "${PROJECT_ROOT}/podman/systemd/web-vpn-podman.service" "${TARGET_DIR}/systemd/web-vpn-podman.service"
install -m 0644 "${PROJECT_ROOT}/DEPLOY.md" "${TARGET_DIR}/DEPLOY.md"
install -m 0644 "${PROJECT_ROOT}/OPERATIONS.md" "${TARGET_DIR}/OPERATIONS.md"
install -m 0644 "${PROJECT_ROOT}/README.md" "${TARGET_DIR}/README.md"

if [[ ! -f "${TARGET_DIR}/env/web-vpn.env" ]]; then
    cp "${TARGET_DIR}/env/web-vpn.env.example" "${TARGET_DIR}/env/web-vpn.env"
fi

echo "Podman stack prepared in ${TARGET_DIR}"
echo "Next steps:"
echo "  1. Edit ${TARGET_DIR}/env/web-vpn.env"
echo "  2. cd ${TARGET_DIR}"
echo "  3. podman-compose up -d --build"
