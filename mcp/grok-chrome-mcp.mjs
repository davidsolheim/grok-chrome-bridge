#!/usr/bin/env node
/**
 * Launch chrome-devtools-mcp against the Chrome profile marked Active
 * by the Grok Chrome Bridge extension.
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const DEFAULT_DISCOVERY_PATH = path.join(
  os.homedir(),
  ".grok",
  "chrome-bridge.json",
);

export function discoveryPath() {
  return process.env.GROK_CHROME_BRIDGE_PATH || DEFAULT_DISCOVERY_PATH;
}

export function parseDevToolsActivePort(text) {
  const lines = String(text)
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length < 2) {
    throw new Error("DevToolsActivePort must contain a port and a debugger path");
  }
  const port = Number.parseInt(lines[0], 10);
  if (!Number.isInteger(port) || port <= 0 || port > 65535) {
    throw new Error(`Invalid DevToolsActivePort port: ${lines[0]}`);
  }
  const wsPath = lines[1].startsWith("/") ? lines[1] : `/${lines[1]}`;
  return {
    port,
    path: wsPath,
    browserUrl: `http://127.0.0.1:${port}`,
    wsEndpoint: `ws://127.0.0.1:${port}${wsPath}`,
  };
}

export function loadDiscovery(filePath = discoveryPath()) {
  if (!fs.existsSync(filePath)) {
    return null;
  }
  const raw = fs.readFileSync(filePath, "utf8");
  const data = JSON.parse(raw);
  return data && typeof data === "object" ? data : null;
}

export function rereadDevTools(userDataDir) {
  if (!userDataDir) {
    return null;
  }
  const portFile = path.join(userDataDir, "DevToolsActivePort");
  if (!fs.existsSync(portFile)) {
    return null;
  }
  try {
    return parseDevToolsActivePort(fs.readFileSync(portFile, "utf8"));
  } catch {
    return null;
  }
}

export function resolveConnection(discovery, reread = rereadDevTools) {
  if (!discovery || discovery.active !== true) {
    return {
      ok: false,
      error:
        "No Chrome profile is marked Active. Load Grok Chrome Bridge, enable the Active toggle.",
    };
  }
  const userDataDir = discovery.profile?.userDataDir;
  const live = reread(userDataDir);
  const browserUrl = live?.browserUrl || discovery.browserUrl;
  const wsEndpoint = live?.wsEndpoint || discovery.wsEndpoint;
  if (!browserUrl && !wsEndpoint) {
    return {
      ok: false,
      error:
        "Active profile found, but Chrome remote debugging is off. Open chrome://inspect/#remote-debugging and enable it.",
      discovery,
    };
  }
  return {
    ok: true,
    browserUrl,
    wsEndpoint,
    port: live?.port || discovery.port,
    discovery,
  };
}

export function buildMcpArgs(connection, extraArgs = []) {
  const args = ["-y", "chrome-devtools-mcp@latest"];
  if (connection.wsEndpoint) {
    args.push(`--ws-endpoint=${connection.wsEndpoint}`);
  } else if (connection.browserUrl) {
    args.push(`--browser-url=${connection.browserUrl}`);
  }
  const blockedFlags = new Set([
    "--autoConnect",
    "--auto-connect",
    "--category-extensions",
    "--categoryExtensions",
    "--status",
    "--help",
  ]);
  const blockedValueFlags = new Set([
    "--browser-url",
    "--browserUrl",
    "-u",
    "--ws-endpoint",
    "--wsEndpoint",
    "-w",
    "--ws-headers",
    "--wsHeaders",
    "--user-data-dir",
    "--userDataDir",
  ]);
  for (let i = 0; i < extraArgs.length; i += 1) {
    const raw = String(extraArgs[i]);
    const name = raw.split("=")[0];
    if (blockedValueFlags.has(name)) {
      if (!raw.includes("=") && i + 1 < extraArgs.length) {
        i += 1;
      }
      continue;
    }
    if (blockedFlags.has(name)) {
      continue;
    }
    args.push(raw);
  }
  return args;
}

function printStatus(result) {
  if (!result.ok) {
    console.log(JSON.stringify({ ok: false, error: result.error }, null, 2));
    return;
  }
  const profile = result.discovery?.profile || {};
  console.log(
    JSON.stringify(
      {
        ok: true,
        profile: profile.name || profile.directory || null,
        directory: profile.directory || null,
        userDataDir: profile.userDataDir || null,
        browserUrl: result.browserUrl,
        wsEndpoint: result.wsEndpoint,
        tabCount: Array.isArray(result.discovery?.tabs)
          ? result.discovery.tabs.length
          : 0,
        updatedAt: result.discovery?.updatedAt || null,
      },
      null,
      2,
    ),
  );
}

function fail(message) {
  console.error("Grok Chrome Bridge: " + message);
  console.error("");
  console.error("1. Load unpacked extension: GitHub/grok-chrome-bridge/extension");
  console.error("2. Enable chrome://inspect/#remote-debugging and click Allow");
  console.error("3. Click Active in the Grok Chrome Bridge popup");
  console.error("4. Re-run / reload Grok so MCP reconnects");
  process.exit(1);
}

export async function waitForConnection({
  timeoutMs = 8000,
  intervalMs = 400,
  load = loadDiscovery,
  reread = rereadDevTools,
} = {}) {
  const started = Date.now();
  let last = resolveConnection(load(), reread);
  while (!last.ok && Date.now() - started < timeoutMs) {
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
    last = resolveConnection(load(), reread);
  }
  return last;
}

async function main() {
  const argv = process.argv.slice(2);
  if (argv.includes("--status") || argv.includes("--help")) {
    if (argv.includes("--help")) {
      console.log("Usage: grok-chrome-mcp.mjs [--status] [...chrome-devtools-mcp args]");
      process.exit(0);
    }
    printStatus(resolveConnection(loadDiscovery()));
    process.exit(0);
  }

  const connection = await waitForConnection();
  if (!connection.ok) {
    fail(connection.error);
  }

  const extra = argv.filter((arg) => arg !== "--status");
  const args = buildMcpArgs(connection, extra);
  const child = spawn("npx", args, {
    stdio: "inherit",
    env: process.env,
  });
  child.on("exit", (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal);
      return;
    }
    process.exit(code ?? 1);
  });
  child.on("error", (error) => {
    console.error(`Grok Chrome Bridge: failed to start chrome-devtools-mcp: ${error.message}`);
    process.exit(1);
  });
}

const invokedDirectly =
  process.argv[1] &&
  fileURLToPath(import.meta.url) === path.resolve(process.argv[1]);

if (invokedDirectly) {
  void main();
}
