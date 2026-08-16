#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST_PATH = ROOT / "native-host" / "grok-chrome-bridge.py"


def load_host():
    spec = importlib.util.spec_from_file_location("grok_chrome_bridge", HOST_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


host = load_host()


class ParseTests(unittest.TestCase):
    def test_parse_devtools_active_port(self):
        parsed = host.parse_devtools_active_port("9333\n/devtools/browser/abc\n")
        self.assertEqual(parsed["port"], 9333)
        self.assertEqual(parsed["browserUrl"], "http://127.0.0.1:9333")
        self.assertEqual(parsed["wsEndpoint"], "ws://127.0.0.1:9333/devtools/browser/abc")

    def test_parse_devtools_rejects_bad_port(self):
        with self.assertRaises(ValueError):
            host.parse_devtools_active_port("not-a-port\n/devtools/browser/x\n")

    def test_parse_chrome_command_flags(self):
        cmd = (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
            '--user-data-dir="/tmp/Chrome Work" --profile-directory="Profile 1"'
        )
        parsed = host.parse_chrome_command(cmd)
        self.assertEqual(parsed["channel"], "stable")
        self.assertEqual(parsed["userDataDir"], "/tmp/Chrome Work")
        self.assertEqual(parsed["profileDirectory"], "Profile 1")

    def test_infer_canary(self):
        parsed = host.parse_chrome_command(
            "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary"
        )
        self.assertEqual(parsed["channel"], "canary")
        self.assertTrue(str(host.default_user_data_dir("canary")).endswith("Google/Chrome Canary"))


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.user_data = Path(self.tmp.name) / "Chrome"
        self.user_data.mkdir()
        self.discovery = Path(self.tmp.name) / "chrome-bridge.json"
        os.environ["GROK_CHROME_BRIDGE_PATH"] = str(self.discovery)

    def write_port(self, port: int = 9333):
        (self.user_data / "DevToolsActivePort").write_text(
            f"{port}\n/devtools/browser/test-id\n", encoding="utf-8"
        )

    def test_read_devtools_ignores_local_state_accounts(self):
        self.write_port()
        (self.user_data / "Local State").write_text(
            json.dumps(
                {
                    "profile": {
                        "info_cache": {
                            "Default": {
                                "name": "Work",
                                "gaia_name": "Secret Person",
                                "user_name": "secret@example.com",
                            }
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        parsed = host.read_devtools(self.user_data)
        self.assertEqual(parsed["port"], 9333)
        self.assertFalse(hasattr(host, "read_profile_name"))

    def test_probe_browser_rejects_non_loopback(self):
        self.assertIsNone(host.probe_browser("http://example.com:9222"))
        self.assertIsNone(host.probe_browser("https://127.0.0.1:9222"))

    def test_activate_requires_instance_id(self):
        result = host.handle_message({"action": "activate"})
        self.assertFalse(result["ok"])
        self.assertIn("instanceId", result["error"])

    def test_activate_without_debugging(self):
        original = host.resolve_chrome

        def fake_resolve(_message):
            return {
                "chrome": {"pid": 1, "channel": "stable"},
                "channel": "stable",
                "userDataDir": self.user_data,
                "profileDirectory": "Default",
            }

        host.resolve_chrome = fake_resolve  # type: ignore[method-assign]
        self.addCleanup(lambda: setattr(host, "resolve_chrome", original))
        result = host.handle_message(
            {"action": "activate", "instanceId": "aaa", "tabs": [{"title": "A", "url": "https://a.test"}]}
        )
        self.assertFalse(result["ok"])
        self.assertIn("Remote debugging", result["error"])
        stored = json.loads(self.discovery.read_text(encoding="utf-8"))
        self.assertFalse(stored["active"])
        self.assertNotIn("tabs", stored)
        self.assertNotIn("name", stored.get("profile", {}))

    def test_activate_and_foreign_heartbeat(self):
        original = host.resolve_chrome
        original_probe = host.probe_browser

        def fake_resolve(_message):
            return {
                "chrome": {"pid": 1, "channel": "stable"},
                "channel": "stable",
                "userDataDir": self.user_data,
                "profileDirectory": "Default",
            }

        host.resolve_chrome = fake_resolve  # type: ignore[method-assign]
        host.probe_browser = lambda _url, timeout=1.5: {  # type: ignore[method-assign]
            "Browser": "Chrome/144",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9333/devtools/browser/live",
        }
        self.addCleanup(lambda: setattr(host, "resolve_chrome", original))
        self.addCleanup(lambda: setattr(host, "probe_browser", original_probe))
        self.write_port()

        activated = host.handle_message({"action": "activate", "instanceId": "owner"})
        self.assertTrue(activated["ok"])
        self.assertTrue(activated["discovery"]["active"])
        self.assertEqual(
            activated["discovery"]["wsEndpoint"],
            "ws://127.0.0.1:9333/devtools/browser/live",
        )
        self.assertNotIn("tabs", activated["discovery"])
        self.assertNotIn("name", activated["discovery"]["profile"])

        skipped = host.handle_message({"action": "heartbeat", "instanceId": "other"})
        self.assertTrue(skipped["ok"])
        self.assertTrue(skipped.get("skipped"))
        stored = json.loads(self.discovery.read_text(encoding="utf-8"))
        self.assertEqual(stored["profile"]["instanceId"], "owner")

        deactivated = host.handle_message({"action": "deactivate", "instanceId": "other"})
        self.assertTrue(deactivated.get("skipped"))
        stored = json.loads(self.discovery.read_text(encoding="utf-8"))
        self.assertTrue(stored["active"])

        owner_off = host.handle_message({"action": "deactivate", "instanceId": "owner"})
        self.assertTrue(owner_off["ok"])
        stored = json.loads(self.discovery.read_text(encoding="utf-8"))
        self.assertFalse(stored["active"])

    def test_unknown_action(self):
        result = host.handle_message({"action": "nope"})
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
