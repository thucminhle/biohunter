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
//
// *** Easy Apply handling (2026-08-17) ***
// linkedin_extract.js returns an `applyType` field alongside `applyUrl`
// ("external" | "easy_apply" | "none"), confirmed live on two real
// postings (see linkedin_extract.js's own header comment). When a
// posting uses LinkedIn's Easy Apply, there is no real company URL to
// save -- applyUrl comes back blank on purpose, and the field's
// placeholder text is set here to say so explicitly, so a blank field
// reads as "confirmed no link exists" rather than "extraction may have
// failed here too".
//
// *** Auto-close on capture (2026-08-17) ***
// Previously stayed open after a successful capture, showing a link to
// the posting's dashboard page. User doesn't need that link at capture
// time (can find the posting in the dashboard later), and wants the
// window out of the way immediately -- so this now shows a brief
// confirmation, then closes itself (background.js's onRemoved listener
// already resets its captureWindowId tracking however the window closes,
// so this doesn't need any change on that end). Only successful and
// duplicate captures auto-close; errors stay open so they're not missed.

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

const DEFAULT_APPLY_PLACEHOLDER = fields.applyUrl.placeholder;

// How long to show the "Captured!" confirmation before the window closes
// itself. Long enough to register as real feedback, short enough not to
// feel like it's lingering.
const AUTO_CLOSE_DELAY_MS = 900;

const params = new URLSearchParams(window.location.search);
const tabId = parseInt(params.get("tabId"), 10);
const draftKey = `draft_${tabId}`;

function isLinkedInJobPage(url) {
  return /linkedin\.com\/jobs\/(view|collections)/.test(url || "");
}

// Sets the apply-link field's placeholder based on what extraction found,
// so an empty field communicates WHY it's empty instead of looking broken.
function applyApplyTypeNote(applyType) {
  if (applyType === "easy_apply") {
    fields.applyUrl.placeholder = "This posting uses LinkedIn Easy Apply — no external link exists";
  } else if (applyType === "none") {
    fields.applyUrl.placeholder = "No Apply button detected — paste the link by hand if you have one";
  } else {
    fields.applyUrl.placeholder = DEFAULT_APPLY_PLACEHOLDER;
  }
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
        applyApplyTypeNote(result.applyType);

        if (result.applyType === "easy_apply") {
          sourceNote.textContent =
            "LinkedIn detected — auto-filled below. This posting uses Easy Apply, so there's no external application link to save (that's expected, not a missing field).";
        } else {
          sourceNote.textContent =
            "LinkedIn detected — auto-filled below. Double-check location and description before saving.";
        }
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
      // Error -- leave the window open so the message isn't missed, and
      // so the user can retry without having to redo the whole capture.
      statusEl.className = "error";
      statusEl.textContent = (response && response.error) || "Unknown error.";
      return;
    }

    // Success (or duplicate) -- clear the draft immediately so a later
    // re-open of this tab starts fresh instead of showing stale,
    // already-submitted data, then show a brief confirmation and close.
    chrome.storage.session.remove(draftKey);

    statusEl.className = "ok";
    statusEl.textContent =
      response.status === "duplicate" ? "Already captured — closing…" : "Captured! Closing…";

    setTimeout(() => window.close(), AUTO_CLOSE_DELAY_MS);
  });
});

init();
