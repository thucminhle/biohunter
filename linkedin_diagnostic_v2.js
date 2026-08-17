// ============================================================
// BioHunter — LinkedIn page diagnostic v2
// Same as before, but waits a moment for the page to finish loading
// before checking anything, and reports basic page stats first so we
// can tell "wrong selectors" apart from "page wasn't loaded yet".
// Paste this ENTIRE file into the Console (see instructions), then wait.
// It only reads the page -- it does not click, submit, or change anything.
// ============================================================

function runDiagnostic() {
  console.log("%c=== BIOHUNTER DIAGNOSTIC START ===", "font-weight:bold;font-size:14px;color:#1e5a3c;");
  console.log("Page URL: " + window.location.href);
  console.log("Page <title>: " + document.title);

  // ---------- PART 0: Basic sanity check -- did the page actually load? ----------
  console.log("\n%c--- PART 0: Page load sanity check ---", "font-weight:bold;color:#1e5a3c;");
  (() => {
    const bodyTextLength = document.body.innerText.trim().length;
    const h1s = document.querySelectorAll("h1");
    const allEls = document.querySelectorAll("*").length;
    console.log(`  Visible text on page: ${bodyTextLength} characters`);
    console.log(`  Total elements on page: ${allEls}`);
    console.log(`  <h1> elements found: ${h1s.length}`);
    h1s.forEach((h, i) => console.log(`    h1[${i}]: "${h.textContent.trim().slice(0, 80)}"`));
    if (bodyTextLength < 500) {
      console.log("  ⚠️ Very little text on the page -- it likely hasn't finished loading yet.");
      console.log("  ⚠️ Try waiting 5-10 seconds after the page looks done, then run this script again.");
    } else {
      console.log("  ✅ Page has substantial content loaded.");
    }
  })();

  // ---------- PART 1: Structured data (JSON-LD) ----------
  console.log("\n%c--- PART 1: Structured data (JSON-LD) ---", "font-weight:bold;color:#1e5a3c;");
  (() => {
    const scripts = document.querySelectorAll('script[type="application/ld+json"]');
    console.log(`  Found ${scripts.length} JSON-LD block(s) on this page.`);
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
    if (!foundJobPosting) console.log("  ❌ No JobPosting structured data found.");
  })();

  // ---------- PART 2: Current CSS selectors ----------
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

  // ---------- PART 3: Apply-link heuristic ----------
  console.log("\n%c--- PART 3: Apply-link heuristic ---", "font-weight:bold;color:#1e5a3c;");
  (() => {
    const links = Array.from(document.querySelectorAll("a"));
    const matches = links.filter((a) => /company.?s?\s*(site|website)/i.test(a.textContent || ""));
    if (matches.length === 0) {
      console.log("  ❌ No anchor text matched the heuristic (may just not be on this posting -- that's normal).");
    } else {
      matches.forEach((a) => console.log(`  ✅ Matched: "${a.textContent.trim()}" -> ${a.href}`));
    }
  })();

  console.log("\n%c=== BIOHUNTER DIAGNOSTIC END ===", "font-weight:bold;font-size:14px;color:#1e5a3c;");
  console.log("Copy everything above (from START to END) and send it back.");
}

console.log("Waiting 3 seconds for the page to finish rendering before checking anything...");
setTimeout(runDiagnostic, 3000);
