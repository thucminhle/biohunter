// popup.js

const fields = {
  company: document.getElementById("company"),
  title: document.getElementById("title"),
  location: document.getElementById("location"),
  url: document.getElementById("url"),
  description: document.getElementById("description"),
};
const sourceNote = document.getElementById("source-note");
const statusEl = document.getElementById("status");
const captureBtn = document.getElementById("captureBtn");

function isLinkedInJobPage(url) {
  // Covers both the logged-in job-view URL shape and the public
  // /jobs/view/ shape. Not exhaustive -- LinkedIn has other URL shapes
  // for job search/collections pages that aren't a single posting; those
  // fall through to the generic fallback below, which is the intended,
  // safe behavior (better to ask the user to fill fields by hand than to
  // silently extract garbage from the wrong kind of page).
  return /linkedin\.com\/jobs\/(view|collections)/.test(url);
}

async function init() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  fields.url.value = tab.url || "";

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
      }
    } catch (err) {
      sourceNote.textContent =
        "Couldn't run LinkedIn extraction on this tab (" +
        err.message +
        "). Fill in the fields below by hand.";
    }
  } else {
    // Generic fallback -- not a recognized LinkedIn job page. Best-guess
    // pre-fill from the tab itself (page title, current URL); everything
    // else is left for the user to type in, same as the existing
    // /postings/manual HTML form already requires.
    sourceNote.textContent =
      "No adapter for this site yet — fill in company and description by hand.";
    fields.title.value = tab.title || "";
  }
}

captureBtn.addEventListener("click", async () => {
  const payload = {
    company: fields.company.value.trim(),
    title: fields.title.value.trim(),
    url: fields.url.value.trim(),
    location: fields.location.value.trim() || null,
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
  });
});

init();
