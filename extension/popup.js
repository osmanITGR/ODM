const statusEl = document.getElementById("status");
const tokenEl = document.getElementById("token");
const enabledEl = document.getElementById("enabled");
const savedEl = document.getElementById("saved");

// Opening popup.html straight from disk is an easy mistake: the page renders
// normally, but chrome.storage and chrome.runtime do not exist outside an
// installed extension, so Save silently fails and the status never resolves.
const INSTALLED = typeof chrome !== "undefined" && !!chrome.storage;

function showNotInstalled() {
  statusEl.textContent = "Not loaded as an extension";
  statusEl.className = "status off";

  const hint = document.getElementById("hint");
  hint.innerHTML =
    "This page was opened from a file, so <b>Save</b> cannot work.<br><br>" +
    "Go to <b>chrome://extensions</b>, turn on <b>Developer mode</b>, " +
    "click <b>Load unpacked</b> and pick this folder. Then open the popup " +
    "from the toolbar icon.";
  hint.hidden = false;

  document.getElementById("save").disabled = true;
  document.getElementById("recheck").disabled = true;
  tokenEl.disabled = true;
  enabledEl.disabled = true;
}

async function load() {
  const stored = await chrome.storage.local.get({ token: "", enabled: true });
  tokenEl.value = stored.token;
  enabledEl.checked = stored.enabled;
}

function ping() {
  statusEl.textContent = "Checking...";
  statusEl.className = "status";
  chrome.runtime.sendMessage({ type: "ping" }, (reply) => {
    // A dead service worker leaves lastError set and reply undefined.
    if (chrome.runtime.lastError) {
      statusEl.textContent = "Extension error - try reloading it";
      statusEl.className = "status off";
      return;
    }
    if (reply && reply.ok) {
      statusEl.textContent = `Connected to ODM ${reply.data.version}`;
      statusEl.className = "status on";
    } else {
      statusEl.textContent = "ODM is not running";
      statusEl.className = "status off";
    }
  });
}

document.getElementById("save").addEventListener("click", async () => {
  try {
    await chrome.storage.local.set({
      token: tokenEl.value.trim(),
      enabled: enabledEl.checked,
    });
  } catch (error) {
    savedEl.textContent = `Could not save: ${error.message}`;
    return;
  }
  savedEl.textContent = "Saved";
  setTimeout(() => (savedEl.textContent = ""), 1500);
  ping();
});

document.getElementById("recheck").addEventListener("click", ping);

enabledEl.addEventListener("change", async () => {
  if (!INSTALLED) return;
  await chrome.storage.local.set({ enabled: enabledEl.checked });
});

if (INSTALLED) {
  load().then(ping);
} else {
  showNotInstalled();
}
