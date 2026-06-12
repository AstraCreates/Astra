import { chromium } from "playwright";
import fs from "node:fs";

const { cookieName, value } = JSON.parse(fs.readFileSync("tests-e2e/cookie.json", "utf8"));
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
await ctx.addCookies([
  { name: cookieName, value, domain: "localhost", path: "/", httpOnly: true, secure: false, sameSite: "Lax" },
  { name: "astra_cookie_notice", value: "acknowledged", domain: "localhost", path: "/" },
]);
const page = await ctx.newPage();
await page.goto("http://localhost:3000/brain", { waitUntil: "domcontentloaded" });
await page.waitForTimeout(2000);

const state = await page.evaluate(() => {
  const btns = [...document.querySelectorAll("button")].map(b => ({
    text: b.textContent?.trim().slice(0, 30),
    ariaLabel: b.getAttribute("aria-label"),
    zIndex: window.getComputedStyle(b).zIndex,
    position: window.getComputedStyle(b).position,
  }));
  const hamburger = btns.find(b => b.ariaLabel?.toLowerCase().includes("menu") || b.text === "☰");
  return { url: location.href, btns, hamburger };
});

console.log("URL:", state.url);
console.log("All buttons:", JSON.stringify(state.btns, null, 2));
console.log("Hamburger:", JSON.stringify(state.hamburger));

if (state.hamburger) {
  // Click it
  const btn = page.getByRole("button", { name: /open menu/i });
  await btn.click();
  await page.waitForTimeout(500);
  const afterClick = await page.evaluate(() => {
    const nav = document.querySelector("nav");
    const navR = nav?.getBoundingClientRect();
    return { navFound: !!nav, navLeft: Math.round(navR?.left ?? -1), navW: Math.round(navR?.width ?? 0) };
  });
  console.log("After click:", JSON.stringify(afterClick));
}

await browser.close();
