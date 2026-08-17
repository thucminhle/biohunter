// capture.js
//
// Runs in a standalone chrome.windows.create() window (see
// background.js), not a default action popup -- so it does NOT close
// when you click over to the LinkedIn tab to select/copy text. Because
// this window isn't "the popup for tab X" anymore, the tab it's
// capturing from is passed explicitly via ?tabId=... in the URL rather
// than inferred from chrome.tabs.query({active:true}).
//
// Draft autosave: every keystroke/paste is saved (debounced) to
// chrome.storage.session, keyed by tabId, and restored on open. This is
// a second layer of protection on top of the window no longer
// auto-closing -- if you close the window by hand mid-fill, reopening
// it (same LinkedIn tab) brings back exactly what you had.

const fields = {
  company: document.getElementById("company"),
  title: document.getElementById("title"),
  location: document.getElementById("location"),
  url: document.getElementById("url"),
  applyUrl: document.getElementById("applyUrl"),
  description: document.getElementById("description"),
};
const sourceNote = document.getElementById("source-note");
const statusEl = document.getElementById("status");
const captureBtn = document.getElementById("captureBtn");

const params = new URLSearchParams(window.location.search);
const tabId = parseInt(params.get("tabId"), 10);
const draftKey = `draft_${tabId}`;

function isLinkedInJobPage(url) {
  return /linkedin\.com\/jobs\/(view|collections)/.test(url || "");
}

function currentValues() {
  return {
    company: fields.company.value,
    title: fields.title.value,
    location: fields.location.value,
    url: fields.url.value,
    applyUrl: fields.applyUrl.value,
    description: fields.description.value,
  };
}

let saveTimer = null;
function scheduleSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    chrome.storage.session.set({ [draftKey]: currentValues() });
  }, 300); // debounced so pasting a long description doesn't spam writes
}
Object.values(fields).forEach((el) => el.addEventListener("input", scheduleSave));

async function init() {
  const tab = await chrome.tabs.get(tabId);
  fields.url.value = tab.url || "";

  // Restore any saved draft for this tab FIRST -- if one exists, prefer
  // it over a fresh auto-extract, since a fresh extract would clobber
  // pasted text the user already fixed up by hand.
  const stored = await chrome.storage.session.get(draftKey);
  const draft = stored[draftKey];

  if (draft) {
    fields.company.value = draft.company || "";
    fields.title.value = draft.title || "";
    fields.location.value = draft.location || "";
    fields.url.value = draft.url || tab.url || "";
    fields.applyUrl.value = draft.applyUrl || "";
    fields.description.value = draft.description || "";
    sourceNote.textContent = "Restored your last unsaved draft for this tab.";
    return;
  }

  if (tab.url && isLinkedInJobPage(tab.url)) {
    sourceNote.textContent =
      "LinkedIn detected — auto-filled below. Selectors are unverified; check these against the real page before trusting them.";
    try {
      const [{ result }] = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: ["linkedin_extract.js"],
      });
      if (result) {
        fields.title.value = result.title || "";
        fields.company.value = result.company || "";
        fields.location.value = result.location || "";
        fields.description.value = result.description || "";
        fields.url.value = result.url || tab.url;
        fields.applyUrl.value = result.applyUrl || "";
      }
    } catch (err) {
      sourceNote.textContent =
        "Couldn't run LinkedIn extraction on this tab (" +
        err.message +
        "). Fill in the fields below by hand.";
    }
  } else {
    sourceNote.textContent =
      "No adapter for this site yet — fill in company and description by hand.";
    fields.title.value = tab.title || "";
  }
  scheduleSave();
}

captureBtn.addEventListener("click", async () => {
  const payload = {
    company: fields.company.value.trim(),
    title: fields.title.value.trim(),
    url: fields.url.value.trim(),
    location: fields.location.value.trim() || null,
    apply_url: fields.applyUrl.value.trim() || null,
    description: fields.description.value.trim(),
  };

  if (!payload.company || !payload.title || !payload.url || !payload.description) {
    statusEl.className = "error";
    statusEl.textContent = "Company, title, URL, and description are all required.";
    return;
  }

  captureBtn.disabled = true;
  statusEl.className = "";
  statusEl.textContent = "Sending...";

  chrome.runtime.sendMessage({ type: "CAPTURE_POSTING", payload }, (response) => {
    captureBtn.disabled = false;
    if (!response || !response.ok) {
      statusEl.className = "error";
      statusEl.textContent = (response && response.error) || "Unknown error.";
      return;
    }
    statusEl.className = "ok";
    const label = response.status === "duplicate" ? "Already captured — " : "Captured! ";
    statusEl.innerHTML =
      label + `<a href="${response.dashboardUrl}" target="_blank">Open in BioHunter</a>`;

    // Successful capture -- clear the draft so a later re-open of this
    // tab starts fresh instead of showing stale, already-submitted data.
    chrome.storage.session.remove(draftKey);
  });
});

init();
