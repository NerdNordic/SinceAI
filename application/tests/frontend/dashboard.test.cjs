// Run with: node tests/frontend/dashboard.test.cjs (no npm dependencies).
// loadDash must never leave the dashboard silently broken: a failed fetch alerts
// the user and leaves dash null, and the tiles template guards on dash (TypeError fix).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const staticDir = path.join(__dirname, '../../frontend');
const html = fs.readFileSync(path.join(staticDir, 'index.html'), 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(match => match[1]);
const translations = fs.readFileSync(path.join(staticDir, 'i18n.js'), 'utf8');

function setup(fetchImpl) {
  const alerts = [];
  const requests = [];
  let options;
  const context = vm.createContext({
    window: {addEventListener() {}},
    document: {documentElement: {lang: 'en', dataset: {}}, title: '', getElementById: () => null},
    localStorage: {getItem: () => null, setItem() {}},
    alert: message => alerts.push(String(message)),
    Vue: {createApp(value) { options = value; return {mount() {}}; }, nextTick: async () => {}},
    fetch: async (url, init) => {
      requests.push({url});
      return fetchImpl(url, init);
    },
  });
  vm.runInContext(scripts[0], context);
  vm.runInContext(translations, context);
  vm.runInContext(scripts[1], context);
  const app = options.data();
  for (const [key, method] of Object.entries(options.methods)) app[key] = method.bind(app);
  for (const [key, get] of Object.entries(options.computed)) Object.defineProperty(app, key, {get: get.bind(app)});
  app.$refs = {};
  return {app, alerts, requests};
}

test('loadDash alerts once and leaves dash null when the fetch rejects', async () => {
  const {app, alerts} = setup(async () => { throw Error('Failed to fetch'); });
  app.view = 'dash';
  await app.loadDash();
  assert.equal(app.dash, null);
  assert.equal(app.dashBusy, false);
  assert.equal(alerts.length, 1);
  assert.ok(alerts[0].length > 0);
});

test('loadDash alerts instead of parsing an error body when the status is not ok', async () => {
  const {app, alerts} = setup(async () => ({ok: false, status: 500, json: async () => ({detail: 'boom'})}));
  app.view = 'dash';
  await app.loadDash();
  assert.equal(app.dash, null);
  assert.equal(alerts.length, 1);
});

test('loadDash stores the dashboard and draws one chart per tile', async () => {
  const dash = {tiles: [
    {fingerprint: 'cf-1', chart: {labels: ['2026-01'], datasets: []}, unit: 'M€'},
    {fingerprint: 'cf-2', chart: {labels: ['2026-01'], datasets: []}, unit: 'kpl'},
  ], kpi_ids: ['KPI-001']};
  const {app, alerts, requests} = setup(async () => ({ok: true, json: async () => dash}));
  const drawn = [];
  app.drawChart = (id, chart, unit) => drawn.push([id, unit]);
  app.view = 'dash';
  await app.loadDash();
  assert.equal(app.dash, dash);
  assert.deepEqual(drawn, [['dcf-1', 'M€'], ['dcf-2', 'kpl']]);
  assert.deepEqual(requests.map(r => r.url), ['/api/dashboards/tehtaan_johtaja']);
  assert.equal(alerts.length, 0);
});

test('the tiles container is guarded so a null dash never renders the v-for', () => {
  assert.match(html, /<div class="tiles" v-if="dash">/);
});
