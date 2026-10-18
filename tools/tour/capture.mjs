// Screens for the tour video, from the app running locally against live
// providers. Public places in Windsor only; "Home" is a stand-in on Datchet's
// village green. Writes shots/v-*.png and shots/boxes.json (tap targets, CSS
// px within each shot).
import { chromium } from "playwright";
import fs from "fs";

const OUT = "shots";
const PART = process.argv[2] ?? "drive";
const boxes = fs.existsSync(`${OUT}/boxes.json`) ? JSON.parse(fs.readFileSync(`${OUT}/boxes.json`, "utf8")) : {};
const browser = await chromium.launch({
  // CHROME_PATH: a Chromium of your own, if Playwright's isn't installed.
  ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}),
  args: ["--lang=en-GB"],
});
const ctx = await browser.newContext({
  viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true,
  // Barry Avenue, Windsor: the riverside road by Alexandra Gardens.
  geolocation: { latitude: 51.4876, longitude: -0.6085 }, permissions: ["geolocation"],
  locale: "en-GB", timezoneId: "Europe/London",
});
await ctx.addInitScript(() => {
  if (localStorage.getItem("driftway.places.v1")) return;
  localStorage.setItem("driftway.places.v1", JSON.stringify([
    { id: "home", label: "Home", lat: 51.4836, lng: -0.5793, isDefault: true },
    { id: "pool", label: "Swimming pool", lat: 51.4857, lng: -0.6214, isDefault: false },
    { id: "gran", label: "Grandma's", lat: 51.4705, lng: -0.6445, isDefault: false },
  ]));
});
const page = await ctx.newPage();
await page.clock.install({ time: new Date("2026-10-20T10:12:00+01:00") });

async function box(name, locator, shotScrollY = 0) {
  const b = await locator.boundingBox();
  const sy = await page.evaluate(() => window.scrollY);
  boxes[name] = { x: b.x, y: b.y + sy - shotScrollY, w: b.width, h: b.height };
  fs.writeFileSync(`${OUT}/boxes.json`, JSON.stringify(boxes, null, 1));
}
async function shot(name, full = false) {
  await page.screenshot({ path: `${OUT}/v-${name}.png`, fullPage: full });
  console.log("shot", name);
}

// 0. The tab bar, once per tab; then hidden in every shot (the video lays it
// over the bottom of the phone).
await page.goto("http://localhost:5173/");
await page.waitForTimeout(1500);
for (const [tab, name] of [["Plan a drive", "plan"], ["Meet up", "meet"], ["Walk", "walk"], ["Still asleep", "sa"]]) {
  await page.getByRole("button", { name: tab }).click();
  await page.waitForTimeout(500);
  await page.locator("nav.tabbar").screenshot({ path: `${OUT}/tab-${name}.png` });
}
await page.addStyleTag({ content: "nav.tabbar { visibility: hidden !important; }" });
await page.waitForTimeout(300);

if (PART === "drive") {
// 1. Still asleep
await shot("sa-a");
await box("sa-45", page.locator(".sa-durations button, .sa-durations label").nth(2));
await box("sa-find", page.getByRole("button", { name: /Find route/ }));
await page.locator(".sa-durations button, .sa-durations label").nth(2).click();
await page.waitForTimeout(300);
await shot("sa-b");

// 2. Plan a drive: a 45-minute round trip
await page.locator("nav.tabbar button", { hasText: "Plan a drive" }).dispatchEvent("click");
await page.waitForTimeout(800);
await shot("plan-a", true);
const chip45 = page.locator(".chip", { hasText: /^45$/ });
await box("plan-45", chip45);
await chip45.click();
await page.waitForTimeout(300);
await shot("plan-b", true);
await box("plan-go", page.locator(".btn-generate"));
await page.locator(".btn-generate").click();
await page.waitForTimeout(250);
await shot("plan-loading");
await page.waitForSelector(".results-head", { timeout: 120000 });
await page.waitForTimeout(800);
await shot("plan-results", true);
await box("card1", page.locator(".card").first());

// 3. Arrive by 10:55 at the swimming pool
await page.goBack();
await page.waitForTimeout(600);
await page.getByText("Go somewhere").click();
await page.waitForTimeout(300);
const poolShortcut = page.locator(".ps-shortcut", { hasText: "Swimming pool" }).last();
await box("arr-pool", poolShortcut);
await shot("arr-a", true);
await poolShortcut.click();
await page.waitForTimeout(300);
await box("arr-by", page.locator(".chip", { hasText: "Arrive by" }));
await shot("arr-b", true);
await page.locator(".chip", { hasText: "Arrive by" }).click();
await page.locator("input[type=time]").fill("10:55");
await page.locator("input[type=time]").blur();
await page.waitForTimeout(300);
await shot("arr-c", true);
await box("arr-ring", page.locator(".duration-ring"));
await box("arr-time", page.locator("input[type=time]"));
await box("arr-go", page.locator(".btn-generate"));
await page.locator(".btn-generate").click();
await page.waitForSelector(".results-head", { timeout: 120000 });
await page.waitForTimeout(800);
await shot("arr-results", true);
await box("arr-leave", page.locator(".tag-ok, .tag-warn").first());

}
if (PART === "drive" || PART === "wakes") {
// 4. What wakes your little one
await page.getByRole("button", { name: "Settings" }).click();
await page.waitForTimeout(600);
const wakes = page.locator("section[aria-labelledby=wakes-title]");
await wakes.scrollIntoViewIfNeeded();
const bumpsWakes = wakes.locator(".chip-group").first().locator(".chip", { hasText: "Wakes them" });
await page.evaluate(() => window.scrollTo(0, 0));
await shot("wakes-a", true);
await box("wakes-bumps", bumpsWakes);
await bumpsWakes.click();
await page.waitForTimeout(300);
await page.evaluate(() => window.scrollTo(0, 0));
await shot("wakes-a2", true);
const lightsFine = wakes.locator(".chip-group").nth(1).locator(".chip", { hasText: "Not at all" });
await box("wakes-lights", lightsFine);
await lightsFine.click();
await page.waitForTimeout(300);
await page.evaluate(() => window.scrollTo(0, 0));
await shot("wakes-b", true);
await box("wakes-section", wakes);
await page.getByText("← Back").click();
await page.waitForTimeout(600);

}
if (PART === "walk") {
// 5. Walk: walks are made as soon as the start is known
await page.locator("nav.tabbar button", { hasText: "Walk" }).dispatchEvent("click");
await page.waitForTimeout(1000);
await shot("walk-a", true);
await page.waitForSelector(".walk-name", { timeout: 120000 }).catch(() => console.log("no walks"));
await page.waitForTimeout(1500);
await shot("walk-b", true);
const walk1 = page.locator("article.walk >> visible=true").first();
await box("walk1b", walk1);
await walk1.locator("summary", { hasText: "Show on map" }).click();
await page.waitForTimeout(5000);
await shot("walk-c", true);
await box("walk1", walk1);
await box("walk1-map", walk1.locator(".leaflet-container").first());

// 6. Meet up
await page.locator("nav.tabbar button", { hasText: "Meet up" }).dispatchEvent("click");
await page.waitForTimeout(1000);
await shot("meet-a", true);
await box("feedback", page.getByRole("button", { name: "Feedback" }));

}
fs.writeFileSync(`${OUT}/boxes.json`, JSON.stringify(boxes, null, 1));
await browser.close();
