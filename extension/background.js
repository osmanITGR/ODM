const BRIDGE = "http://127.0.0.1:47653";

// File types worth intercepting. Everything else goes to the browser as usual.
const INTERESTING = /\.(zip|rar|7z|tar|gz|bz2|xz|iso|img|exe|msi|apk|dmg|deb|rpm|appimage|pdf|epub|mobi|mp3|flac|wav|m4a|ogg|opus|mp4|mkv|avi|mov|webm|flv|m4v|wmv|doc|docx|xls|xlsx|ppt|pptx|csv|bin|pkg|jar|whl)$/i;

async function settings() {
  const stored = await chrome.storage.local.get({ token: "", enabled: true, minSize: 0 });
  return stored;
}

function isInteresting(item) {
  try {
    const path = new URL(item.url).pathname;
    return INTERESTING.test(path);
  } catch {
    return false;
  }
}

async function sendToOdm(url, filename) {
  const { token } = await settings();
  if (!token) throw new Error("no token configured");

  const response = await fetch(`${BRIDGE}/add`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-ODM-Token": token },
    body: JSON.stringify({ url, filename }),
  });

  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.error || `bridge returned ${response.status}`);
  }
}

function notify(title, message) {
  chrome.notifications.create({
    type: "basic",
    iconUrl: "icon48.png",
    title,
    message,
  });
}

chrome.downloads.onCreated.addListener(async (item) => {
  const { enabled, minSize } = await settings();
  if (!enabled) return;
  if (!item.url || item.url.startsWith("blob:") || item.url.startsWith("data:")) return;
  if (!isInteresting(item)) return;
  if (minSize && item.fileSize > 0 && item.fileSize < minSize) return;

  try {
    await sendToOdm(item.url, item.filename ? item.filename.split(/[\\/]/).pop() : null);
    // Handed off successfully, so stop the browser's own copy.
    await chrome.downloads.cancel(item.id);
    await chrome.downloads.erase({ id: item.id });
    notify("Sent to ODM", item.filename || item.url);
  } catch (error) {
    notify("ODM unavailable", `${error.message} - the browser will download it instead.`);
  }
});

chrome.runtime.onMessage.addListener((message, _sender, reply) => {
  if (message.type === "ping") {
    fetch(`${BRIDGE}/ping`)
      .then((r) => r.json())
      .then((data) => reply({ ok: true, data }))
      .catch((e) => reply({ ok: false, error: e.message }));
    return true;
  }
  if (message.type === "send") {
    sendToOdm(message.url, null)
      .then(() => reply({ ok: true }))
      .catch((e) => reply({ ok: false, error: e.message }));
    return true;
  }
});
