import { chromium } from "playwright";
import fs from "node:fs";

const { cookieName, value } = JSON.parse(fs.readFileSync("tests-e2e/cookie.json", "utf8"));
const BASE = "http://localhost:3000";
const bugs = [];
function bug(vp, route, desc) { bugs.push({ vp, route, desc }); console.log(`\n🐛 BUG [${vp}] ${route}: ${desc}`); }
function pass(vp, route, check) { console.log(`   ✓ [${vp}] ${route}: ${check}`); }

const browser = await chromium.launch();

for (const vp of [{ name: "desktop", w: 1280, h: 800 }, { name: "mobile", w: 390, h: 844 }]) {
  const ctx = await browser.newContext({ viewport: { width: vp.w, height: vp.h } });
  await ctx.addCookies([
    { name: cookieName, value, domain: "localhost", path: "/", httpOnly: true, secure: false, sameSite: "Lax" },
    { name: "astra_cookie_notice", value: "acknowledged", domain: "localhost", path: "/" },
  ]);
  const page = await ctx.newPage();

  // ── /?new=1 — New Run goal input ─────────────────────────────────────────────
  console.log(`\n=== [${vp.name}] /?new=1 goal input ===`);
  await page.goto(BASE + "/?new=1", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1500);

  const newRunState = await page.evaluate(() => {
    const textarea = document.querySelector("textarea");
    const input = document.querySelector("input");
    const bodyText = document.body.innerText;
    const hasNewRun = /new run/i.test(bodyText);
    return {
      hasTextarea: !!textarea,
      placeholder: textarea?.placeholder?.slice(0, 80),
      hasInput: !!input,
      hasNewRunText: hasNewRun,
      overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 2,
      bodySlice: bodyText.slice(0, 120).replace(/\n/g, " "),
    };
  });
  pass(vp.name, "/?new=1", `textarea=${newRunState.hasTextarea}, placeholder="${newRunState.placeholder}", body: ${newRunState.bodySlice.slice(0, 60)}`);
  if (!newRunState.hasTextarea) bug(vp.name, "/?new=1", "no textarea for goal input in New Run view");
  if (newRunState.overflow) bug(vp.name, "/?new=1", "horizontal overflow");

  // Type into goal textarea
  if (newRunState.hasTextarea) {
    await page.fill("textarea", "Launch a SaaS for restaurant owners");
    await page.waitForTimeout(200);
    const submitState = await page.evaluate(() => {
      const btns = [...document.querySelectorAll("button")];
      const submit = btns.find(b => /launch|start|begin|run|go|↵|→/i.test(b.textContent || ""));
      return { submitText: submit?.textContent?.trim().slice(0, 30), submitDisabled: submit?.disabled };
    });
    pass(vp.name, "/?new=1", `submit: "${submitState.submitText}" disabled=${submitState.submitDisabled}`);
    if (submitState.submitDisabled === true) bug(vp.name, "/?new=1", "submit button disabled after typing goal");
  }

  // ── /outreach — modal overflow on mobile ─────────────────────────────────────
  console.log(`\n=== [${vp.name}] /outreach modal scroll test ===`);
  await page.goto(BASE + "/outreach", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1500);

  const newCampBtn = page.getByRole("button", { name: /new campaign/i });
  if (await newCampBtn.count() > 0) {
    await newCampBtn.click();
    await page.waitForTimeout(500);

    const modalCheck = await page.evaluate(() => {
      // Find the modal backdrop
      const allFixed = [...document.querySelectorAll("*")].filter(el => {
        const s = window.getComputedStyle(el);
        return s.position === "fixed" && (s.inset === "0px" || (s.top === "0px" && s.left === "0px" && s.right === "0px" && s.bottom === "0px"));
      });
      const modal = allFixed[allFixed.length - 1]; // topmost fixed element
      const modalInner = modal?.querySelector("[style*='overflow']") || modal;
      const inputs = modal ? [...modal.querySelectorAll("input, textarea, select")].map(i => ({
        tag: i.tagName,
        placeholder: i.placeholder?.slice(0, 30),
        rect: (() => { const r = i.getBoundingClientRect(); return { top: Math.round(r.top), h: Math.round(r.height), visible: r.height > 0 }; })(),
      })) : [];
      const bodyOverflow = document.documentElement.scrollWidth > document.documentElement.clientWidth + 2;
      return { inputCount: inputs.length, inputs, bodyOverflow, modalFound: !!modal };
    });

    if (!modalCheck.modalFound) {
      bug(vp.name, "/outreach", "modal not found via fixed position");
    } else {
      pass(vp.name, "/outreach", `modal: ${modalCheck.inputCount} inputs, overflow=${modalCheck.bodyOverflow}`);
      if (modalCheck.bodyOverflow) bug(vp.name, "/outreach", "modal causes horizontal overflow");

      // Check all inputs visible (not scrolled out of viewport)
      const hidden = modalCheck.inputs.filter(i => i.rect.top > 900 || i.rect.h === 0);
      if (hidden.length > 0) bug(vp.name, "/outreach", `${hidden.length} modal inputs not visible: ${hidden.map(i => i.placeholder || i.tag).join(", ")}`);
      else pass(vp.name, "/outreach", `all ${modalCheck.inputCount} inputs visible in viewport`);

      // Check labels
      const labelCheck = await page.evaluate(() => {
        const labels = [...document.querySelectorAll("label")].map(l => l.textContent?.trim().slice(0, 30));
        const selects = [...document.querySelectorAll("select")].map(s => ({ val: s.value, options: s.options.length }));
        return { labels, selects };
      });
      pass(vp.name, "/outreach", `labels: ${labelCheck.labels.join(" | ").slice(0, 60)}`);
    }

    // Close modal
    const closeBtn = page.locator("button").filter({ hasText: "✕" }).first();
    if (await closeBtn.count() > 0) await closeBtn.click();
    await page.waitForTimeout(200);
  }

  // ── /brain — suggested question click ────────────────────────────────────────
  console.log(`\n=== [${vp.name}] /brain suggested questions ===`);
  await page.goto(BASE + "/brain", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1200);

  const suggestedQ = await page.evaluate(() => {
    const btns = [...document.querySelectorAll("button")].filter(b => b.textContent && b.textContent.length > 20 && /\?/.test(b.textContent));
    return btns.map(b => b.textContent?.trim().slice(0, 60));
  });
  if (suggestedQ.length > 0) {
    pass(vp.name, "/brain", `suggested questions: ${suggestedQ[0]}`);
    // Click first suggested question
    const qBtn = page.locator("button").filter({ hasText: suggestedQ[0].slice(0, 20) }).first();
    if (await qBtn.count() > 0) {
      await qBtn.click();
      await page.waitForTimeout(800);
      const afterClick = await page.evaluate(() => {
        const input = document.querySelector("input[type='text'], textarea");
        return { inputVal: input?.value?.slice(0, 40), overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 2 };
      });
      pass(vp.name, "/brain", `after q click: input="${afterClick.inputVal}", overflow=${afterClick.overflow}`);
      if (afterClick.overflow) bug(vp.name, "/brain", "suggested question click causes overflow");
    }
  }

  await ctx.close();
}

await browser.close();

console.log("\n════════════════════════════════════════");
console.log(`Bugs: ${bugs.length}`);
bugs.forEach((b, i) => console.log(`  ${i+1}. [${b.vp}] ${b.route}: ${b.desc}`));
if (!bugs.length) console.log("  None.");
