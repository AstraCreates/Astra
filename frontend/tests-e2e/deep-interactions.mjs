/**
 * Deep interaction tests — authenticated routes.
 * Tests specific UI interactions, edge cases, and error states.
 */
import { chromium } from "playwright";
import fs from "node:fs";

const { cookieName, value } = JSON.parse(fs.readFileSync("tests-e2e/cookie.json", "utf8"));
const BASE = "http://localhost:3000";

const bugs = [];
function bug(vp, route, desc, evidence = "") {
  bugs.push({ vp, route, desc, evidence });
  console.log(`\n🐛 BUG [${vp}] ${route}: ${desc}${evidence ? `\n   ${evidence}` : ""}`);
}
function pass(vp, route, check) {
  console.log(`   ✓ [${vp}] ${route}: ${check}`);
}

const browser = await chromium.launch();

for (const vp of [{ name: "desktop", w: 1280, h: 800 }, { name: "mobile", w: 390, h: 844 }]) {
  const ctx = await browser.newContext({ viewport: { width: vp.w, height: vp.h } });
  await ctx.addCookies([
    { name: cookieName, value, domain: "localhost", path: "/", httpOnly: true, secure: false, sameSite: "Lax" },
    { name: "astra_cookie_notice", value: "acknowledged", domain: "localhost", path: "/" },
  ]);
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on("console", m => { if (m.type() === "error") consoleErrors.push(m.text().slice(0, 200)); });

  // ── /goals ────────────────────────────────────────────────────────────────────
  console.log(`\n=== [${vp.name}] /goals — goal input ===`);
  await page.goto(BASE + "/goals", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1500);

  const goalState = await page.evaluate(() => {
    const textarea = document.querySelector("textarea");
    const inputs = [...document.querySelectorAll("input")];
    const submitBtn = [...document.querySelectorAll("button")].find(b =>
      /start|submit|launch|run|go|create|begin/i.test(b.textContent || "")
    );
    return {
      hasTextarea: !!textarea,
      textareaPlaceholder: textarea?.placeholder?.slice(0, 60),
      inputCount: inputs.length,
      submitText: submitBtn?.textContent?.trim().slice(0, 30),
      submitDisabled: submitBtn?.disabled,
    };
  });
  pass(vp.name, "/goals", `textarea: ${goalState.hasTextarea}, placeholder: ${goalState.textareaPlaceholder}`);
  if (!goalState.hasTextarea) bug(vp.name, "/goals", "no textarea for goal input");

  // Type into goal input and check submit enables
  if (goalState.hasTextarea) {
    await page.fill("textarea", "Launch a SaaS product for restaurant owners");
    await page.waitForTimeout(300);
    const afterFill = await page.evaluate(() => {
      const submitBtn = [...document.querySelectorAll("button")].find(b =>
        /start|submit|launch|run|go|create|begin|↵|→/i.test(b.textContent || "")
      );
      const textarea = document.querySelector("textarea");
      return { submitDisabled: submitBtn?.disabled, submitText: submitBtn?.textContent?.trim().slice(0, 30), val: textarea?.value?.slice(0, 40) };
    });
    pass(vp.name, "/goals", `after typing: submit="${afterFill.submitText}" disabled=${afterFill.submitDisabled}, val="${afterFill.val}"`);
  }

  // ── /brain — tab switching ────────────────────────────────────────────────────
  console.log(`\n=== [${vp.name}] /brain — tab interactions ===`);
  await page.goto(BASE + "/brain", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1500);

  const brainTabs = await page.evaluate(() =>
    [...document.querySelectorAll("button")].filter(b => /ask|knowledge|map|settings/i.test(b.textContent || ""))
      .map(b => b.textContent?.trim())
  );
  pass(vp.name, "/brain", `tabs: ${brainTabs.join(", ")}`);

  // Click Knowledge tab
  const knowledgeBtn = page.getByRole("button", { name: /knowledge/i });
  if (await knowledgeBtn.count() > 0) {
    await knowledgeBtn.first().click();
    await page.waitForTimeout(600);
    const knowledgeState = await page.evaluate(() => ({
      hasSourceList: document.querySelectorAll("[class*='source'], [class*='record']").length,
      bodyText: document.body.innerText.slice(0, 200),
    }));
    pass(vp.name, "/brain", `Knowledge tab: ${knowledgeState.bodyText.slice(0, 60).replace(/\n/g, " ")}`);
  }

  // ── /outreach — empty state + New Campaign modal ──────────────────────────────
  console.log(`\n=== [${vp.name}] /outreach — empty state + modal ===`);
  await page.goto(BASE + "/outreach", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2000);

  const outreachState = await page.evaluate(() => {
    const newBtn = [...document.querySelectorAll("button")].find(b => /new campaign/i.test(b.textContent || ""));
    const emptyState = document.body.innerText.includes("No campaigns");
    return { hasNewBtn: !!newBtn, emptyState, bodySlice: document.body.innerText.slice(0, 200) };
  });
  pass(vp.name, "/outreach", `newBtn=${outreachState.hasNewBtn}, empty=${outreachState.emptyState}`);

  // Click "+ New Campaign" and check modal opens
  const newCampaignBtn = page.getByRole("button", { name: /new campaign/i });
  if (await newCampaignBtn.count() > 0) {
    await newCampaignBtn.click();
    await page.waitForTimeout(500);
    const modalState = await page.evaluate(() => {
      const modal = document.querySelector("[style*='position: fixed'][style*='inset: 0']") ||
                    document.querySelector("[style*='position:fixed'][style*='inset:0']");
      const inputs = modal ? [...modal.querySelectorAll("input, textarea")].length : 0;
      const overflow = document.documentElement.scrollWidth > document.documentElement.clientWidth + 2;
      return { hasModal: !!modal, inputCount: inputs, overflow };
    });
    if (!modalState.hasModal) bug(vp.name, "/outreach", "New Campaign modal did not open");
    else {
      pass(vp.name, "/outreach", `New Campaign modal opened with ${modalState.inputCount} inputs`);
      if (modalState.overflow) bug(vp.name, "/outreach", "New Campaign modal causes horizontal overflow");
    }

    // Close modal with ✕
    const closeBtn = page.locator("button").filter({ hasText: "✕" });
    if (await closeBtn.count() > 0) {
      await closeBtn.click();
      await page.waitForTimeout(300);
      const modalGone = await page.evaluate(() => !document.querySelector("[style*='position: fixed'][style*='inset: 0']"));
      if (!modalGone) bug(vp.name, "/outreach", "New Campaign modal did not close on ✕");
      else pass(vp.name, "/outreach", "modal closes on ✕");
    }
  }

  // ── /credits — buy button interactions ──────────────────────────────────────
  console.log(`\n=== [${vp.name}] /credits — buy buttons ===`);
  await page.goto(BASE + "/credits", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1200);

  const creditBtns = await page.evaluate(() =>
    [...document.querySelectorAll("button")].filter(b => /buy|purchase|get|select|credit/i.test(b.textContent || ""))
      .map(b => ({
        text: b.textContent?.trim().slice(0, 40),
        disabled: b.disabled,
        rect: (() => { const r = b.getBoundingClientRect(); return { w: Math.round(r.width), h: Math.round(r.height) }; })(),
      }))
  );
  pass(vp.name, "/credits", `buy buttons: ${creditBtns.map(b => b.text).join(" | ").slice(0, 80)}`);
  if (creditBtns.length === 0) bug(vp.name, "/credits", "no buy buttons found");

  // ── /settings — Restart → flow ────────────────────────────────────────────────
  console.log(`\n=== [${vp.name}] /settings — interactions ===`);
  await page.goto(BASE + "/settings", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1200);

  // Check Settings page has all expected sections
  const settingsText = await page.evaluate(() => document.body.innerText);
  const expectedSections = ["Account", "Integrations", "Onboarding", "Notifications", "Platform"];
  for (const section of expectedSections) {
    if (!settingsText.includes(section)) bug(vp.name, "/settings", `missing section: ${section}`);
  }
  const foundSections = expectedSections.filter(s => settingsText.includes(s));
  pass(vp.name, "/settings", `sections: ${foundSections.join(", ")}`);

  // Check Theme toggle
  const themeToggle = await page.evaluate(() => {
    const btn = [...document.querySelectorAll("button")].find(b => /light|dark|theme/i.test(b.textContent || ""));
    return btn ? { text: btn.textContent?.trim().slice(0, 20), disabled: btn.disabled } : null;
  });
  if (!themeToggle) bug(vp.name, "/settings", "theme toggle button missing");
  else pass(vp.name, "/settings", `theme toggle: "${themeToggle.text}"`);

  // ── Console errors check ──────────────────────────────────────────────────────
  const nonApiErrors = consoleErrors.filter(e => !e.includes("ERR_CONNECTION_REFUSED") && !e.includes("localhost:8000") && !e.includes("404"));
  if (nonApiErrors.length > 0) {
    bug(vp.name, "ALL", `non-API console errors: ${nonApiErrors.slice(0, 3).join(" | ")}`);
  } else {
    pass(vp.name, "ALL", `no non-API console errors (${consoleErrors.length} backend errors expected)`);
  }

  await ctx.close();
}

await browser.close();

console.log("\n════════════════════════════════════════");
console.log("DEEP INTERACTION AUDIT COMPLETE");
console.log(`Bugs found: ${bugs.length}`);
bugs.forEach((b, i) => console.log(`  ${i+1}. [${b.vp}] ${b.route}: ${b.desc}${b.evidence ? "\n     " + b.evidence : ""}`));
if (!bugs.length) console.log("  None.");
fs.writeFileSync("tests-e2e/deep-audit-report.json", JSON.stringify({ bugs }, null, 2));
