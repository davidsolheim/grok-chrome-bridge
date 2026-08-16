#!/usr/bin/env bash
# Register the native messaging host and optionally point Grok Build at this bridge.
#
# Usage:
#   ./scripts/install.sh
#   ./scripts/install.sh --configure-grok
#   ./scripts/install.sh --host /path/to/grok-chrome-bridge.py

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

NM_HOST_NAME="com.grokchromebridge.host"
EXTENSION_ID="kaelkjfngeajflpnjpgoijcjjcalnphi"
ALLOWED_ORIGIN="chrome-extension://${EXTENSION_ID}/"
CONFIGURE_GROK=0
HOST_PATH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --configure-grok)
      CONFIGURE_GROK=1
      shift
      ;;
    --host)
      HOST_PATH="${2:-}"
      shift 2
      ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "${HOST_PATH}" ]]; then
  HOST_PATH="${ROOT_DIR}/native-host/grok-chrome-bridge.py"
fi

if [[ ! -f "${HOST_PATH}" ]]; then
  echo "error: native host not found: ${HOST_PATH}" >&2
  exit 1
fi

HOST_PATH="$(cd "$(dirname "${HOST_PATH}")" && pwd)/$(basename "${HOST_PATH}")"
chmod +x "${HOST_PATH}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 is required for the native messaging host" >&2
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  echo "error: node is required for the Grok MCP wrapper" >&2
  exit 1
fi

MANIFEST_BODY="$(cat <<EOF
{
  "name": "${NM_HOST_NAME}",
  "description": "Advertise the Active Chrome profile to Grok Build",
  "path": "${HOST_PATH}",
  "type": "stdio",
  "allowed_origins": [
    "${ALLOWED_ORIGIN}"
  ]
}
EOF
)"

HOST_DIRS=(
  "${HOME}/Library/Application Support/Google/Chrome/NativeMessagingHosts"
  "${HOME}/Library/Application Support/Chromium/NativeMessagingHosts"
  "${HOME}/Library/Application Support/BraveSoftware/Brave-Browser/NativeMessagingHosts"
  "${HOME}/Library/Application Support/Microsoft Edge/NativeMessagingHosts"
)

echo "==> Installing native messaging host: ${NM_HOST_NAME}"
echo "    host: ${HOST_PATH}"
echo "    allowed_origins: ${ALLOWED_ORIGIN}"

INSTALLED=0
for dir in "${HOST_DIRS[@]}"; do
  mkdir -p "${dir}"
  target="${dir}/${NM_HOST_NAME}.json"
  printf '%s\n' "${MANIFEST_BODY}" > "${target}"
  echo "    wrote ${target}"
  INSTALLED=$((INSTALLED + 1))
done

echo "==> Native host registered (${INSTALLED} browser manifests)"

if [[ "${CONFIGURE_GROK}" -eq 1 ]]; then
  GROK_CONFIG="${HOME}/.grok/config.toml"
  WRAPPER="${ROOT_DIR}/mcp/grok-chrome-mcp.mjs"
  echo "==> Updating Grok chrome-devtools MCP (section only; config is not printed)"
  python3 - "${GROK_CONFIG}" "${WRAPPER}" <<'PY'
import pathlib
import re
import sys

config_path = pathlib.Path(sys.argv[1])
wrapper = sys.argv[2]
section = f"""[mcp_servers.chrome-devtools]
command = "node"
args = [
    {wrapper!r},
]
enabled = true
startup_timeout_sec = 30
"""
if not config_path.is_file():
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(section + "\n", encoding="utf-8")
    print(f"    created {config_path}")
    raise SystemExit(0)

text = config_path.read_text(encoding="utf-8")
pattern = re.compile(
    r"\[mcp_servers\.chrome-devtools\][\s\S]*?(?=\n\[|\Z)"
)
if pattern.search(text):
    updated = pattern.sub(section.rstrip() + "\n", text, count=1)
else:
    updated = text.rstrip() + "\n\n" + section
if updated != text:
    config_path.write_text(updated, encoding="utf-8")
    print("    updated chrome-devtools MCP section")
else:
    print("    chrome-devtools MCP section already pointed at the wrapper")
PY
  echo "==> Grok chrome-devtools MCP now uses ${WRAPPER}"
fi

echo ""
echo "Next:"
echo "  1. Chrome → chrome://extensions → Developer mode → Load unpacked"
echo "     ${ROOT_DIR}/extension"
echo "     Expected ID: ${EXTENSION_ID}"
echo "  2. Open chrome://inspect/#remote-debugging and enable remote debugging"
echo "  3. Click Active in the Grok Chrome Bridge popup"
echo "  4. Restart Grok Build (or reload MCP) so it attaches to this profile"
echo ""
if [[ "${CONFIGURE_GROK}" -eq 0 ]]; then
  echo "Optional: ./scripts/install.sh --configure-grok"
  echo "  rewrites ~/.grok/config.toml [mcp_servers.chrome-devtools] to this wrapper."
fi
