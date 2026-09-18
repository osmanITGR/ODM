const statusEl = document.getElementById("status");
const tokenEl = document.getElementById("token");
const enabledEl = document.getElementById("enabled");
const savedEl = document.getElementById("saved");

async function load() {
  const stored = await chrome.storage.local.get({ token: "", enabled: true });
  tokenEl.value = stored.token;
  enabledEl.checked = stored.enabled;
}

function ping() {
  statusEl.textContent = "Checking...";
  statusEl.className = "status";
  chrome.runtime.sendMessage({ type: "ping" }, (reply) => {
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
  await chrome.storage.local.set({
    token: tokenEl.value.trim(),
    enabled: enabledEl.checked,
  });
  savedEl.textContent = "Saved";
  setTimeout(() => (savedEl.textContent = ""), 1500);
  ping();
});

document.getElementById("recheck").addEventListener("click", ping);

enabledEl.addEventListener("change", async () => {
  await chrome.storage.local.set({ enabled: enabledEl.checked });
});

load().then(ping);
