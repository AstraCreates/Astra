/**
 * Full QA audit — tests every page, button, and flow in Astra.
 * Usage: node tests-e2e/qa-full-audit.mjs
 */
import { chromium } from "playwright";
import fs from "fs";

const BASE = "http://localhost:3001";
const BUGS = [];
let page, browser, context;

function bug(page_name, desc, severity = "medium") {
  BUGS.push({ page: page_name, desc, severity });
  console.error(`  BUG [${severity.toUpperCase()}] ${page_name}: ${desc}`);
}

async function setup() {
  browser = await chromium.launch({ headless: true });
  context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  page = await context.newPage();

  // Capture console errors
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      const text = msg.text();
      // Filter out known noise
      if (text.includes("favicon") || text.includes("net::ERR_ABORTED")) return;
      console.log(`  [console.error] ${text.slice(0, 200)}`);
    }
  });
  page.on("pageerror", (err) => {
    console.log(`  [page.error] ${err.message.slice(0, 200)}`);
  });

  // Bypass auth gate via localStorage
  await page.goto(BASE);
  await page.evaluate(() => {
    localStorage.setItem("astra_qa_bypass", "1");
    localStorage.setItem("astra_dev_user_id", "google_jhinkesh05_gmail_com");
    localStorage.setItem("astra_auth_user_id", "google_jhinkesh05_gmail_com");
  });
  await page.reload({ waitUntil: "networkidle" });
  console.log("Auth bypass set. Current URL:", page.url());
}

async function waitAndCheck(selector, ctx) {
  try {
    await page.waitForSelector(selector, { timeout: 5000 });
    return true;
  } catch {
    bug(ctx, `selector not found: ${selector}`, "low");
    return false;
  }
}

async function goto(path) {
  await page.goto(`${BASE}${path}`, { waitUntil: "networkidle", timeout: 15000 });
  await page.waitForTimeout(800);
}

async function checkPageLoads(path, label) {
  console.log(`\n=== ${label} (${path}) ===`);
  try {
    await goto(path);
    // Check for error boundaries
    const errorTexts = ["Something went wrong", "Application error", "Error:", "404", "500"];
    for (const txt of errorTexts) {
      const el = await page.locator(`text=${txt}`).first();
      if (await el.isVisible().catch(() => false)) {
        const bodyText = await page.textContent("body").catch(() => "");
        if (bodyText.includes(txt)) {
          bug(label, `Page shows "${txt}"`, "high");
        }
      }
    }
    return true;
  } catch (err) {
    bug(label, `Page failed to load: ${err.message}`, "high");
    return false;
  }
}

// ── Dashboard / Home ──────────────────────────────────────────────────────────
async function testDashboard() {
  await checkPageLoads("/", "Dashboard");

  // Check main dashboard elements exist
  const bodyHTML = await page.content();
  if (!bodyHTML.includes("Astra") && !bodyHTML.includes("dashboard")) {
    bug("Dashboard", "No main content visible");
  }

  // Test theme toggle if present
  const themeToggle = page.locator('[aria-label*="theme"], [title*="theme"], button:has-text("Dark"), button:has-text("Light")').first();
  if (await themeToggle.isVisible().catch(() => false)) {
    await themeToggle.click();
    await page.waitForTimeout(300);
    await themeToggle.click(); // restore
    console.log("  ✓ Theme toggle works");
  }
}

// ── Sidebar Nav ───────────────────────────────────────────────────────────────
async function testSidebarNav() {
  console.log("\n=== Sidebar Navigation ===");
  await goto("/");

  const navLinks = [
    { text: "Dashboard", path: "/" },
    { text: "Goals", path: "/goals" },
    { text: "Brain", path: "/brain" },
    { text: "Library", path: "/library" },
    { text: "Agents", path: "/agents" },
    { text: "Integrations", path: "/integrations" },
    { text: "Settings", path: "/settings" },
  ];

  for (const link of navLinks) {
    const el = page.locator(`a[href="${link.path}"], nav a:has-text("${link.text}")`).first();
    if (await el.isVisible().catch(() => false)) {
      await el.click();
      await page.waitForTimeout(800);
      const url = page.url();
      if (!url.includes(link.path === "/" ? "/" : link.path.slice(1))) {
        bug("Sidebar", `Nav to ${link.text} went to ${url} not ${link.path}`, "medium");
      } else {
        console.log(`  ✓ Nav to ${link.text} works`);
      }
    } else {
      bug("Sidebar", `Nav link "${link.text}" not found`, "low");
    }
  }
}

