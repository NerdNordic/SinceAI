/* SinceAI full demo recorder (~2 min storyboard), driven over CDP screencast.
   Configure with environment variables:
     DEMO_BASE_URL   page origin the browser loads        (default http://172.18.0.1:8000)
     DEMO_CDP        Chrome DevTools endpoint             (default http://127.0.0.1:9222)
     DEMO_W/DEMO_H   viewport                             (default 1400x900)
     DEMO_FRAMES     frame output directory               (default <video_demo>/.work/frames)
     DEMO_STAMPS    frame timestamps json                (default <video_demo>/.work/timestamps.json)
   Storyboard: Plant Director briefing + card modal + certified tiles,
   ask flow (REUSE -> BUILD with real Gemini), Data Steward governance
   (registry, preview, proposal approval, audit), Finnish REUSE, theme toggle.
   Run from application/tools/video_demo after `npm ci`:
     node recorder.cjs */
const path = require('path');
const fs = require('fs');
const { chromium } = require(require.resolve('playwright-core', { paths: [__dirname] }));

const HERE = __dirname;
const BASE = process.env.DEMO_BASE_URL || 'http://172.18.0.1:8000';
const CDP = process.env.DEMO_CDP || 'http://127.0.0.1:9222';
const W = parseInt(process.env.DEMO_W || '1400', 10);
const H = parseInt(process.env.DEMO_H || '900', 10);
const OUT = process.env.DEMO_FRAMES || path.join(HERE, '.work', 'frames');
const STAMPS = process.env.DEMO_STAMPS || path.join(HERE, '.work', 'timestamps.json');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  fs.rmSync(OUT, { recursive: true, force: true });
  fs.mkdirSync(OUT, { recursive: true });

  const browser = await chromium.connectOverCDP(CDP);
  console.log(`connected to chrome at ${CDP}`);
  const context = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  page.on('pageerror', (e) => console.log('PAGEERROR', e.message));
  page.on('console', (m) => { if (m.type() === 'error') console.log('CONSOLE', m.text()); });

  // Steady repaint driver: screencast only emits frames on damage; a tiny
  // pulsing pixel keeps a ~10fps heartbeat even when the page is static.
  await page.addInitScript(() => {
    document.addEventListener('DOMContentLoaded', () => {
      const d = document.createElement('div');
      d.style.cssText = 'position:fixed;top:0;left:0;width:2px;height:2px;z-index:2147483647;pointer-events:none;';
      d.animate([{ opacity: 0.98 }, { opacity: 0.01 }], { duration: 100, iterations: Infinity });
      document.body.appendChild(d);
    });
  });

  const cdp = await context.newCDPSession(page);
  const stamps = [];
  cdp.on('Page.screencastFrame', async (f) => {
    try {
      const idx = stamps.length;
      fs.writeFileSync(`${OUT}/f${String(idx).padStart(5, '0')}.jpg`, Buffer.from(f.data, 'base64'));
      stamps.push(Date.now());
      await cdp.send('Page.screencastFrameAck', { sessionId: f.sessionId });
    } catch (e) { console.log('frame err', e.message); }
  });
  await cdp.send('Page.startScreencast', {
    format: 'jpeg', quality: 85, maxWidth: W, maxHeight: H, everyNthFrame: 1,
  });
  console.log('screencast started');

  const ask = async (question, pauseMs) => {
    const before = await page.locator('.turn').count();
    await page.click('.ask input');
    await page.type('.ask input', question, { delay: 40 });
    await sleep(300);
    await page.click('.ask button');
    console.log('asked:', question);
    await page.locator('.turn').nth(before).locator('.decision').waitFor({ timeout: 60000 });
    console.log('answered (decision visible)');
    await sleep(pauseMs);
    return before;
  };

  // ---------------- Act 1: Plant Director briefing ----------------
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded', timeout: 25000 });
  await page.waitForSelector('.card', { timeout: 25000 });
  console.log('briefing visible');
  await sleep(6500);

  await page.click('.card');
  await page.waitForSelector('.modal', { timeout: 8000 });
  await sleep(4500);
  await page.keyboard.press('Escape');
  await sleep(1800);

  await page.mouse.wheel(0, 600);
  await sleep(3000);                       // certified dashboard tiles
  await page.mouse.wheel(0, -600);
  await sleep(1200);

  // ---------------- Act 2: ask flow (Gemini or canned fast responses) ---------
  await page.locator('.viewtabs button').nth(1).click();
  await page.waitForSelector('.ask input', { timeout: 8000 });
  await sleep(1500);

  const t1 = await ask('Show net sales month over month', 7000);   // -> REUSE (certified)
  const turn1 = page.locator('.turn').nth(t1);
  await turn1.locator('details:has(a[href*="raw.csv"])').locator('summary').click();
  console.log('receipt open');
  await sleep(1800);
  await turn1.scrollIntoViewIfNeeded();
  await sleep(7500);

  const t2 = await ask('How many units of Xarelto have we shipped by month?', 8000);  // -> BUILD
  await page.locator('.turn').nth(t2).scrollIntoViewIfNeeded();
  await sleep(3000);

  // ---------------- Act 3: Data Steward governance ----------------
  await page.locator('.role-select-wrap select').selectOption('data_steward');
  await page.locator('.viewtabs button').nth(0).click();           // Hallinta view
  await page.waitForSelector('table', { timeout: 15000 });
  console.log('steward view');
  await sleep(7000);

  await page.locator('button:has-text("Preview")').first().click();
  await page.waitForSelector('.modal', { timeout: 10000 });
  console.log('preview open');
  await sleep(5500);
  await page.locator('.modal .close').click();
  await sleep(1800);

  await page.mouse.wheel(0, 500);
  await sleep(1500);
  await page.locator('button:has-text("Approve")').first().click();
  console.log('proposal approved');
  await sleep(4500);

  await page.mouse.wheel(0, 700);
  await sleep(5000);                       // audit log
  await page.mouse.wheel(0, -1800);
  await sleep(1200);

  // ---------------- Act 4: back to Plant Director, Finnish ----------------
  await page.locator('.role-select-wrap select').selectOption('tehtaan_johtaja');
  await page.waitForSelector('.card', { timeout: 15000 });
  await sleep(4500);

  await page.locator('.roles button:has-text("Suomi")').click();
  console.log('language -> fi');
  await sleep(6000);

  await page.locator('.viewtabs button').nth(1).click();
  await page.waitForSelector('.ask input', { timeout: 8000 });
  await sleep(1200);
  await ask('Montako Xarelon yksikköä on toimitettu kuukausittain?', 7000);  // -> REUSE, in Finnish

  // ---------------- Act 5: theme toggle + end ----------------
  await page.locator('.roles button:has-text("English")').click();
  await sleep(2500);
  await page.locator('header .btn.ghost').first().click();          // light mode
  console.log('theme -> light');
  await sleep(4000);
  await page.locator('header .btn.ghost').first().click();          // back to dark
  await sleep(3000);

  await cdp.send('Page.stopScreencast');
  await sleep(500);
  fs.mkdirSync(path.dirname(STAMPS), { recursive: true });
  fs.writeFileSync(STAMPS, JSON.stringify(stamps));
  console.log('frames:', stamps.length, 'span:', ((stamps[stamps.length - 1] - stamps[0]) / 1000).toFixed(1) + 's');

  await context.close();
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
