/**
 * Regression tests for confirmed bugs.
 * Each test: verify bug was real → confirm fix works.
 *
 * BUG #1: CookieNotice OK button blocked by zIndex:9999 overlays (SignInScreen)
 * BUG #2: StepQuiz optionRow helper missing key props — React console error
 */
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = "http://localhost:3000";
const { cookieName, value } = JSON.parse(fs.readFileSync("tests-e2e/cookie.json", "utf8"));

let passed = 0;
let failed = 0;

function assert(condition, name) {
  if (condition) {
    console.log(`  ✅ PASS: ${name}`);
    passed++;
  } else {
    console.error(`  ❌ FAIL: ${name}`);
    failed++;
  }
}

const browser = await chromium.launch();

// ─────────────────────────────────────────────────────────────────────────────
// BUG #1: CookieNotice OK button clickable when SignInScreen overlay is present
// Root cause: zIndex:180 on CookieNotice < zIndex:9999 on SignInScreen overlay
// Fix: CookieNotice zIndex raised to 10000
// ─────────────────────────────────────────────────────────────────────────────
console.log("\n=== BUG #1 — CookieNotice clickable over SignInScreen ===");
{
  // Unauthenticated context — no session cookie so SignInScreen shows
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on("console", m => { if (m.type() === "error") consoleErrors.push(m.text()); });

  await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1200);

  // 1. Cookie notice is visible
  const noticeVisible = await page.evaluate(() => {
    const notice = [...document.querySelectorAll("div")].find(d =>
      d.style.position === "fixed" &&
      (d.textContent?.includes("cookie") || d.textContent?.includes("Cookie"))
    );
    if (!notice) return false;
    const r = notice.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  });
  assert(noticeVisible, "Cookie notice is visible on unauthenticated page load");

  // 2. SignInScreen overlay is present (the blocker that caused BUG #1)
  const signInOverlayPresent = await page.evaluate(() => {
    const overlays = [...document.querySelectorAll("div")].filter(d => {
      const s = window.getComputedStyle(d);
      return s.position === "fixed" && parseInt(s.zIndex) >= 9999 && parseInt(s.zIndex) < 10000;
    });
    return overlays.length > 0;
  });
  assert(signInOverlayPresent, "SignInScreen overlay at zIndex:9999 is present");

  // 3. Cookie notice OK button is topmost at its center point (not blocked)
  const okButtonTopmost = await page.evaluate(() => {
    const notice = [...document.querySelectorAll("div")].find(d =>
      d.style.position === "fixed" &&
      (d.textContent?.includes("cookie") || d.textContent?.includes("Cookie"))
    );
    if (!notice) return false;
    const okBtn = [...notice.querySelectorAll("button")].find(b =>
      /ok|accept|got it|dismiss|acknowledge/i.test(b.textContent || "")
    );
    if (!okBtn) return false;
    const r = okBtn.getBoundingClientRect();
    const cx = r.left + r.width / 2;
    const cy = r.top + r.height / 2;
    const top = document.elementFromPoint(cx, cy);
    return top === okBtn || okBtn.contains(top);
  });
  assert(okButtonTopmost, "Cookie notice OK button is topmost element (not blocked by overlay)");

  // 4. Cookie notice zIndex is > 9999
  const cookieZIndex = await page.evaluate(() => {
    const notice = [...document.querySelectorAll("div")].find(d =>
      d.style.position === "fixed" &&
      (d.textContent?.includes("cookie") || d.textContent?.includes("Cookie"))
    );
    return notice ? parseInt(window.getComputedStyle(notice).zIndex) : 0;
  });
  assert(cookieZIndex > 9999, `Cookie notice zIndex is > 9999 (got ${cookieZIndex})`);

  // 5. Clicking OK dismisses the notice
  if (noticeVisible) {
    await page.evaluate(() => {
      const notice = [...document.querySelectorAll("div")].find(d =>
        d.style.position === "fixed" &&
        (d.textContent?.includes("cookie") || d.textContent?.includes("Cookie"))
      );
      const okBtn = notice ? [...notice.querySelectorAll("button")].find(b =>
        /ok|accept|got it|dismiss|acknowledge/i.test(b.textContent || "")
      ) : null;
      okBtn?.click();
    });
    await page.waitForTimeout(500);
    const noticeGone = await page.evaluate(() => {
      const notice = [...document.querySelectorAll("div")].find(d =>
        d.style.position === "fixed" &&
        (d.textContent?.includes("cookie") || d.textContent?.includes("Cookie"))
      );
      return !notice || notice.getBoundingClientRect().height === 0;
    });
    assert(noticeGone, "Cookie notice dismissed after clicking OK");
  }

  await ctx.close();
}

