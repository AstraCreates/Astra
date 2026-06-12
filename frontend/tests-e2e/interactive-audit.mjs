/**
 * Interactive UI audit — authenticated routes.
 * Tests interactions, not just screenshots.
 */
import { chromium } from "playwright";
import fs from "node:fs";

const { cookieName, value } = JSON.parse(fs.readFileSync("tests-e2e/cookie.json", "utf8"));
const BASE = "http://localhost:3000";

const VIEWPORTS = [
  { name: "desktop", width: 1280, height: 800 },
  { name: "mobile",  width: 390,  height: 844 },
];

const bugs = [];
function bug(vp, route, desc, evidence) {
  bugs.push({ vp, route, desc, evidence });
  console.log(`\n🐛 BUG [${vp}] ${route}: ${desc}`);
  if (evidence) console.log(`   Evidence: ${evidence}`);
}
function pass(vp, route, check) {
  console.log(`   ✓ [${vp}] ${route}: ${check}`);
}

async function withAuth(browser, vp) {
  const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
  await ctx.addCookies([{ name: cookieName, value, domain: "localhost", path: "/", httpOnly: true, secure: false, sameSite: "Lax" }]);
  // Dismiss cookie notice
  await ctx.addCookies([{ name: "astra_cookie_notice", value: "acknowledged", domain: "localhost", path: "/" }]);
  return ctx;
}

async function checkOverflow(page) {
  return page.evaluate(() => {
    const de = document.documentElement;
    return de.scrollWidth > de.clientWidth + 2;
  });
}

async function getErrors(page) {
  const errs = [];
  page.on("pageerror", e => errs.push(e.message));
  return errs;
}

const browser = await chromium.launch();

for (const vp of VIEWPORTS) {
  const ctx = await withAuth(browser, vp);
  const page = await ctx.newPage();
  const pageErrors = [];
  page.on("pageerror", e => pageErrors.push(e.message));

  // ── Home / Dashboard ─────────────────────────────────────────────────────────
  console.log(`\n=== [${vp.name}] Home ===`);
  await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1500);
  if (await checkOverflow(page)) bug(vp.name, "/", "overflow-X");
  // Expect to see dashboard (onboarding_done already set via localStorage or shows welcome)
  const homeText = await page.evaluate(() => document.body.innerText.slice(0, 300));
  pass(vp.name, "/", `body text: ${homeText.slice(0, 80).replace(/\n/g, " ")}`);

  // ── Brain ─────────────────────────────────────────────────────────────────────
  console.log(`\n=== [${vp.name}] /brain ===`);
  await page.goto(BASE + "/brain", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1200);
  if (await checkOverflow(page)) bug(vp.name, "/brain", "overflow-X");
  const brainButtons = await page.evaluate(() => [...document.querySelectorAll("button")].map(b => b.textContent?.trim().slice(0,30)));
  pass(vp.name, "/brain", `buttons: ${brainButtons.slice(0,5).join(", ")}`);

  // Check for broken images
  const brokenImgs = await page.evaluate(() =>
    [...document.querySelectorAll("img")].filter(i => !i.complete || i.naturalWidth === 0).map(i => i.src.slice(0,60))
  );
  if (brokenImgs.length) bug(vp.name, "/brain", `broken images: ${brokenImgs.join(", ")}`);

  // ── Goals ─────────────────────────────────────────────────────────────────────
  console.log(`\n=== [${vp.name}] /goals ===`);
  await page.goto(BASE + "/goals", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1200);
  if (await checkOverflow(page)) bug(vp.name, "/goals", "overflow-X");
  // Check textarea/input for goal input
  const goalInputs = await page.evaluate(() => [...document.querySelectorAll("input, textarea")].map(i => ({ tag: i.tagName, placeholder: i.placeholder?.slice(0,40) })));
  pass(vp.name, "/goals", `inputs: ${goalInputs.map(i => i.placeholder).join(" | ").slice(0,80)}`);

  // ── Integrations ──────────────────────────────────────────────────────────────
  console.log(`\n=== [${vp.name}] /integrations ===`);
  await page.goto(BASE + "/integrations", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1200);
  if (await checkOverflow(page)) bug(vp.name, "/integrations", "overflow-X");
  const intBtns = await page.evaluate(() => [...document.querySelectorAll("button")].map(b => b.textContent?.trim().slice(0,25)));
  pass(vp.name, "/integrations", `buttons found: ${intBtns.length}`);

  // ── Outreach ──────────────────────────────────────────────────────────────────
  console.log(`\n=== [${vp.name}] /outreach ===`);
  await page.goto(BASE + "/outreach", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2000);
  if (await checkOverflow(page)) bug(vp.name, "/outreach", "overflow-X");
  // Check no infinite spinner — should show either campaigns or empty state
  const outreachLoading = await page.evaluate(() => {
    const text = document.body.innerText;
    const hasEmptyState = text.includes("No campaigns yet") || text.includes("Create first campaign") || text.includes("New Campaign");
    const stuckLoading = text.includes("Loading campaigns") && !hasEmptyState;
    return { stuckLoading, hasEmptyState, text: text.slice(0, 100) };
  });
  if (outreachLoading.stuckLoading) bug(vp.name, "/outreach", "stuck loading spinner — campaigns never resolve");
  else pass(vp.name, "/outreach", `resolved: ${outreachLoading.text.slice(0,60).replace(/\n/g, " ")}`);

  // ── Payments ──────────────────────────────────────────────────────────────────
  console.log(`\n=== [${vp.name}] /payments ===`);
  await page.goto(BASE + "/payments", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2000);
  if (await checkOverflow(page)) bug(vp.name, "/payments", "overflow-X");
  const paymentsLoading = await page.evaluate(() => {
    const text = document.body.innerText;
    const resolved = text.includes("Connect your Stripe") || text.includes("Available Balance") || text.includes("Stripe");
    const stuck = text.includes("Checking Stripe connection") && !resolved;
    return { stuck, text: text.slice(0, 100) };
  });
  if (paymentsLoading.stuck) bug(vp.name, "/payments", "stuck checking Stripe connection");
  else pass(vp.name, "/payments", `resolved: ${paymentsLoading.text.slice(0,60).replace(/\n/g, " ")}`);

  // ── Credits ───────────────────────────────────────────────────────────────────
  console.log(`\n=== [${vp.name}] /credits ===`);
  await page.goto(BASE + "/credits", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1200);
  if (await checkOverflow(page)) bug(vp.name, "/credits", "overflow-X");
  const creditPlans = await page.evaluate(() => [...document.querySelectorAll("button")].filter(b => /buy|credit|purchase|get|select/i.test(b.textContent || "")).map(b => b.textContent?.trim().slice(0,30)));
  pass(vp.name, "/credits", `credit buttons: ${creditPlans.join(", ").slice(0,80)}`);

  // ── Settings ──────────────────────────────────────────────────────────────────
  console.log(`\n=== [${vp.name}] /settings ===`);
  await page.goto(BASE + "/settings", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1200);
  if (await checkOverflow(page)) bug(vp.name, "/settings", "overflow-X");

  // Test Manage → link renders + is clickable
  const manageLink = await page.evaluate(() => {
    const link = [...document.querySelectorAll("a")].find(a => a.textContent?.includes("Manage"));
    if (!link) return null;
    const r = link.getBoundingClientRect();
    const cx = r.left + r.width / 2;
    const cy = r.top + r.height / 2;
    const top = document.elementFromPoint(cx, cy);
    return { href: link.href, isTopmost: top === link || link.contains(top), rect: { w: Math.round(r.width), h: Math.round(r.height) }, text: link.textContent?.trim() };
  });
  if (!manageLink) bug(vp.name, "/settings", "Manage → link not found");
  else if (!manageLink.isTopmost) bug(vp.name, "/settings", `Manage → link blocked by overlay`, JSON.stringify(manageLink));
  else pass(vp.name, "/settings", `Manage → link clickable (${manageLink.text})`);

  // Mobile: check no text wrapping on Manage → arrow
  if (vp.name === "mobile" && manageLink) {
    const arrowWraps = await page.evaluate(() => {
      const link = [...document.querySelectorAll("a")].find(a => a.textContent?.includes("Manage"));
      if (!link) return false;
      // If arrow is on separate line, link height would be > ~44px (two lines)
      const r = link.getBoundingClientRect();
      return r.height > 44;
    });
    if (arrowWraps) bug(vp.name, "/settings", "Manage → arrow wraps to second line (height > 44px)");
    else pass(vp.name, "/settings", "Manage → fits on one line on mobile");
  }

  // Test Restart → button
  const restartBtn = await page.evaluate(() => {
    const btn = [...document.querySelectorAll("button")].find(b => b.textContent?.includes("Restart"));
    return btn ? { text: btn.textContent?.trim(), disabled: btn.disabled } : null;
  });
  if (!restartBtn) bug(vp.name, "/settings", "Restart → button not found");
  else pass(vp.name, "/settings", `Restart button found: "${restartBtn.text}"`);

  await ctx.close();
}

