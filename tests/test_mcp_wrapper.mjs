import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const wrapperPath = path.join(here, "..", "mcp", "grok-chrome-mcp.mjs");
const {
  parseDevToolsActivePort,
  resolveConnection,
  buildMcpArgs,
  waitForConnection,
} = await import(wrapperPath);

function testParsePort() {
  const parsed = parseDevToolsActivePort("9222\n/devtools/browser/xyz\n");
  assert.equal(parsed.port, 9222);
  assert.equal(parsed.browserUrl, "http://127.0.0.1:9222");
  assert.equal(parsed.wsEndpoint, "ws://127.0.0.1:9222/devtools/browser/xyz");
  assert.throws(() => parseDevToolsActivePort("only-one-line\n"));
}

function testResolvePrefersLivePort() {
  const discovery = {
    active: true,
    browserUrl: "http://127.0.0.1:1111",
    wsEndpoint: "ws://127.0.0.1:1111/devtools/browser/old",
    profile: { userDataDir: "/tmp/chrome-profile" },
  };
  const live = resolveConnection(discovery, () => ({
    port: 2222,
    browserUrl: "http://127.0.0.1:2222",
    wsEndpoint: "ws://127.0.0.1:2222/devtools/browser/new",
  }));
  assert.equal(live.ok, true);
  assert.equal(live.wsEndpoint, "ws://127.0.0.1:2222/devtools/browser/new");
}

function testResolveInactive() {
  const result = resolveConnection({ active: false }, () => null);
  assert.equal(result.ok, false);
  assert.match(result.error, /marked Active/);
}

function testResolveMissingDebug() {
  const result = resolveConnection(
    { active: true, profile: { userDataDir: "/tmp/none" } },
    () => null,
  );
  assert.equal(result.ok, false);
  assert.match(result.error, /remote debugging/i);
}

function testBuildArgs() {
  const args = buildMcpArgs(
    { wsEndpoint: "ws://127.0.0.1:9222/devtools/browser/x" },
    [
      "--autoConnect",
      "--no-usage-statistics",
      "--status",
      "--browser-url",
      "http://127.0.0.1:1",
      "--ws-endpoint=ws://evil.example/devtools",
    ],
  );
  assert.deepEqual(args, [
    "-y",
    "chrome-devtools-mcp@latest",
    "--ws-endpoint=ws://127.0.0.1:9222/devtools/browser/x",
    "--no-usage-statistics",
  ]);
}

async function testWaitForConnection() {
  let calls = 0;
  const result = await waitForConnection({
    timeoutMs: 1000,
    intervalMs: 20,
    load: () => {
      calls += 1;
      if (calls < 3) {
        return { active: false };
      }
      return {
        active: true,
        browserUrl: "http://127.0.0.1:9222",
        wsEndpoint: "ws://127.0.0.1:9222/devtools/browser/x",
      };
    },
    reread: () => null,
  });
  assert.equal(result.ok, true);
  assert.ok(calls >= 3);
}

testParsePort();
testResolvePrefersLivePort();
testResolveInactive();
testResolveMissingDebug();
testBuildArgs();
await testWaitForConnection();

const { rereadDevTools } = await import(wrapperPath);
const dir = fs.mkdtempSync(path.join(os.tmpdir(), "gcb-"));
fs.writeFileSync(path.join(dir, "DevToolsActivePort"), "9444\n/devtools/browser/disk\n");
const parsed = rereadDevTools(dir);
assert.equal(parsed.port, 9444);
fs.rmSync(dir, { recursive: true, force: true });

console.log("test_mcp_wrapper.mjs OK");
