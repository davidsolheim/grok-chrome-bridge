const activeEl = document.getElementById("active");
const activeLabel = document.getElementById("activeLabel");
const profileEl = document.getElementById("profile");
const debugEl = document.getElementById("debug");
const discoveryEl = document.getElementById("discovery");
const endpointEl = document.getElementById("endpoint");
const bannerEl = document.getElementById("banner");
const tabCountEl = document.getElementById("tabCount");
const tabsEl = document.getElementById("tabs");
const refreshBtn = document.getElementById("refresh");
const openDebugBtn = document.getElementById("openDebug");

function send(message) {
  return chrome.runtime.sendMessage(message);
}

function setBanner(kind, text) {
  if (!text) {
    bannerEl.hidden = true;
    bannerEl.textContent = "";
    bannerEl.className = "banner";
    return;
  }
  bannerEl.hidden = false;
  bannerEl.className = `banner ${kind}`;
  bannerEl.textContent = text;
}

function renderTabs(tabs) {
  tabsEl.replaceChildren();
  const list = Array.isArray(tabs) ? tabs.slice(0, 12) : [];
  for (const tab of list) {
    const li = document.createElement("li");
    const title = tab.title || tab.url || "Untitled";
    li.innerHTML = `<strong></strong> · <span></span>`;
    li.querySelector("strong").textContent = title;
    li.querySelector("span").textContent = tab.url || "";
    tabsEl.append(li);
  }
}

function render(status) {
  const native = status.lastNative || status.native || {};
  const discovery = native.discovery || {};
  const profile = discovery.profile || {};
  const active = Boolean(status.active);
  activeEl.checked = active;
  activeLabel.textContent = active ? "Active" : "Inactive";

  profileEl.textContent = profile.directory || "This Chrome profile";

  if (discovery.remoteDebugging) {
    debugEl.textContent = discovery.port ? `On · port ${discovery.port}` : "On";
    debugEl.className = "v ok";
  } else if (active) {
    debugEl.textContent = "Off";
    debugEl.className = "v warn";
  } else {
    debugEl.textContent = "Not checked";
    debugEl.className = "v";
  }

  if (!active) {
    discoveryEl.textContent = "Not advertising";
    discoveryEl.className = "v";
  } else if (discovery.active && (discovery.browserUrl || discovery.wsEndpoint)) {
    discoveryEl.textContent = "Written for Grok";
    discoveryEl.className = "v ok";
  } else {
    discoveryEl.textContent = "Waiting";
    discoveryEl.className = "v warn";
  }

  endpointEl.textContent = discovery.browserUrl || discovery.wsEndpoint || "—";

  const tabs = status.tabs || [];
  tabCountEl.textContent = String(status.tabCount ?? tabs.length ?? 0);
  renderTabs(tabs);

  if (!active) {
    setBanner("", "");
    return;
  }
  if (native.ok && discovery.remoteDebugging) {
    setBanner("ok", "Grok Build can attach to this profile. Keep Chrome open.");
    return;
  }
  if (native.error && /native host|install\.sh|Specified native messaging host not found/i.test(native.error)) {
    setBanner("error", "Native host is not installed. From the repo run ./scripts/install.sh");
    return;
  }
  if (!discovery.remoteDebugging) {
    setBanner(
      "warn",
      "Remote debugging is off. Open chrome://inspect/#remote-debugging, enable it, then Refresh.",
    );
    return;
  }
  if (native.error) {
    setBanner("error", native.error);
    return;
  }
  setBanner("", "");
}

async function loadStatus() {
  const status = await send({ type: "getStatus" });
  if (!status?.ok) {
    setBanner("error", status?.error || "Could not read extension status.");
    return;
  }
  render(status);
}

activeEl.addEventListener("change", async () => {
  activeEl.disabled = true;
  try {
    const result = await send({ type: "setActive", active: activeEl.checked });
    const status = await send({ type: "getStatus" });
    render({ ...status, native: result?.native || status.lastNative });
  } finally {
    activeEl.disabled = false;
  }
});

refreshBtn.addEventListener("click", async () => {
  refreshBtn.disabled = true;
  try {
    await send({ type: "refresh" });
    await loadStatus();
  } finally {
    refreshBtn.disabled = false;
  }
});

openDebugBtn.addEventListener("click", async () => {
  await send({ type: "openRemoteDebugging" });
});

void loadStatus();