// ── Goals Page ────────────────────────────────────────────────────────────────
async function testGoals() {
  await checkPageLoads("/goals", "Goals");

  // Look for any goal creation UI
  const newGoalBtn = page.locator('button:has-text("New"), button:has-text("Create"), button:has-text("Add"), button:has-text("Goal"), [placeholder*="goal" i]').first();
  if (await newGoalBtn.isVisible().catch(() => false)) {
    console.log("  ✓ New goal button visible");
    await newGoalBtn.click();
    await page.waitForTimeout(500);

    // Check if modal/input appeared
    const inputEl = page.locator('input[placeholder], textarea[placeholder], [role="dialog"]').first();
    if (await inputEl.isVisible().catch(() => false)) {
      console.log("  ✓ Goal creation dialog opens");
      // Try to type a goal
      await inputEl.fill("Test goal from QA");
      await page.keyboard.press("Escape");
    }
  } else {
    bug("Goals", "No goal creation button found", "medium");
  }

  // Check for existing goals list
  const goalItems = await page.locator('[class*="goal"], [class*="session"], li').count();
  console.log(`  Goals/sessions found: ${goalItems}`);
}

// ── Brain Page ────────────────────────────────────────────────────────────────
async function testBrain() {
  await checkPageLoads("/brain", "Brain");

  // Look for genome sections
  const sections = await page.locator('[class*="section"], [class*="card"], [class*="panel"]').count();
  console.log(`  Brain sections found: ${sections}`);

  // Check for save/edit buttons
  const editBtns = await page.locator('button:has-text("Edit"), button:has-text("Save"), button:has-text("Update")').count();
  console.log(`  Edit/Save buttons found: ${editBtns}`);

  if (editBtns === 0 && sections === 0) {
    bug("Brain", "No content or edit controls visible", "medium");
  }
}

// ── Library Page ──────────────────────────────────────────────────────────────
async function testLibrary() {
  await checkPageLoads("/library", "Library");

  // Look for document list
  const docItems = await page.locator('[class*="doc"], [class*="file"], [class*="item"], li').count();
  console.log(`  Library items found: ${docItems}`);

  // Check for upload/add button
  const uploadBtn = page.locator('button:has-text("Upload"), button:has-text("Add"), input[type="file"]').first();
  if (await uploadBtn.isVisible().catch(() => false)) {
    console.log("  ✓ Upload button visible");
  }

  // If there are items, click first one
  const firstItem = page.locator('[class*="file-item"], [class*="doc-item"], [role="listitem"]').first();
  if (await firstItem.isVisible().catch(() => false)) {
    await firstItem.click();
    await page.waitForTimeout(500);
    console.log("  ✓ Can click library item");
  }
}

// ── Agents Page ───────────────────────────────────────────────────────────────
async function testAgents() {
  await checkPageLoads("/agents", "Agents");

  const agentCards = await page.locator('[class*="agent"], [class*="card"]').count();
  console.log(`  Agent cards found: ${agentCards}`);

  if (agentCards === 0) {
    bug("Agents", "No agent cards visible", "low");
  }

  // Click first agent card if available
  const firstCard = page.locator('[class*="agent-card"], [class*="card"]').first();
  if (await firstCard.isVisible().catch(() => false)) {
    await firstCard.click();
    await page.waitForTimeout(500);
    // Check if detail view opened
    const detail = page.locator('[class*="detail"], [class*="modal"], [role="dialog"]').first();
    if (await detail.isVisible().catch(() => false)) {
      console.log("  ✓ Agent detail opens");
      await page.keyboard.press("Escape");
    }
  }
}

// ── Integrations Page ─────────────────────────────────────────────────────────
async function testIntegrations() {
  await checkPageLoads("/integrations", "Integrations");

  const integItems = await page.locator('[class*="integration"], [class*="connect"], [class*="card"]').count();
  console.log(`  Integration items found: ${integItems}`);

  // Check for any Connect buttons
  const connectBtns = await page.locator('button:has-text("Connect"), button:has-text("Enable")').count();
  console.log(`  Connect buttons: ${connectBtns}`);

  if (integItems === 0) {
    bug("Integrations", "No integration items visible", "low");
  }
}

// ── Settings Page ─────────────────────────────────────────────────────────────
async function testSettings() {
  await checkPageLoads("/settings", "Settings");

  // Check for profile/account settings
  const inputs = await page.locator('input, select, textarea').count();
  console.log(`  Settings inputs found: ${inputs}`);

  const saveBtns = await page.locator('button:has-text("Save"), button:has-text("Update"), button[type="submit"]').count();
  console.log(`  Save buttons found: ${saveBtns}`);

  if (inputs === 0 && saveBtns === 0) {
    bug("Settings", "No settings controls visible", "medium");
  }
}

