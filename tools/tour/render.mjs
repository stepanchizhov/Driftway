// Renders stage.html frame by frame (deterministic), for ffmpeg.
//   node render.mjs frames            -> every frame at 30 fps
//   node render.mjs stills 4 11 22    -> preview stills at those seconds
import { chromium } from "playwright";
import fs from "fs";
import path from "path";
import { pathToFileURL } from "url";

const mode = process.argv[2] ?? "stills";
const FPS = 30;
const here = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Z]:)/, "$1"));
const boxes = JSON.parse(fs.readFileSync(path.join(here, "shots/boxes.json"), "utf8"));
// Each shot's height in app px (images are at 2x).
const sizes = {};
for (const f of fs.readdirSync(path.join(here, "shots"))) {
  if (!f.startsWith("v-") || !f.endsWith(".png")) continue;
  const buf = fs.readFileSync(path.join(here, "shots", f));
  sizes[f.slice(0, -4)] = buf.readUInt32BE(20) / 2;          // PNG IHDR height
}

const browser = await chromium.launch({
  // CHROME_PATH: a Chromium of your own, if Playwright's isn't installed.
  ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}),
  args: ["--allow-file-access-from-files"],
});
const page = await browser.newPage({ viewport: { width: 540, height: 960 }, deviceScaleFactor: 2 });
await page.goto(pathToFileURL(path.join(here, "stage.html")).href);
await page.evaluate(([b, s]) => window.setup(b, s), [boxes, sizes]);
const duration = await page.evaluate(() => window.DURATION);

if (mode === "frames") {
  const dir = path.join(here, "frames");
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir);
  const n = Math.round(duration * FPS);
  for (let i = 0; i < n; i++) {
    await page.evaluate((t) => window.render(t), i / FPS);
    await page.screenshot({ path: path.join(dir, `f${String(i).padStart(5, "0")}.png`) });
    if (i % 150 === 0) console.log(`frame ${i}/${n}`);
  }
  console.log("done", n);
} else if (mode === "range") {
  const [from, to] = process.argv.slice(3).map(Number);
  for (let i = Math.floor(from * FPS); i <= Math.ceil(to * FPS); i++) {
    await page.evaluate((t) => window.render(t), i / FPS);
    await page.screenshot({ path: path.join(here, "frames", `f${String(i).padStart(5, "0")}.png`) });
  }
  console.log("range done");
} else {
  fs.mkdirSync(path.join(here, "stills"), { recursive: true });
  for (const s of process.argv.slice(3).map(Number)) {
    await page.evaluate((t) => window.render(t), s);
    await page.screenshot({ path: path.join(here, "stills", `s${String(s).replace(".", "_")}.png`) });
  }
  console.log("stills done");
}
await browser.close();
