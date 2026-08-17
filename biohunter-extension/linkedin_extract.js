// linkedin_extract.js
//
// Injected on-demand (via chrome.scripting.executeScript from
// popup.js/capture.js) into the active tab when it's a LinkedIn job page.
// Returns whatever it can find; the capture window shows the results as
// editable fields regardless, so a miss on any one field degrades to
// "user fixes it by hand" rather than a hard failure.
//
// *** REWRITTEN 2026-08-17 after live DevTools verification ***
// The previous version used hand-guessed CSS selectors like
// `a.topcard__org-name-link`. Live testing against a real posting
// (linkedin.com/jobs/view/4443580788) showed ALL of those return zero
// matches -- not because they were guessed wrong, but because LinkedIn's
// current build generates class names as short hashes (e.g. `_745ed96f`,
// `c8199d27`) that are reassigned on every LinkedIn deploy. Any selector
// built on those names is expected to break again the next time LinkedIn
// ships a new build, guessed correctly or not -- so this version avoids
// class-name matching for title/company/description entirely, and only
// keeps the softest form of it (pattern matching) for the one field that
// has no better source.
//
// *** Apply link, confirmed live 2026-08-17 on TWO real postings ***
// - External apply (Addition Therapeutics posting): anchor's aria-label
//   is exactly "Apply on company website", href is a LinkedIn safety-
//   redirect wrapper (linkedin.com/safety/go/?url=<real URL, encoded>&...)
//   -- unwrapped below to get the real destination instead of saving
//   LinkedIn's tracking link.
// - Easy Apply (R&D Partners posting): anchor's aria-label is "Easy Apply
//   to this job", href points back into linkedin.com itself (an in-site
//   application flow, not a real company link) -- correctly reported as
//   "no external link", not left ambiguous.
// IMPORTANT: matching is done on aria-label, NOT visible button text or
// general link text. Both button types visually just say "Apply" or
// "Easy Apply", so aria-label is the only reliable signal -- and a text-
// based search was confirmed live to false-positive-match "similar jobs"
// recommendation cards further down the page, which contain a hidden
// "Easy Apply" badge string in their link text even when their visible
// label is a completely different job's title.
//
// *** STILL FLAG FOR NEXT SESSION -- confirmed on TWO real postings only ***
// Title/company/description/location logic confirmed on one posting
// (Addition Therapeutics). Apply-link logic confirmed on two postings
// (Addition Therapeutics = external, R&D Partners = Easy Apply). None of
// this has run through the actual extension end-to-end yet for THIS
// specific apply-link change -- test it live before trusting it further.

(async function extractLinkedInJob() {
  // ---------- Title & company ----------
  // LinkedIn's <title> tag reliably follows "Job Title | Company | LinkedIn"
  // -- this is SEO/browser-tab metadata, not a styled DOM element, so it
  // isn't affected by LinkedIn's class-name hashing.
  const titleParts = document.title.split(" | ").map((s) => s.trim());
  const title = titleParts[0] || "";
  const company = titleParts.length >= 3 ? titleParts[1] : "";

  // ---------- Description ----------
  // LinkedIn truncates the description behind a "...see more" toggle by
  // default. Click it (if present) and wait briefly before reading the
  // page, then take the largest real text block, excluding the sidebar's
  // "Job search smarter with Premium" upsell block and anything that's
  // almost the entire page's text (which would mean <body> itself got
  // picked, not a real container).
  const clickable = Array.from(document.querySelectorAll("button, span, a"));
  const seeMore = clickable.find((el) =>
    /^(see more|show more|\.\.\.\s*more)$/i.test(el.textContent.trim())
  );
  if (seeMore) {
    seeMore.click();
    await new Promise((resolve) => setTimeout(resolve, 600));
  }

  const totalLen = document.body.textContent.trim().length;
  let description = "";
  let bestLen = 0;
  for (const el of document.querySelectorAll("body *")) {
    const t = el.textContent.trim();
    if (
      t.length > 300 &&
      t.length < totalLen * 0.9 &&
      !/premium|job search smarter/i.test(t) &&
      t.length > bestLen
    ) {
      bestLen = t.length;
      description = t;
    }
  }

  // ---------- Location ----------
  // No metadata source as clean as document.title exists for this one, so
  // this falls back to pattern matching: the shortest, childless elements
  // whose text looks like "City, ST" or "Remote"/"Hybrid"/"On-site". The
  // FIRST such match in document order is taken as the posting's real
  // location -- confirmed live that later matches further down the page
  // belong to a "similar jobs" recommendations module, not this posting.
  // Only checked on one posting so far -- worth confirming on a couple
  // more before fully trusting it.
  const locPattern =
    /^(remote|hybrid|on-?site)$|^[A-Za-z\s.'-]+,\s*[A-Za-z]{2,}(,\s*[A-Za-z\s]+)?$/i;
  let location = "";
  for (const el of document.querySelectorAll("body *")) {
    const t = el.textContent.trim();
    if (t.length > 0 && t.length < 60 && el.children.length === 0 && locPattern.test(t)) {
      location = t;
      break;
    }
  }

  // ---------- Apply link / Easy Apply detection ----------
  // applyType is one of:
  //   "external"   -- real Apply button, applyUrl holds the unwrapped
  //                   company application URL
  //   "easy_apply" -- LinkedIn's own in-site application flow, no
  //                   external link exists (applyUrl stays blank)
  //   "none"       -- neither button found (unexpected, but degrade
  //                   gracefully rather than error)
  const allLinks = Array.from(document.querySelectorAll("a"));
  const easyApplyEl = allLinks.find((a) =>
    /easy apply/i.test(a.getAttribute("aria-label") || "")
  );
  const externalApplyEl = allLinks.find((a) =>
    /apply on company website/i.test(a.getAttribute("aria-label") || "")
  );

  let applyType = "none";
  let applyUrl = "";

  if (easyApplyEl) {
    applyType = "easy_apply";
    // applyUrl intentionally left blank -- there is no external link for
    // Easy Apply postings, LinkedIn handles the whole application in-site.
  } else if (externalApplyEl) {
    applyType = "external";
    // The raw href is a LinkedIn safety-redirect wrapper, e.g.
    // "https://www.linkedin.com/safety/go/?url=<real URL, encoded>&...".
    // Unwrap it to save the real destination instead of LinkedIn's own
    // tracking link, which is what the capture window's "Direct
    // application link" field is meant to hold.
    const rawHref = externalApplyEl.href;
    try {
      const wrapped = new URL(rawHref).searchParams.get("url");
      applyUrl = wrapped ? decodeURIComponent(wrapped) : rawHref;
    } catch (e) {
      applyUrl = rawHref;
    }
  }

  return {
    title,
    company,
    location,
    description,
    applyUrl,
    applyType,
    url: window.location.href,
  };
})();