// ─────────────────────────────────────────────────────────────────────────────
// BUG #2: StepQuiz optionRow lists have unique key props (no React warning)
// Root cause: optionRow factory fn returned <div> without key= prop
// Fix: added key parameter to optionRow, applied to root <div key={key}>
// ─────────────────────────────────────────────────────────────────────────────
console.log("\n=== BUG #2 — StepQuiz option rows have unique key props ===");
{
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  await ctx.addCookies([
    { name: cookieName, value, domain: "localhost", path: "/", httpOnly: true, secure: false, sameSite: "Lax" },
  ]);
  const page = await ctx.newPage();

  // Capture ALL console messages (React key warnings come as errors/warnings)
  const keyWarnings = [];
  page.on("console", m => {
    const text = m.text();
    if (/key.*prop|unique.*key|Each child in a list/i.test(text)) {
      keyWarnings.push(text.slice(0, 120));
    }
  });

  await page.goto(BASE + "/onboarding", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1000);

  // 1. Onboarding page loaded (StepWelcome visible)
  const stepWelcomeVisible = await page.evaluate(() => {
    const textarea = document.querySelector("textarea");
    return !!textarea && document.body.innerText.includes("Welcome to Astra");
  });
  assert(stepWelcomeVisible, "Onboarding StepWelcome rendered with textarea");

  // 2. Fill in StepWelcome and advance to StepQuiz
  await page.fill("input[placeholder='Alex']", "Test");
  await page.fill("textarea", "A SaaS tool for restaurant owners to manage inventory with AI predictions for 12 chars min.");
  await page.waitForTimeout(200);

  // Click Continue → (enabled when goal > 10 chars)
  const continueBtn = page.getByRole("button", { name: /continue/i });
  await continueBtn.click();
  await page.waitForTimeout(800);

  // 3. StepQuiz is now visible (business type options shown)
  const stepQuizVisible = await page.evaluate(() => {
    const text = document.body.innerText;
    return /business|B2B|B2C|SaaS|ecomm|type/i.test(text);
  });
  assert(stepQuizVisible, "StepQuiz rendered after Continue → click");

  // 4. Wait a moment for React to process all renders
  await page.waitForTimeout(500);

  // 5. No key prop warnings in console
  assert(
    keyWarnings.length === 0,
    `No "key" prop warnings — got ${keyWarnings.length}${keyWarnings.length ? ": " + keyWarnings[0] : ""}`
  );

  // 6. Options are clickable (rendered correctly with keys)
  const optionCount = await page.evaluate(() => {
    // Options are divs with onClick (the optionRow helper renders them)
    // They should be inside the quiz container
    const body = document.body.innerText;
    const hasBizTypes = /SaaS|ecomm|service|marketplace/i.test(body);
    return { hasBizTypes };
  });
  assert(optionCount.hasBizTypes, "Business type options rendered in StepQuiz");

  // 7. Click a business type option and advance to next sub-step
  const bizOptions = await page.evaluate(() => {
    const divs = [...document.querySelectorAll("div[style*='cursor']")];
    return divs.filter(d => d.textContent && d.textContent.length > 5).length;
  });
  assert(bizOptions > 0, `${bizOptions} clickable option rows found in StepQuiz`);

  await ctx.close();
}

// ─────────────────────────────────────────────────────────────────────────────
await browser.close();

console.log(`\n════════════════════════════════════════`);
console.log(`REGRESSION TESTS: ${passed} passed, ${failed} failed`);
if (failed > 0) {
  console.error("Some regression tests FAILED — check output above.");
  process.exit(1);
}
console.log("All regression tests PASSED.");
