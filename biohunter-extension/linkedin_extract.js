// linkedin_extract.js
//
// Injected on-demand (via chrome.scripting.executeScript from popup.js)
// into the active tab when it's a LinkedIn job page. Returns whatever it
// can find; the popup UI shows the results as editable fields regardless,
// so a wrong/missing selector degrades to "user fixes it by hand" rather
// than a hard failure.
//
// *** UNVERIFIED SELECTORS ***
// These were NOT confirmed against a real live LinkedIn DOM in DevTools
// (same bar every companies.yaml css_selector in this project was held
// to -- e.g. AbbVie's selector was only trusted after
// `document.querySelectorAll(...).length` was checked by hand on a real
// posting). LinkedIn changes its DOM/class names periodically and I have
// no way to browse it live from here. Treat every selector below as a
// first guess -- the extension's own popup makes each field editable
// specifically because of this, and the README's step 1 says to check
// these against one real LinkedIn job page before relying on them.

(function extractLinkedInJob() {
  function text(selector) {
    const el = document.querySelector(selector);
    return el ? el.textContent.trim() : "";
  }

  // Best-guess selector chains, most-likely-current first, falling back
  // to older/alternate LinkedIn layouts that have existed at various
  // points. All unverified -- see header comment.
  const title =
    text("h1.top-card-layout__title") ||
    text("h1.t-24") ||
    text("h1[class*='job-title']") ||
    text("h1");

  const company =
    text("a.topcard__org-name-link") ||
    text("span.topcard__flavor a") ||
    text("[class*='company-name']");

  const location =
    text("span.topcard__flavor--bullet") ||
    text("[class*='job-location']");

  const description =
    text("div.description__text") ||
    text("div[class*='job-details']") ||
    text("article");

  // *** UNVERIFIED, same caveat as every selector above ***
  // LinkedIn job pages sometimes show a direct "apply on company site"
  // link, separate from the LinkedIn job URL itself -- this looks for
  // an anchor whose visible text mentions "company site", which is the
  // most likely stable signal (an href alone can't be trusted to point
  // at the company's domain vs. LinkedIn's own apply-tracking redirect).
  // Left blank, not guessed, if nothing matches -- the capture window's
  // field is manually editable either way.
  let applyUrl = "";
  const applyLinks = Array.from(document.querySelectorAll("a"));
  const companyLink = applyLinks.find((a) =>
    /company.?s?\s*(site|website)/i.test(a.textContent || "")
  );
  if (companyLink) {
    applyUrl = companyLink.href;
  }

  return {
    title,
    company,
    location,
    description,
    applyUrl,
    url: window.location.href,
  };
})();
