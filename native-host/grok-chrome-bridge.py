#!/usr/bin/env python3
"""Native messaging host: advertise the Chrome profile that marked itself Active."""

from __future__ import annotations

import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOST_NAME = "com.grokchromebridge.host"
PROTOCOL_VERSION = 1
DISCOVERY_PATH = Path.home() / ".grok" / "chrome-bridge.json"
MAX_NATIVE_BYTES = 64 * 1024
MAX_PORT_FILE_BYTES = 4096
INSTANCE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
PROFILE_DIR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,63}$")
EXTENSION_ID_RE = re.compile(r"^[a-p]{32}$")
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

CHROME_MACOS_MARKERS = (
    "/MacOS/Google Chrome",
    "/MacOS/Google Chrome Canary",
    "/MacOS/Google Chrome Dev",
    "/MacOS/Google Chrome Beta",
    "/MacOS/Chromium",
    "/MacOS/Brave Browser",
    "/MacOS/Microsoft Edge",
)

CHANNEL_DIRS = {
    "canary": "Google/Chrome Canary",
    "dev": "Google/Chrome Dev",
    "beta": "Google/Chrome Beta",
    "chromium": "Chromium",
    "brave": "BraveSoftware/Brave-Browser",
    "edge": "Microsoft Edge",
    "stable": "Google/Chrome",
}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_discovery_path() -> Path:
    return Path(os.environ.get("GROK_CHROME_BRIDGE_PATH", DISCOVERY_PATH))


def parse_devtools_active_port(text: str) -> dict[str, Any]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        raise ValueError("DevToolsActivePort must contain a port and a debugger path")
    port = int(lines[0])
    if port <= 0 or port > 65535:
        raise ValueError(f"Invalid DevToolsActivePort port: {lines[0]}")
    path = lines[1] if lines[1].startswith("/") else f"/{lines[1]}"
    if not re.fullmatch(r"/[A-Za-z0-9._/-]{1,200}", path):
        raise ValueError("Invalid DevToolsActivePort path")
    return {
        "port": port,
        "path": path,
        "browserUrl": f"http://127.0.0.1:{port}",
        "wsEndpoint": f"ws://127.0.0.1:{port}{path}",
    }


def infer_channel(command: str) -> str:
    lower = command.lower()
    if "chrome canary" in lower:
        return "canary"
    if "chrome dev" in lower:
        return "dev"
    if "chrome beta" in lower:
        return "beta"
    if "chromium" in lower:
        return "chromium"
    if "brave" in lower:
        return "brave"
    if "microsoft edge" in lower or "/edge" in lower:
        return "edge"
    return "stable"


def default_user_data_dir(channel: str = "stable") -> Path:
    suffix = CHANNEL_DIRS.get(channel, CHANNEL_DIRS["stable"])
    return Path.home() / "Library" / "Application Support" / suffix


def _flag_value(command: str, flag: str) -> str | None:
    match = re.search(
        rf"{re.escape(flag)}(?:=|\s+)((?:\"[^\"]+\")|(?:'[^']+')|(?:\S+))",
        command,
    )
    if not match:
        return None
    return match.group(1).strip("\"'")


def parse_chrome_command(command: str) -> dict[str, Any]:
    return {
        "channel": infer_channel(command),
        "userDataDir": _flag_value(command, "--user-data-dir"),
        "profileDirectory": _flag_value(command, "--profile-directory"),
    }


def sanitize_instance_id(value: Any) -> str | None:
    if not isinstance(value, str) or not INSTANCE_ID_RE.fullmatch(value):
        return None
    return value


def sanitize_profile_directory(value: Any) -> str:
    if isinstance(value, str) and PROFILE_DIR_RE.fullmatch(value.strip()):
        return value.strip()
    return "Default"


def sanitize_extension_id(value: Any) -> str | None:
    if not isinstance(value, str) or not EXTENSION_ID_RE.fullmatch(value):
        return None
    return value


def safe_user_data_dir(raw: Any) -> Path | None:
    if raw is None:
        return None
    try:
        path = Path(str(raw)).expanduser().resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    if not path.is_dir():
        return None
    return path


def proc_field(pid: int, field: str) -> str:
    out = subprocess.check_output(
        ["ps", "-p", str(pid), f"-o{field}="],
        text=True,
        stderr=subprocess.DEVNULL,
    )
    return out.strip()


