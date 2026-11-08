/* SinceAI demo recorder for the "Build Less, Build Better" script
   (ignore/target-video-script), driven over CDP screencast.

   Configure with environment variables:
     DEMO_BASE_URL   page origin the browser loads        (default http://172.18.0.1:8000)
     DEMO_CDP        Chrome DevTools endpoint             (default http://127.0.0.1:9222)
     DEMO_W/DEMO_H   viewport                             (default 1600x900)
     DEMO_FRAMES     frame output directory               (default <video_demo>/.work/frames)
     DEMO_STAMPS     frame timestamps json                (default <video_demo>/.work/timestamps.json)
     DEMO_CUTS       paused-wait windows json             (default <video_demo>/.work/cuts.json)
     DEMO_SCENES     per-scene decisions json             (default <video_demo>/.work/scenes.json)

   Storyboard (40-45 s): title card; shift supervisor BUILD with receipt;
   plant director REUSE in Finnish + build-less meter; finance controller
   ANSWER; country manager CLARIFY; data steward governance (registry row,
   propose + approve certification, audit log, quality assurance, all test
   questions); end card. English UI, visible cursor overlay with click
   ripples, captions, gliding mouse, human-paced typing.

   Loading-state trimming: during known waits the screencast is paused after a
   short "taste" of the skeleton (chat asks keep up to ~1.5 s of the real
   Gemini-thinking skeleton; other loads flash ~0.4 s) and resumed when
   content is ready. The pause windows are written to cuts.json so the
   assembler can compress exactly those gaps.
   Run from application/tools/video_demo after `npm ci`:
     node recorder.cjs */
const path = require('path');
const fs = require('fs');
const { chromium } = require(require.resolve('playwright-core', { paths: [__dirname] }));

const HERE = __dirname;
const BASE = process.env.DEMO_BASE_URL || 'http://172.18.0.1:8000';
const CDP = process.env.DEMO_CDP || 'http://127.0.0.1:9222';
const W = parseInt(process.env.DEMO_W || '1600', 10);
const H = parseInt(process.env.DEMO_H || '900', 10);
const OUT = process.env.DEMO_FRAMES || path.join(HERE, '.work', 'frames');
const STAMPS = process.env.DEMO_STAMPS || path.join(HERE, '.work', 'timestamps.json');
const CUTS = process.env.DEMO_CUTS || path.join(HERE, '.work', 'cuts.json');
const SCENES = process.env.DEMO_SCENES || path.join(HERE, '.work', 'scenes.json');
const CLICK_BEFORE = parseInt(process.env.DEMO_CLICK_BEFORE || '100', 10);
const CLICK_AFTER = parseInt(process.env.DEMO_CLICK_AFTER || '150', 10);
const TYPE_MS = parseInt(process.env.DEMO_TYPE_MS || '25', 10);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const T0 = Date.now();
const mark = (...a) => console.log(`[t+${((Date.now() - T0) / 1000).toFixed(1)}s]`, ...a);

