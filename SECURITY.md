# Security

This tool is designed to let a **local** coding agent control the Chrome profile you mark Active. That is powerful on purpose. Treat an Active profile like you have handed the agent your logged-in browser.

## Threat model

| Actor | What they can do |
|-------|------------------|
| You / Grok Build on this machine | Control the Active Chrome profile (tabs, cookies, logins) while remote debugging is on |
| Other local processes | If Chrome remote debugging is enabled, **any local process** can attach to that DevTools port. This is a Chrome property, not unique to this repo |
| Web pages | Nothing. The extension has no content scripts and no host permissions |
| Other extensions | Cannot talk to the native host. Chrome restricts native messaging to `allowed_origins` (this extension’s ID only) |
| Remote attackers | No listen address other than `127.0.0.1`. The host never probes a non-loopback URL |

## What is stored

| Location | Contents |
|----------|----------|
| `~/.grok/chrome-bridge.json` (mode `0600`) | Active flag, loopback DevTools URL, profile directory name, user-data-dir path, instance id |
| `chrome.storage.local` | Active toggle, random instance id, last host status |

The host does **not** write tab titles, tab URLs, cookies, Google account names, or email addresses.

The popup may show this profile’s open tabs **in memory only**, using the `tabs` permission. Those titles/URLs are not sent to the native host and are not written to the discovery file.

## What this repo does not contain

- API keys, tokens, or cookies
- A Chrome extension **private** key (the `key` field in `manifest.json` is the **public** key; it only pins the unpacked extension ID)
- Personal browsing data
- Company identifiers

## Safe use

1. Enable `chrome://inspect/#remote-debugging` only while you want an agent attached.
2. Keep **one** profile Active.
3. Do not browse sensitive accounts in that profile while debugging is on if you do not trust other software on the machine.
4. Run `./scripts/install.sh` from a clone you trust. `--configure-grok` rewrites only the `[mcp_servers.chrome-devtools]` section of `~/.grok/config.toml` and never prints that file (it may contain unrelated secrets).

## Reporting

Open a GitHub issue on this repository for vulnerabilities. Do not include cookies, tokens, or browsing history in reports.
