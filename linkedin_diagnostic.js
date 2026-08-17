// ============================================================
// BioHunter — LinkedIn page diagnostic
// Paste this ENTIRE file into the browser Console (see instructions)
// while viewing a real LinkedIn job posting. It only reads the page
// and prints results — it does not click, submit, or change anything.
// ============================================================

console.log("%c=== BIOHUNTER DIAGNOSTIC START ===", "font-weight:bold;font-size:14px;color:#1e5a3c;");
console.log("Page URL: " + window.location.href);

// ---------- PART 1: Does LinkedIn embed structured JobPosting data? ----------
// This is the best-case scenario -- a formal, stable data format instead
// of guessed CSS class names.
console.log("\n%c--- PART 1: Structured data (JSON-LD) ---", "font-weight:bold;color:#1e5a3c;");
(() => {
  const scripts = document.querySelectorAll('script[type="application/ld+json"]');
  console.log(`Found ${scripts.length} JSON-LD block(s) on this page.`);
  let foundJobPosting = false;
  scripts.forEach((s, i) => {
    try {
      const data = JSON.parse(s.textContent);
      const isJobPosting =
        data["@type"] === "JobPosting" ||
        (Array.isArray(data["@graph"]) && data["@graph"].some((x) => x["@type"] === "JobPosting"));
      console.log(`  Block [${i}]: @type = ${data["@type"] || "(graph)"} | looks like JobPosting: ${isJobPosting}`);
      if (isJobPosting) {
        foundJobPosting = true;
        console.log("  ✅ FULL JOBPOSTING DATA (screenshot or copy this block):");
        console.log(data);
      }
    } catch (e) {
      console.log(`  Block [${i}]: not parseable as JSON`);
    }
  });
  if (!foundJobPosting) {
    console.log("  ❌ No JobPosting structured data found on this page.");
  }
})();

// ---------- PART 2: Do the extension's current guessed CSS selectors work? ----------
console.log("\n%c--- PART 2: Current CSS selectors (fallback path) ---", "font-weight:bold;color:#1e5a3c;");
(() => {
  const candidates = {
    title: ["h1.top-card-layout__title", "h1.t-24", "h1[class*='job-title']", "h1"],
    company: ["a.topcard__org-name-link", "span.topcard__flavor a", "[class*='company-name']"],
    location: ["span.topcard__flavor--bullet", "[class*='job-location']"],
    description: ["div.description__text", "div[class*='job-details']", "article"],
  };
  for (const [field, selectors] of Object.entries(candidates)) {
    console.log(`  ${field}:`);
    let anyMatch = false;
    for (const sel of selectors) {
      const els = document.querySelectorAll(sel);
      if (els.length > 0) {
        anyMatch = true;
        const preview = els[0].textContent.trim().slice(0, 80);
        console.log(`    ✅ "${sel}" -> ${els.length} match(es). First: "${preview}${preview.length === 80 ? "…" : ""}"`);
      } else {
        console.log(`    ❌ "${sel}" -> no match`);
      }
    }
    if (!anyMatch) console.log(`    ⚠️ NOTHING matched for ${field}.`);
  }
})();

// ---------- PART 3: Does the "apply on company site" link heuristic work? ----------
console.log("\n%c--- PART 3: Apply-link heuristic ---", "font-weight:bold;color:#1e5a3c;");
(() => {
  const links = Array.from(document.querySelectorAll("a"));
  const matches = links.filter((a) => /company.?s?\s*(site|website)/i.test(a.textContent || ""));
  if (matches.length === 0) {
    console.log("  ❌ No anchor text matched the heuristic (this posting may just not have that link -- that's normal).");
  } else {
    matches.forEach((a) => console.log(`  ✅ Matched: "${a.textContent.trim()}" -> ${a.href}`));
  }
})();

console.log("\n%c=== BIOHUNTER DIAGNOSTIC END ===", "font-weight:bold;font-size:14px;color:#1e5a3c;");
console.log("Copy everything above (from START to END) and send it back.");