def find_chrome_process(start_pid: int | None = None) -> dict[str, Any] | None:
    pid = os.getppid() if start_pid is None else start_pid
    seen: set[int] = set()
    last_chrome: dict[str, Any] | None = None
    while pid and pid > 1 and pid not in seen:
        seen.add(pid)
        try:
            command = proc_field(pid, "command")
            ppid_raw = proc_field(pid, "ppid")
        except (subprocess.CalledProcessError, FileNotFoundError):
            break
        if any(marker in command for marker in CHROME_MACOS_MARKERS) or re.search(
            r"(Google Chrome|Chromium|Brave Browser|Microsoft Edge)", command
        ):
            parsed = parse_chrome_command(command)
            last_chrome = {"pid": pid, **parsed}
            if any(marker in command for marker in CHROME_MACOS_MARKERS):
                return last_chrome
        try:
            pid = int(ppid_raw)
        except ValueError:
            break
    return last_chrome


def read_limited_text(path: Path, max_bytes: int) -> str:
    real = path.resolve()
    with open(real, "rb") as handle:
        data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"{path.name} is too large")
    return data.decode("utf-8")


def read_devtools(user_data_dir: Path) -> dict[str, Any] | None:
    port_file = user_data_dir / "DevToolsActivePort"
    if not port_file.is_file():
        return None
    try:
        real = port_file.resolve()
        if user_data_dir.resolve() not in real.parents and real.parent != user_data_dir.resolve():
            return None
        parsed = parse_devtools_active_port(read_limited_text(real, MAX_PORT_FILE_BYTES))
        parsed["portFile"] = str(real)
        return parsed
    except (OSError, ValueError):
        return None


def probe_browser(browser_url: str, timeout: float = 1.5) -> dict[str, Any] | None:
    try:
        parsed = urllib.parse.urlparse(browser_url)
    except ValueError:
        return None
    if parsed.scheme != "http" or (parsed.hostname or "") not in LOOPBACK_HOSTS:
        return None
    if parsed.port is None or not (1 <= parsed.port <= 65535):
        return None
    safe_url = f"http://127.0.0.1:{parsed.port}/json/version"
    req = urllib.request.Request(safe_url, method="GET")
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as resp:
            if getattr(resp, "status", 200) != 200:
                return None
            body = resp.read(8192)
        data = json.loads(body.decode("utf-8"))
        if not isinstance(data, dict):
            return None
        ws = data.get("webSocketDebuggerUrl")
        if ws is not None:
            ws_parsed = urllib.parse.urlparse(str(ws))
            if ws_parsed.scheme != "ws" or (ws_parsed.hostname or "") not in LOOPBACK_HOSTS:
                data.pop("webSocketDebuggerUrl", None)
        return {
            "Browser": data.get("Browser") if isinstance(data.get("Browser"), str) else None,
            "webSocketDebuggerUrl": data.get("webSocketDebuggerUrl"),
        }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError):
        return None


def load_discovery(path: Path | None = None) -> dict[str, Any] | None:
    target = path or default_discovery_path()
    if not target.is_file():
        return None
    try:
        data = json.loads(read_limited_text(target, 64 * 1024))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def write_discovery(data: dict[str, Any], path: Path | None = None) -> Path:
    target = path or default_discovery_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix="chrome-bridge.", suffix=".json", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, target)
        os.chmod(target, 0o600)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return target


def resolve_chrome(message: dict[str, Any]) -> dict[str, Any]:
    chrome = find_chrome_process()
    channel = chrome["channel"] if chrome else "stable"
    user_data_dir = safe_user_data_dir((chrome or {}).get("userDataDir")) or default_user_data_dir(
        channel
    )
    profile_directory = sanitize_profile_directory((chrome or {}).get("profileDirectory"))
    return {
        "chrome": {"pid": (chrome or {}).get("pid"), "channel": channel},
        "channel": channel,
        "userDataDir": user_data_dir,
        "profileDirectory": profile_directory,
    }


