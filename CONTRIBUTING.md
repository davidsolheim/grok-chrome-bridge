# Contributing

Thanks for taking a look. This is a small, local-only Chrome bridge.

## Setup

```bash
./scripts/install.sh
```

Load `extension/` unpacked in Chrome (`chrome://extensions` → Developer mode). Expected ID: `kaelkjfngeajflpnjpgoijcjjcalnphi`.

## Tests

```bash
python3 tests/test_native_host.py
node tests/test_mcp_wrapper.mjs
```

## Please don’t

- Broaden native messaging `allowed_origins`
- Persist tab URLs, cookies, or account names
- Commit `*.pem`, `.env`, or `~/.grok/chrome-bridge.json`
- Point the MCP wrapper at a non-loopback DevTools endpoint
