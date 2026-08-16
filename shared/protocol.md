# Grok Chrome Bridge protocol

**Protocol version:** `1`

The Chromium extension marks a profile **Active**. A native messaging host writes a discovery file. Grok Build’s MCP wrapper reads that file and starts `chrome-devtools-mcp` against that Chrome instance.

```
Chrome profile (extension Active)
        │  native messaging
        ▼
native-host/grok-chrome-bridge.py
        │  ~/.grok/chrome-bridge.json
        ▼
mcp/grok-chrome-mcp.mjs
        │  --ws-endpoint / --browser-url
        ▼
chrome-devtools-mcp  →  this profile’s tabs, cookies, logins
```

## Native messaging

| Item | Value |
|------|--------|
| Host name | `com.grokchromebridge.host` |
| Host script | `native-host/grok-chrome-bridge.py` |
| Extension ID | `kaelkjfngeajflpnjpgoijcjjcalnphi` |
| Wire protocol | 4-byte little-endian length + UTF-8 JSON |
| Network | host only reads local Chrome files and `http://127.0.0.1:<port>/json/version` |

### Request

```json
{
  "v": 1,
  "action": "activate",
  "instanceId": "uuid-per-profile-install",
  "extensionId": "kaelkjfngeajflpnjpgoijcjjcalnphi"
}
```

The host ignores tab lists, user-agent strings, and other extra fields. Do not send page URLs or titles.

| `action` | Effect |
|----------|--------|
| `ping` | `{ ok: true, result: "pong" }` |
| `status` | Live probe of this Chrome + stored Active flag |
| `activate` | This profile becomes the one Grok should use |
| `heartbeat` | Refresh discovery if this profile still owns Active |
| `deactivate` | Clear Active if this profile owns it |

`instanceId` is a random id in `chrome.storage.local` (per Chrome profile). Heartbeats from a non-owner do not overwrite another profile’s Active claim. `activate` always takes ownership.

### Response

```json
{
  "ok": true,
  "discovery": {
    "v": 1,
    "active": true,
    "remoteDebugging": true,
    "browserUrl": "http://127.0.0.1:9222",
    "wsEndpoint": "ws://127.0.0.1:9222/devtools/browser/…",
    "profile": {
      "directory": "Default",
      "userDataDir": "/home/you/.config/google-chrome"
    }
  }
}
```

Discovery never includes tab titles, tab URLs, cookies, or account names.

## Discovery file

Path: `~/.grok/chrome-bridge.json` (override with `GROK_CHROME_BRIDGE_PATH`). Mode `0600`.

The MCP wrapper prefers a live `DevToolsActivePort` in `profile.userDataDir` over the cached URL, so a Chrome restart with a new debug port still works.

## Grok MCP wrapper

```bash
node mcp/grok-chrome-mcp.mjs --status
node mcp/grok-chrome-mcp.mjs
```

Spawns `npx -y chrome-devtools-mcp@latest --ws-endpoint=…`. Does not launch a new Chrome profile. Extra args cannot override the discovered loopback endpoint.

Remote debugging must be enabled in Chrome 144+ via `chrome://inspect/#remote-debugging`. An extension cannot turn that on by itself.