def build_discovery(message: dict[str, Any], active: bool) -> dict[str, Any]:
    resolved = resolve_chrome(message)
    user_data_dir: Path = resolved["userDataDir"]
    profile_directory = resolved["profileDirectory"]
    devtools = read_devtools(user_data_dir)
    version = probe_browser(devtools["browserUrl"]) if devtools else None
    if version and version.get("webSocketDebuggerUrl"):
        ws_endpoint = version["webSocketDebuggerUrl"]
    elif devtools:
        ws_endpoint = devtools["wsEndpoint"]
    else:
        ws_endpoint = None

    return {
        "v": PROTOCOL_VERSION,
        "host": HOST_NAME,
        "active": bool(active and devtools),
        "updatedAt": now_iso(),
        "remoteDebugging": bool(devtools),
        "port": devtools["port"] if devtools else None,
        "browserUrl": devtools["browserUrl"] if devtools else None,
        "wsEndpoint": ws_endpoint,
        "browser": (version or {}).get("Browser"),
        "profile": {
            "directory": profile_directory,
            "userDataDir": str(user_data_dir),
            "channel": resolved["channel"],
            "instanceId": sanitize_instance_id(message.get("instanceId")),
            "extensionId": sanitize_extension_id(message.get("extensionId")),
        },
        "pid": (resolved["chrome"] or {}).get("pid"),
    }


def handle_message(message: Any) -> dict[str, Any]:
    if not isinstance(message, dict):
        return {"ok": False, "error": "Message must be a JSON object."}
    action = message.get("action")
    path = default_discovery_path()

    if action == "ping":
        return {"ok": True, "result": "pong", "host": HOST_NAME}

    if action == "status":
        current = load_discovery(path)
        live = build_discovery(message, active=bool((current or {}).get("active")))
        return {"ok": True, "discovery": live}

    if action == "activate":
        if not sanitize_instance_id(message.get("instanceId")):
            return {"ok": False, "error": "instanceId is required."}
        discovery = build_discovery(message, active=True)
        write_discovery(discovery, path)
        if not discovery["remoteDebugging"]:
            return {
                "ok": False,
                "error": "Remote debugging is off. Open chrome://inspect/#remote-debugging and enable it.",
                "discovery": discovery,
            }
        return {"ok": True, "discovery": discovery}

    if action == "heartbeat":
        instance_id = sanitize_instance_id(message.get("instanceId"))
        if not instance_id:
            return {"ok": False, "error": "instanceId is required."}
        current = load_discovery(path)
        owner = (current or {}).get("profile", {}).get("instanceId")
        if current and current.get("active") and owner and owner != instance_id:
            return {
                "ok": True,
                "skipped": True,
                "error": "Another Chrome profile is currently Active.",
                "discovery": current,
            }
        should_write = (not current) or (not current.get("active")) or owner == instance_id
        discovery = build_discovery(message, active=should_write)
        if should_write:
            write_discovery(discovery, path)
        if should_write and not discovery["remoteDebugging"]:
            return {
                "ok": False,
                "error": "Remote debugging is off. Open chrome://inspect/#remote-debugging and enable it.",
                "discovery": discovery,
            }
        return {"ok": True, "discovery": discovery if should_write else current}

    if action == "deactivate":
        instance_id = sanitize_instance_id(message.get("instanceId"))
        current = load_discovery(path)
        owner = (current or {}).get("profile", {}).get("instanceId")
        if current and owner and instance_id and owner != instance_id:
            return {
                "ok": True,
                "skipped": True,
                "discovery": current,
            }
        discovery = build_discovery(message, active=False)
        discovery["active"] = False
        write_discovery(discovery, path)
        return {"ok": True, "discovery": discovery}

    return {"ok": False, "error": f'Unknown action "{action}".'}


def read_native_message() -> dict[str, Any] | None:
    raw_len = sys.stdin.buffer.read(4)
    if not raw_len:
        return None
    if len(raw_len) < 4:
        raise ValueError("Truncated native messaging length header")
    length = struct.unpack("<I", raw_len)[0]
    if length > MAX_NATIVE_BYTES:
        raise ValueError("Native messaging payload too large")
    payload = sys.stdin.buffer.read(length)
    if len(payload) < length:
        raise ValueError("Truncated native messaging payload")
    data = json.loads(payload.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Native messaging payload must be an object")
    return data


def write_native_message(message: dict[str, Any]) -> None:
    payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(payload)))
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


def main() -> int:
    try:
        message = read_native_message()
        if message is None:
            return 0
        write_native_message(handle_message(message))
        return 0
    except Exception as exc:  # noqa: BLE001 — last-chance native host envelope
        try:
            write_native_message({"ok": False, "error": str(exc)})
        except Exception:
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
