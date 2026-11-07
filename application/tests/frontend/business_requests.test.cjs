// Run with: node tests/frontend/business_requests.test.cjs (no npm dependencies).
// The Data Steward's business-requests table: one /api/business-requests fetch is
// stored raw, filtering and the urgency-first ordering happen client-side, and a
// request can be sent straight into the conversation (askFrom switches to chat).
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
  app.$nextTick = async () => {};
  return {app, alerts, requests};
}

const REQUESTS = [
  {request_id: 'REQ-0001', request_date: '2026-09-01T00:00:00', product_context: 'Xarelto', market_context: 'DE',
   request_text: 'Create a Xarelto sales dashboard', urgency: 'normal', status: 'new'},
  {request_id: 'REQ-0002', request_date: '2026-08-01T00:00:00', product_context: 'Nubeqa', market_context: 'US',
   request_text: 'Replace the legacy Tableau workbook', urgency: 'urgent', status: 'triaged'},
  {request_id: 'REQ-0003', request_date: '2026-10-01T00:00:00', product_context: 'Kerendia', market_context: 'JP',
   request_text: 'Build a market access report', urgency: 'urgent', status: 'new'},
  {request_id: 'REQ-0004', request_date: '2026-07-01T00:00:00', product_context: 'Eylea', market_context: 'FI',
   request_text: 'Weekly inventory coverage chart', urgency: 'high', status: 'triaged'},
];

test('filteredRequests puts urgent before high before normal, newest first within a group', () => {
  const {app} = setup(async () => ({ok: true, json: async () => ({})}));
  app.businessRequests = REQUESTS;
  assert.deepEqual(app.filteredRequests.map(r => r.request_id), ['REQ-0003', 'REQ-0002', 'REQ-0004', 'REQ-0001']);
});

test('filters narrow the table client-side', () => {
  const {app} = setup(async () => ({ok: true, json: async () => ({})}));
  app.businessRequests = REQUESTS;
  app.brFilter = {urgency: 'urgent', status: '', product: '', market: '', q: ''};
  assert.deepEqual(app.filteredRequests.map(r => r.request_id), ['REQ-0003', 'REQ-0002']);
  app.brFilter = {urgency: '', status: 'new', product: '', market: '', q: ''};
  assert.deepEqual(app.filteredRequests.map(r => r.request_id), ['REQ-0003', 'REQ-0001']);
  app.brFilter = {urgency: '', status: '', product: 'Eylea', market: '', q: ''};
  assert.deepEqual(app.filteredRequests.map(r => r.request_id), ['REQ-0004']);
  app.brFilter = {urgency: '', status: '', product: '', market: 'DE', q: ''};
  assert.deepEqual(app.filteredRequests.map(r => r.request_id), ['REQ-0001']);
  app.brFilter = {urgency: '', status: '', product: '', market: '', q: 'legacy'};
  assert.deepEqual(app.filteredRequests.map(r => r.request_id), ['REQ-0002']);
  app.brFilter = {urgency: '', status: '', product: '', market: '', q: 'req-0004'};
  assert.deepEqual(app.filteredRequests.map(r => r.request_id), ['REQ-0004']);
  app.brFilter = {urgency: '', status: '', product: '', market: '', q: 'no such request'};
  assert.deepEqual(app.filteredRequests, []);
});

test('refresh as the data steward fetches and stores the business-requests list', async () => {
  const {app, requests} = setup(async (url) => ({ok: true, json: async () => {
    if (url === '/api/roles?language=en') return [{id: 'data_steward', label: 'Data steward'}];
    if (url === '/api/business-requests') return REQUESTS;
    return [];
  }}));
  app.role = 'data_steward';
  await app.refresh();
  assert.equal(app.businessRequests, REQUESTS);
  assert.ok(requests.some(r => r.url === '/api/business-requests'));
});

test('askFrom sends a business request into the conversation and switches the steward to chat', () => {
  const {app} = setup(async () => ({ok: true, json: async () => ({})}));
  app.role = 'data_steward';
  app.view = 'dash';
  app.askFrom(REQUESTS[1].request_text);
  assert.equal(app.view, 'chat');
  assert.equal(app.question, REQUESTS[1].request_text);
});

test('new labels translate for both languages', () => {
  const {app} = setup(async () => ({ok: true, json: async () => ({})}));
  app.language = 'en';
  assert.equal(app.t('Liiketoimintapyynnöt'), 'Business requests');
  assert.equal(app.t('Kysy chatissa'), 'Ask in chat');
  assert.equal(app.t('urgent'), 'urgent');
  app.language = 'fi';
  assert.equal(app.t('Liiketoimintapyynnöt'), 'Liiketoimintapyynnöt');
  assert.equal(app.t('urgent'), 'kiireellinen');
  assert.equal(app.t('high'), 'korkea');
  assert.equal(app.t('triaged'), 'triagattu');
});

test('the steward governance view contains the business-requests table with filters and actions', () => {
  assert.ok(html.includes("<h2 style=\"margin-top:20px\">{{ t('Liiketoimintapyynnöt') }}</h2>"));
  assert.match(html, /v-for="r in filteredRequests"/);
  assert.match(html, /v-if="!filteredRequests\.length"/);
  assert.match(html, /@click="askFrom\(r\.request_text\)"/);
  assert.match(html, /v-model="brFilter\.q"/);
});

test('the data steward gets a governance tab and a shared conversation tab', () => {
  assert.match(html, /<button v-if="role === 'data_steward'"[^>]*>\{\{ t\('Hallinta'\) \}\}<\/button>/);
  assert.equal((html.match(/class="viewtabs"/g) || []).length, 1);
  assert.match(html, /<div class="panel" v-if="view === 'dash' && role === 'data_steward'">/);
  assert.match(html, /<div class="panel" v-else-if="view === 'dash'">/);
  assert.match(html, /<div class="panel chat" v-else>/);
});