(async () => {
  fs.rmSync(OUT, { recursive: true, force: true });
  fs.mkdirSync(OUT, { recursive: true });

  const browser = await chromium.connectOverCDP(CDP);
  console.log(`connected to chrome at ${CDP}`);
  const context = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  page.on('pageerror', (e) => console.log('PAGEERROR', e.message));
  page.on('console', (m) => { if (m.type() === 'error') console.log('CONSOLE', m.text()); });

  // Steady repaint driver + English UI: screencast only emits frames on damage,
  // a tiny pulsing pixel keeps a heartbeat even when the page is static.
  await page.addInitScript(() => {
    localStorage.setItem('sinceai-language', 'en');
    document.addEventListener('DOMContentLoaded', () => {
      const d = document.createElement('div');
      d.style.cssText = 'position:fixed;top:0;left:0;width:2px;height:2px;z-index:2147483647;pointer-events:none;';
      d.animate([{ opacity: 0.98 }, { opacity: 0.01 }], { duration: 100, iterations: Infinity });
      document.body.appendChild(d);
    });
  });

  const cdp = await context.newCDPSession(page);
  const stamps = [];
  const cuts = [];
  const scenes = [];
  let capturing = true;
  const screencastParams = { format: 'jpeg', quality: 85, maxWidth: W, maxHeight: H, everyNthFrame: 1 };

  cdp.on('Page.screencastFrame', async (f) => {
    try {
      // Overlay animations make Chrome emit frames far faster than the 12fps
      // output; writing every frame would block the event loop (sync writes)
      // and stretch the timeline. Keep at most ~12fps, always ack.
      const now = Date.now();
      if (!stamps.length || now - stamps[stamps.length - 1] >= 80) {
        const idx = stamps.length;
        fs.writeFileSync(`${OUT}/f${String(idx).padStart(5, '0')}.jpg`, Buffer.from(f.data, 'base64'));
        stamps.push(now);
      }
      await cdp.send('Page.screencastFrameAck', { sessionId: f.sessionId });
    } catch (e) { console.log('frame err', e.message); }
  });

  async function pauseCapture() {
    if (!capturing) return;
    capturing = false;
    await cdp.send('Page.stopScreencast');
  }
  async function resumeCapture() {
    if (capturing) return;
    capturing = true;
    await cdp.send('Page.startScreencast', screencastParams);
    await sleep(150);
  }

  async function trimLoad(tasteMs, waitForFn, settleMs) {
    await sleep(tasteMs);
    const ws = Date.now();
    await pauseCapture();
    await waitForFn();
    await sleep(settleMs);
    cuts.push([ws, Date.now()]);
    await resumeCapture();
  }

  // Chat asks: keep up to tasteMs of the real thinking skeleton, then pause
  // until the answer is ready. If the answer arrives first, nothing is cut.
  async function trimChat(tasteMs, waitForFn, settleMs) {
    const done = waitForFn();
    const winner = await Promise.race([done.then(() => 'done'), sleep(tasteMs).then(() => 'timeout')]);
    if (winner === 'timeout') {
      const ws = Date.now();
      await pauseCapture();
      await done;
      await sleep(settleMs);
      cuts.push([ws, Date.now()]);
      await resumeCapture();
    }
  }

  // Cursor + ripple + caption + card overlays (script section 2.1, idempotent).
  const OVERLAY = `(() => {
    if (window.__demoOverlay) return;
    window.__demoOverlay = true;
    const css = document.createElement('style');
    css.textContent = '#demo-cursor{position:fixed;left:0;top:0;width:30px;height:30px;z-index:2147483647;pointer-events:none;transform:translate(-3px,-2px);transition:transform .05s linear;}'
      + '.demo-ripple{position:fixed;width:56px;height:56px;margin:-28px 0 0 -28px;border-radius:50%;border:5px solid #10a37f;z-index:2147483646;pointer-events:none;animation:demoRipple .8s ease-out forwards;}'
      + '@keyframes demoRipple{0%{transform:scale(.4);opacity:1}55%{transform:scale(1);opacity:1}100%{transform:scale(1.3);opacity:0}}'
      + '#demo-caption{position:fixed;left:50%;top:72px;transform:translateX(-50%);max-width:80%;background:rgba(15,23,42,.88);color:#fff;font:600 24px/1.35 system-ui,sans-serif;padding:14px 26px;border-radius:12px;z-index:2147483645;pointer-events:none;opacity:0;transition:opacity .35s ease;text-align:center;}'
      + '#demo-card{position:fixed;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;background:#0f172a;color:#fff;font-family:system-ui,sans-serif;z-index:2147483644;opacity:0;pointer-events:none;transition:opacity .5s ease;text-align:center;}'
      + '#demo-card h1{font-size:54px;margin:0 0 14px}#demo-card p{font-size:26px;margin:4px;opacity:.85}';
    document.head.appendChild(css);
    const cur = document.createElement('div');
    cur.id = 'demo-cursor';
    cur.innerHTML = '<svg viewBox="0 0 24 24" width="30" height="30"><path d="M3 2l7 19 2.6-8.1L21 10z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    document.body.appendChild(cur);
    document.addEventListener('mousemove', (e) => { cur.style.left = e.clientX + 'px'; cur.style.top = e.clientY + 'px'; }, true);
    document.addEventListener('mousedown', (e) => {
      const r = document.createElement('div'); r.className = 'demo-ripple';
      r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px';
      document.body.appendChild(r); setTimeout(() => r.remove(), 850);
    }, true);
    const cap = document.createElement('div'); cap.id = 'demo-caption'; document.body.appendChild(cap);
    const card = document.createElement('div'); card.id = 'demo-card'; document.body.appendChild(card);
    window.__caption = (t) => { if (!t) { cap.style.opacity = 0; return; } cap.textContent = t; cap.style.opacity = 1; };
    window.__card = (title, ...lines) => {
      if (!title) { card.style.opacity = 0; return; }
      card.innerHTML = '<h1>' + title + '</h1>' + lines.map((l) => '<p>' + l + '</p>').join('');
      card.style.opacity = 1;
    };
  })()`;

  // Motion helpers (script section 2.2). The overlay cursor has a 50ms CSS
  // transition, so a few interpolation steps already look like a glide.
  const cap = (t) => page.evaluate((x) => window.__caption(x), t);
  async function glide(locator, steps = 8) {
    let b = await locator.boundingBox().catch(() => null);
    if (!b) {
      await locator.scrollIntoViewIfNeeded().catch(() => {});
      b = await locator.boundingBox().catch(() => null);
    }
    if (!b) return;
    await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps });
  }
  async function clickSmooth(locator, steps = 8) {
    await glide(locator, steps);
    await sleep(CLICK_BEFORE);
    await page.mouse.down();
    await sleep(70);
    await page.mouse.up();
    await sleep(CLICK_AFTER);
  }
  async function typeSmooth(locator, text) {
    await clickSmooth(locator, 8);
    await locator.pressSequentially(text, { delay: TYPE_MS });
    await sleep(150);
  }
  async function smoothScrollTo(locator) {
    const el = await locator.elementHandle();
    await page.evaluate((h) => h.scrollIntoView({ behavior: 'smooth', block: 'center' }), el);
    await sleep(500);
  }
  async function selectRole(roleId) {
    const sel = page.locator('.role-select-wrap select');
    await clickSmooth(sel, 8);
    await sel.selectOption(roleId);
    await sleep(150);
  }

  let sceneNo = 0;
  async function ask(question, decisionClass) {
    const turnIdx = await page.locator('.turn').count();
    await typeSmooth(page.locator('.ask input'), question);
    await sleep(120);
    await page.keyboard.press('Enter');
    await trimChat(1000,
      () => page.locator('.turn').nth(turnIdx).locator('.decision.' + decisionClass).first()
        .waitFor({ timeout: 60000 }), 150);
    scenes.push({ scene: sceneNo, question, decision: decisionClass });
    mark(`scene ${sceneNo}: asked "${question}" -> ${decisionClass}`);
    return page.locator('.turn').nth(turnIdx);
  }

  // Load the app behind the scenes (the title card covers the first paint).
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded', timeout: 25000 });
  await page.waitForSelector('.card', { timeout: 25000 });
  await page.evaluate(OVERLAY);
  await page.mouse.move(1100, Math.round(H / 2));   // park cursor centre-right

  // ---------------- Scene 1: title card ----------------
  sceneNo = 1;
  await page.evaluate(() => window.__card(
    'Build Less, Build Better',
    'A governed analytics assistant that reuses before it builds'));
  await cdp.send('Page.startScreencast', screencastParams);
  mark('screencast started');
  for (let i = 0; i < 5; i++) {   // keep damage flowing on the static card
    await page.mouse.move(1100 + i * 3, Math.round(H / 2) + i * 2);
    await sleep(450);
  }
  await sleep(500);
  await page.evaluate(() => window.__card(null));
  await sleep(450);

  // ---------------- Scene 2: shift supervisor BUILD + receipt ----------------
  sceneNo = 2;
  await cap('A shift supervisor asks a question in plain language.');
  await sleep(150);
  await selectRole('vuoropaallikko');
  await trimLoad(300, () => page.waitForSelector('.card', { timeout: 15000 }), 200);
  await clickSmooth(page.locator('.viewtabs button').nth(1), 8);   // Conversation
  await page.waitForSelector('.ask input', { timeout: 8000 });
  await sleep(150);
  const t2 = await ask('Show OTIF by product for this year', 'BUILD');
  await cap('No matching chart exists, so it builds one: canonical KPI, owner and review date.');
  await sleep(1300);
  await clickSmooth(t2.locator('details:has(a[href*="raw.csv"]) summary'), 10);
  await glide(t2.locator('dl.receipt'), 12);      // KPI id + definition + source
  await sleep(2000);
  const csvLink = t2.locator('a[href*="raw.csv"]');
  if (await csvLink.count()) { await glide(csvLink, 8); await sleep(300); }

  // ---------------- Scene 3: plant director REUSE in Finnish + meter ----------------
  sceneNo = 3;
  await cap('The plant director asks the same thing, in different words and in Finnish.');
  await sleep(150);
  await selectRole('tehtaan_johtaja');
  await sleep(150);
  const t3 = await ask('Näytä OTIF tuotteittain tältä vuodelta', 'REUSE');
  await cap('Same intent, same fingerprint: the existing chart is reused. Nothing new is built.');
  await glide(t3.locator('.decision'), 12);
  await sleep(1300);
  await glide(page.locator('header .meter'), 10);
  await sleep(1300);

  // ---------------- Scene 4: finance controller ANSWER ----------------
  sceneNo = 4;
  await cap('New roles are configuration, not code. Finance gets a direct answer.');
  await sleep(150);
  await selectRole('finance_controller');
  await sleep(150);
  const t4 = await ask('What is our forecast variance right now?', 'ANSWER');
  await cap('A one-off question gets an answer, not another dashboard.');
  await glide(t4.locator('.decision'), 12);
  await sleep(1300);

  // ---------------- Scene 5: country manager CLARIFY ----------------
  sceneNo = 5;
  await selectRole('country_manager_fi');
  await sleep(150);
  const t5 = await ask('Show employee satisfaction by month', 'CLARIFY');
  await cap('No governed data for this, so it asks instead of guessing.');
  await glide(t5.locator('.decision'), 12);
  await sleep(1300);

  // ---------------- Scene 6: data steward - lifecycle and proof ----------------
  sceneNo = 6;
  await cap('The data steward governs what exists.');
  await sleep(150);
  await selectRole('data_steward');
  await clickSmooth(page.locator('.viewtabs button').nth(0), 8);   // Governance
  await trimLoad(300, () => page.waitForSelector('table', { timeout: 15000 }), 250);
  mark('steward view');

  const row = page.locator('table').first().locator('tbody tr').nth(1);   // row 0 is the header
  const titleB = row.locator('td').first().locator('b');
  const rowTitle = (await titleB.count()
    ? await titleB.first().textContent()
    : await row.locator('td').first().textContent()).trim();
  for (const i of [0, 2, 4]) { await glide(row.locator('td').nth(i), 5); }
  await sleep(300);
  await clickSmooth(row.locator('button:has-text("Propose certification")'), 8);
  mark('certification proposed:', rowTitle);
  await cap('Charts used by several roles are proposed for certification; unused ones for retirement.');

  const approveBtn = page.locator(`tr:has-text("${rowTitle}") button:has-text("Approve")`).first();
  await approveBtn.waitFor({ timeout: 10000 });
  await smoothScrollTo(approveBtn);
  await clickSmooth(approveBtn, 8);
  mark('proposal approved');
  await sleep(500);

  await cap('Every decision is logged with who made it.');
  const auditH2 = page.locator('h2', { hasText: 'Audit log' });
  await smoothScrollTo(auditH2);
  await glide(page.locator('h2', { hasText: 'Audit log' }).locator('~ table').locator('tbody tr').first(), 6);
  await sleep(1200);

  await cap('40 golden questions, Finnish and English, all roles, each run twice against the real model.');
  const qaH2 = page.locator('h2', { hasText: 'Quality assurance' });
  await smoothScrollTo(qaH2);
  const cards = page.locator('.evalcards .card');
  const nCards = Math.min(await cards.count(), 3);
  for (let i = 0; i < nCards; i++) { await glide(cards.nth(i), 6); await sleep(120); }
  await sleep(500);

  await clickSmooth(page.locator('details:has(summary:has-text("All test questions")) summary'), 8);
  await sleep(300);
  await page.mouse.wheel(0, 250);
  await sleep(150);
  await cap('This is how quality is reproduced: same pipeline, same tests, every change.');
  await sleep(1300);

  // ---------------- Scene 7: end card ----------------
  sceneNo = 7;
  await cap(null);
  await page.evaluate(() => window.__card(
    'Build less. Build better.',
    'Same question → same chart',
    'Every answer has a receipt · every chart has an owner',
    'Every model change passes the same tests'));
  for (let i = 0; i < 7; i++) {   // keep damage flowing on the static card
    await page.mouse.move(1100 + i * 3, Math.round(H / 2) + i * 2);
    await sleep(450);
  }
  await sleep(300);

  await cdp.send('Page.stopScreencast');
  await sleep(500);
  fs.mkdirSync(path.dirname(STAMPS), { recursive: true });
  fs.writeFileSync(STAMPS, JSON.stringify(stamps));
  fs.writeFileSync(CUTS, JSON.stringify(cuts));
  fs.writeFileSync(SCENES, JSON.stringify(scenes));
  console.log('frames:', stamps.length, 'span:', ((stamps[stamps.length - 1] - stamps[0]) / 1000).toFixed(1) + 's',
    'cuts:', cuts.length, 'scenes:', scenes.length);

  await context.close();
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
