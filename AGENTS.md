# Grok Chrome Bridge

Chromium MV3 extension + native messaging host that advertises the Active Chrome profile to Grok Build.

## Verify

```bash
python3 -m json.tool extension/manifest.json >/dev/null
python3 tests/test_native_host.py
node tests/test_mcp_wrapper.mjs
```

Expected extension ID (from `extension/manifest.json` `key`): `kaelkjfngeajflpnjpgoijcjjcalnphi`.

## Do not

- Launch a new Chrome user-data-dir from the MCP wrapper
- Broaden native messaging `allowed_origins`
- Commit `*.pem` or `~/.grok/chrome-bridge.json`
- Put API keys in the extension