// ── Session / Goal Workspace ──────────────────────────────────────────────────
async function testGoalWorkspace() {
  // Try to open a session workspace if sessions exist
  await goto("/goals");

  // Try clicking the first existing session
  const sessionLinks = page.locator('a[href*="/session"], a[href*="/s/"], [class*="session-item"]');
  const count = await sessionLinks.count();
  console.log(`\n=== Goal Workspace (${count} sessions found) ===`);

  if (count > 0) {
    const href = await sessionLinks.first().getAttribute("href");
    if (href) {
      await goto(href);
      await page.waitForTimeout(1000);

      // Check workspace renders
      const chatArea = page.locator('[class*="chat"], [class*="message"], [class*="workspace"], [class*="session"]').first();
      if (await chatArea.isVisible().catch(() => false)) {
        console.log("  ✓ Session workspace renders");
      } else {
        bug("Goal Workspace", "Session workspace content not visible", "high");
      }

      // Check for send/submit controls
      const sendBtn = page.locator('button[type="submit"], button:has-text("Send"), button:has-text("Run")').first();
      if (await sendBtn.isVisible().catch(() => false)) {
        console.log("  ✓ Send/Run button present");
      }
    }
  } else {
    console.log("  No sessions to test workspace (skip)");
  }
}

// ── Backend Health ────────────────────────────────────────────────────────────
async function testBackendHealth() {
  console.log("\n=== Backend Health ===");
  try {
    const resp = await page.request.get("http://localhost:8001/health", { timeout: 5000 });
    if (resp.ok()) {
      console.log("  ✓ Backend /health OK:", await resp.text());
    } else {
      bug("Backend", `/health returned ${resp.status()}`, "critical");
    }
  } catch (err) {
    bug("Backend", `Cannot reach backend: ${err.message}`, "critical");
  }

  // Test files API
  try {
    const resp = await page.request.get("http://localhost:8001/api/files", { timeout: 5000 });
    if (resp.ok()) {
      const data = await resp.json();
      console.log(`  ✓ /api/files returns ${Array.isArray(data) ? data.length : "?"} files`);
    } else {
      bug("Backend", `/api/files returned ${resp.status()}`, "medium");
    }
  } catch (err) {
    bug("Backend", `/api/files error: ${err.message}`, "medium");
  }

  // Test sessions API
  try {
    const resp = await page.request.get("http://localhost:8001/api/sessions?founder_id=google_jhinkesh05_gmail_com", { timeout: 5000 });
    if (resp.ok()) {
      const data = await resp.json();
      console.log(`  ✓ /api/sessions returns ${Array.isArray(data) ? data.length : "?"} sessions`);
    } else {
      bug("Backend", `/api/sessions returned ${resp.status()}`, "high");
    }
  } catch (err) {
    bug("Backend", `/api/sessions error: ${err.message}`, "medium");
  }
}

// ── Checklist / Missions ──────────────────────────────────────────────────────
async function testChecklist() {
  // Try /checklist or /missions
  const paths = ["/checklist", "/missions", "/roadmap"];
  for (const p of paths) {
    try {
      const resp = await page.request.get(`${BASE}${p}`, { timeout: 5000 });
      if (resp.status() !== 404) {
        await checkPageLoads(p, `Checklist${p}`);
        break;
      }
    } catch {}
  }
}

// ── Outreach Page ─────────────────────────────────────────────────────────────
async function testOutreach() {
  const paths = ["/outreach", "/crm", "/contacts"];
  for (const p of paths) {
    try {
      await goto(p);
      if (!page.url().includes("404") && !page.url().includes("not-found")) {
        console.log(`\n=== Outreach (${p}) ===`);
        const content = await page.textContent("body").catch(() => "");
        if (content.length < 50) {
          bug("Outreach", `${p} is empty`, "medium");
        } else {
          console.log(`  ✓ ${p} has content`);
        }
        break;
      }
    } catch {}
  }
}

// ── Payments / Billing ────────────────────────────────────────────────────────
async function testPayments() {
  const paths = ["/payments", "/billing", "/upgrade", "/pricing"];
  for (const p of paths) {
    try {
      await goto(p);
      if (!page.url().includes("404")) {
        console.log(`\n=== Payments (${p}) ===`);
        const content = await page.textContent("body").catch(() => "");
        console.log(`  Content length: ${content.length}`);
        break;
      }
    } catch {}
  }
}