// ── Mobile-specific: sidebar hamburger ────────────────────────────────────────
console.log(`\n=== [mobile] Navigation hamburger ===`);
const mobCtx = await withAuth(browser, { width: 390, height: 844 });
const mobPage = await mobCtx.newPage();
await mobPage.goto(BASE + "/brain", { waitUntil: "domcontentloaded" });
await mobPage.waitForTimeout(1000);

const hamburger = await mobPage.evaluate(() => {
  const btn = [...document.querySelectorAll("button")].find(b => {
    const style = window.getComputedStyle(b);
    return b.getAttribute("aria-label")?.includes("menu") ||
           (b.querySelector("img") && parseInt(style.zIndex) > 60);
  });
  return btn ? { text: btn.textContent?.trim(), zIndex: window.getComputedStyle(btn).zIndex } : null;
});
if (!hamburger) {
  bug("mobile", "/brain", "hamburger menu button not found on mobile");
} else {
  pass("mobile", "/brain", `hamburger found zIndex=${hamburger.zIndex}`);
  // Click it and check if sidebar opens
  const menuBtn = await mobPage.$('[aria-label*="menu"], [aria-label*="Menu"]');
  if (menuBtn) {
    await menuBtn.click();
    await mobPage.waitForTimeout(400);
    const sidebarVisible = await mobPage.evaluate(() => {
      const nav = document.querySelector("nav");
      if (!nav) return false;
      const r = nav.getBoundingClientRect();
      return r.left >= 0 && r.width > 100;
    });
    if (!sidebarVisible) bug("mobile", "/brain", "hamburger click did not open sidebar");
    else pass("mobile", "/brain", "sidebar opens on hamburger click");
  }
}
await mobCtx.close();

await browser.close();

// ── Report ────────────────────────────────────────────────────────────────────
console.log("\n\n════════════════════════════════════════");
console.log("INTERACTIVE AUDIT COMPLETE");
console.log(`Bugs found: ${bugs.length}`);
bugs.forEach((b, i) => {
  console.log(`\n  ${i+1}. [${b.vp}] ${b.route}: ${b.desc}`);
  if (b.evidence) console.log(`     ${b.evidence}`);
});
if (bugs.length === 0) console.log("  None found.");
console.log("════════════════════════════════════════\n");

fs.writeFileSync("tests-e2e/interactive-audit-report.json", JSON.stringify({ bugs }, null, 2));
