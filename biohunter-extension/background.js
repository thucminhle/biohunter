// background.js
//
// Runs as a Manifest V3 service worker, NOT inside the LinkedIn (or any
// other) page. That distinction matters: a fetch() made from a content
// script would be subject to the LinkedIn page's own CORS policy and
// would be blocked reaching localhost. A fetch() made from here is
// extension-privileged and only needs `host_permissions` in manifest.json
// (already granted for http://localhost/* and http://127.0.0.1/*) -- no
// CORS headers need to be added on the BioHunter dashboard side at all.
//
// Default dashboard base URL matches dashboard.py's confirmed real
// default (`--port` defaults to 5050, confirmed in that file's own
// argparse setup) -- overridable via the options page for anyone running
// a different port.

const DEFAULT_BASE_URL = "http://localhost:5050";

// Clicking the toolbar icon now opens capture.html as its own small
// window (chrome.windows.create), NOT the default action popup. Default
// popups close the instant they lose focus -- which happens the moment
// you click on the page itself to select/copy text for pasting, wiping
// out whatever was typed so far. A separate window stays open across
// that click, same as any other window would.
//
// Only one capture window at a time -- if one's already open, focus it
// instead of stacking a second.
let captureWindowId = null;

chrome.action.onClicked.addListener(async (tab) => {
  if (captureWindowId !== null) {
    try {
      await chrome.windows.update(captureWindowId, { focused: true });
      return;
    } catch {
      // window was closed some other way (e.g. user clicked the X) --
      // fall through and open a fresh one
      captureWindowId = null;
    }
  }

  const win = await chrome.windows.create({
    url: `capture.html?tabId=${tab.id}`,
    type: "popup",
    width: 380,
    height: 560,
  });
  captureWindowId = win.id;
});

chrome.windows.onRemoved.addListener((closedId) => {
  if (closedId === captureWindowId) {
    captureWindowId = null;
  }
});

async function getBaseUrl() {
  const stored = await chrome.storage.sync.get("dashboardBaseUrl");
  return stored.dashboardBaseUrl || DEFAULT_BASE_URL;
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type !== "CAPTURE_POSTING") {
    return false; // not for us
  }

  (async () => {
    const baseUrl = await getBaseUrl();
    try {
      const res = await fetch(`${baseUrl}/api/postings/capture`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(message.payload),
      });

      let body;
      try {
        body = await res.json();
      } catch {
        // Route returned something that wasn't JSON at all -- e.g. the
        // dashboard isn't actually running, wrong port, or a real
        // server-side error page. Surface this honestly rather than
        // pretending it was a clean API error.
        sendResponse({
          ok: false,
          error: `Dashboard returned a non-JSON response (HTTP ${res.status}). Is it running, and is the port set correctly in the extension's options page?`,
        });
        return;
      }

      if (!res.ok || body.status === "error") {
        sendResponse({ ok: false, error: body.error || `HTTP ${res.status}` });
        return;
      }

      sendResponse({
        ok: true,
        status: body.status, // "created" or "duplicate"
        postingId: body.posting_id,
        dashboardUrl: `${baseUrl}${body.dashboard_url}`,
      });
    } catch (err) {
      // Most common real-world cause: dashboard isn't running, or the
      // base URL/port in options doesn't match what's actually serving.
      sendResponse({
        ok: false,
        error: `Could not reach ${baseUrl} -- is the BioHunter dashboard running? (${err.message})`,
      });
    }
  })();

  return true; // keep the message channel open for the async sendResponse
});