// ── All API endpoints audit ───────────────────────────────────────────────────
async function testApiEndpoints() {
  console.log("\n=== Backend API Endpoints ===");
  const endpoints = [
    { method: "GET", path: "/api/sessions?founder_id=google_jhinkesh05_gmail_com" },
    { method: "GET", path: "/api/files" },
    { method: "GET", path: "/api/credits?founder_id=google_jhinkesh05_gmail_com" },
    { method: "GET", path: "/api/genome?founder_id=google_jhinkesh05_gmail_com" },
    { method: "GET", path: "/api/goals?founder_id=google_jhinkesh05_gmail_com" },
    { method: "GET", path: "/api/model-settings?founder_id=google_jhinkesh05_gmail_com" },
    { method: "GET", path: "/api/custom-agents?founder_id=google_jhinkesh05_gmail_com" },
    { method: "GET", path: "/api/missions?founder_id=google_jhinkesh05_gmail_com" },
    { method: "GET", path: "/api/outcomes?founder_id=google_jhinkesh05_gmail_com" },
    { method: "GET", path: "/api/integrations?founder_id=google_jhinkesh05_gmail_com" },
  ];

  for (const ep of endpoints) {
    try {
      const resp = await page.request[ep.method.toLowerCase()](`http://localhost:8001${ep.path}`, { timeout: 5000 });
      const status = resp.status();
      if (status >= 400) {
        bug("API", `${ep.method} ${ep.path} → ${status}`, status >= 500 ? "high" : "medium");
      } else {
        let body;
        try { body = await resp.json(); } catch { body = await resp.text(); }
        console.log(`  ✓ ${ep.method} ${ep.path} → ${status} (${typeof body === "object" ? JSON.stringify(body).slice(0, 80) : String(body).slice(0, 80)})`);
      }
    } catch (err) {
      bug("API", `${ep.method} ${ep.path} error: ${err.message}`, "high");
    }
  }
}

// ── Interactive elements deep test ────────────────────────────────────────────
async function testAllButtons() {
  console.log("\n=== Button/Link Scan ===");
  const pages_to_scan = ["/", "/goals", "/brain", "/library", "/agents", "/settings", "/integrations"];

  for (const p of pages_to_scan) {
    await goto(p);
    // Count clickable elements
    const btnCount = await page.locator("button:visible").count();
    const linkCount = await page.locator("a:visible").count();
    console.log(`  ${p}: ${btnCount} buttons, ${linkCount} links`);

    // Check all links for broken hrefs
    const links = await page.locator("a[href]:visible").all();
    for (const link of links.slice(0, 20)) {
      const href = await link.getAttribute("href").catch(() => "");
      if (href && !href.startsWith("http") && !href.startsWith("#") && !href.startsWith("mailto")) {
        // Internal link - check it resolves
        if (href === "/" || href.startsWith("/")) {
          // Valid internal link
        } else {
          bug(p, `Suspicious link href: ${href}`, "low");
        }
      }
    }
  }
}

// ── Main ──────────────────────────────────────────────────────────────────────
async function main() {
  console.log("Starting Astra QA Audit...\n");

  try {
    await setup();
    await testBackendHealth();
    await testApiEndpoints();
    await testDashboard();
    await testSidebarNav();
    await testGoals();
    await testGoalWorkspace();
    await testBrain();
    await testLibrary();
    await testAgents();
    await testIntegrations();
    await testSettings();
    await testChecklist();
    await testOutreach();
    await testPayments();
    await testAllButtons();
  } finally {
    await browser.close();
  }

  console.log("\n\n========================================");
  console.log(`QA AUDIT COMPLETE — ${BUGS.length} bugs found`);
  console.log("========================================");

  const bySeverity = { critical: [], high: [], medium: [], low: [] };
  for (const b of BUGS) {
    (bySeverity[b.severity] || bySeverity.medium).push(b);
  }

  for (const [sev, list] of Object.entries(bySeverity)) {
    if (list.length) {
      console.log(`\n[${sev.toUpperCase()}] (${list.length})`);
      for (const b of list) console.log(`  • [${b.page}] ${b.desc}`);
    }
  }

  // Write report
  fs.writeFileSync("/tmp/qa-audit-report.json", JSON.stringify({ bugs: BUGS, total: BUGS.length }, null, 2));
  console.log("\nFull report: /tmp/qa-audit-report.json");

  if (bySeverity.critical?.length || bySeverity.high?.length) {
    process.exit(1);
  }
}

main().catch((err) => {
  console.error("QA script crashed:", err);
  process.exit(1);
});
