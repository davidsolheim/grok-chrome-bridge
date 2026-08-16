const NATIVE_HOST = "com.grokchromebridge.host";
const ALARM_NAME = "grok-chrome-bridge-heartbeat";
const HEARTBEAT_MINUTES = 0.5;

function uuid() {
  if (globalThis.crypto?.randomUUID) {
    return crypto.randomUUID();
  }
  return `inst-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function getState() {
  const data = await chrome.storage.local.get({
    active: false,
    instanceId: null,
    lastNative: null,
    lastError: null,
  });
  if (!data.instanceId) {
    data.instanceId = uuid();
    await chrome.storage.local.set({ instanceId: data.instanceId });
  }
  return data;
}

async function collectTabsForPopup() {
  const tabs = await chrome.tabs.query({});
  return tabs.slice(0, 50).map((tab) => ({
    title: tab.title || "",
    url: tab.url || "",
    active: Boolean(tab.active),
  }));
}

function sendNative(message) {
  return new Promise((resolve) => {
    let port;
    let settled = false;
    const finish = (value) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      try {
        port?.disconnect();
      } catch {
        // ignore
      }
      resolve(value);
    };

    try {
      port = chrome.runtime.connectNative(NATIVE_HOST);
    } catch (error) {
      finish({
        ok: false,
        error: error instanceof Error ? error.message : String(error),
      });
      return;
    }

    const timer = setTimeout(() => {
      finish({ ok: false, error: "Native host timed out after 5s." });
    }, 5000);

    port.onMessage.addListener((msg) => {
      finish(msg && typeof msg === "object" ? msg : { ok: false, error: "Empty native host response." });
    });
    port.onDisconnect.addListener(() => {
      const err = chrome.runtime.lastError?.message;
      finish({
        ok: false,
        error: err || "Native host disconnected before responding. Run scripts/install.sh.",
      });
    });
    port.postMessage(message);
  });
}

async function syncNative(action) {
  const state = await getState();
  const response = await sendNative({
    v: 1,
    action,
    instanceId: state.instanceId,
    extensionId: chrome.runtime.id,
  });

  const lastNative = response && typeof response === "object" ? response : { ok: false, error: "Invalid native response." };
  await chrome.storage.local.set({
    lastNative,
    lastError: lastNative.ok ? null : lastNative.error || "Native host failed.",
    lastSyncAt: new Date().toISOString(),
  });
  return lastNative;
}

async function setActive(active) {
  await chrome.storage.local.set({ active: Boolean(active) });
  await ensureAlarm(Boolean(active));
  return syncNative(active ? "activate" : "deactivate");
}

async function ensureAlarm(active) {
  if (active) {
    await chrome.alarms.create(ALARM_NAME, {
      periodInMinutes: HEARTBEAT_MINUTES,
    });
    return;
  }
  await chrome.alarms.clear(ALARM_NAME);
}

async function refreshIfActive() {
  const state = await getState();
  await ensureAlarm(state.active);
  if (!state.active) {
    return { ok: true, skipped: true, active: false };
  }
  return syncNative("heartbeat");
}

chrome.runtime.onInstalled.addListener(() => {
  void refreshIfActive();
});

chrome.runtime.onStartup.addListener(() => {
  void refreshIfActive();
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM_NAME) {
    void refreshIfActive();
  }
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const type = message?.type;
  if (type === "getStatus") {
    getState()
      .then(async (state) => {
        const tabs = await collectTabsForPopup();
        sendResponse({
          ok: true,
          active: state.active,
          instanceId: state.instanceId,
          lastNative: state.lastNative,
          lastError: state.lastError,
          tabCount: tabs.length,
          tabs,
        });
      })
      .catch((error) => {
        sendResponse({ ok: false, error: String(error) });
      });
    return true;
  }
  if (type === "setActive") {
    setActive(Boolean(message.active))
      .then((native) => sendResponse({ ok: Boolean(native?.ok), native }))
      .catch((error) => sendResponse({ ok: false, error: String(error) }));
    return true;
  }
  if (type === "refresh") {
    refreshIfActive()
      .then((native) => sendResponse({ ok: true, native }))
      .catch((error) => sendResponse({ ok: false, error: String(error) }));
    return true;
  }
  if (type === "openRemoteDebugging") {
    chrome.tabs
      .create({ url: "chrome://inspect/#remote-debugging" })
      .then(() => sendResponse({ ok: true }))
      .catch((error) => sendResponse({ ok: false, error: String(error) }));
    return true;
  }
  return false;
});
