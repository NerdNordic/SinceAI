// Run with: node tests/frontend/preferences.test.cjs (no npm dependencies).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const staticDir = path.join(__dirname, '../../frontend');
const html = fs.readFileSync(path.join(staticDir, 'index.html'), 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(match => match[1]);
const translations = fs.readFileSync(path.join(staticDir, 'i18n.js'), 'utf8');

function setup(saved, blocked = false, askResponse = null) {
  const storage = new Map(saved ? [['sinceai-language', saved]] : []);
  const requests = [];
  const alerts = [];
  const root = {lang: 'en', dataset: {}};
  let options;
  const context = vm.createContext({
    window: {addEventListener() {}},
    document: {documentElement: root, title: '', getElementById: () => null},
    localStorage: {
      getItem(key) { if (blocked) throw Error('Blocked'); return storage.get(key); },
      setItem(key, value) { if (blocked) throw Error('Blocked'); storage.set(key, value); },
    },
    alert: message => alerts.push(message),
    Vue: {createApp(value) { options = value; return {mount() {}}; }, nextTick: async () => {}},
    fetch: async (url, init) => {
      requests.push({url, body: init?.body && JSON.parse(init.body)});
      const data = url.startsWith('/api/ask') ? askResponse || {decision: 'CHAT', answer: 'answer', session_id: 'test'} :
        url.startsWith('/api/roles') ? [{id: 'tehtaan_johtaja', label: root.lang === 'en' ? 'Plant director' : 'Tehtaan johtaja'}] : {};
      return {ok: true, json: async () => data};
    },
  });
  vm.runInContext(scripts[0], context);
  vm.runInContext(translations, context);
  vm.runInContext(scripts[1], context);
  const app = options.data();
  for (const [key, method] of Object.entries(options.methods)) app[key] = method.bind(app);
  for (const [key, get] of Object.entries(options.computed)) Object.defineProperty(app, key, {get: get.bind(app)});
  app.$refs = {};
  return {app, options, storage, requests, root, alerts};
}

test('English defaults, saved Finnish, invalid preference and blocked storage', async () => {
  for (const [saved, blocked, expected] of [[undefined, false, 'en'], ['fi', false, 'fi'], ['de', false, 'en'], ['fi', true, 'en']]) {
    const {app, options, root} = setup(saved, blocked);
    assert.equal(app.language, expected);
    await options.mounted.call(app);
    assert.equal(root.lang, expected);
    assert.equal(app.t('Lähetä'), expected === 'en' ? 'Send' : 'Lähetä');
  }
});

test('switching localizes UI, examples, dates and requests without losing conversation or theme', async () => {
  const {app, storage, requests, root, alerts} = setup();
  app.sessionId = 'existing';
  app.answers.push({answer: 'Previous answer'});
  const theme = app.theme;
  await app.setLanguage('fi');
  assert.equal(root.lang, 'fi');
  assert.equal(storage.get('sinceai-language'), 'fi');
  assert.equal(app.t('STOCKOUT_RISK'), 'Loppumisriski');
  assert.equal(app.t('__proto__'), '__proto__');
  assert.equal(app.t('month'), 'Kuukausi');
  assert.equal(app.locale, 'fi-FI');
  assert.equal(app.examples, undefined);
  assert.equal(app.theme, theme);
  assert.equal(app.sessionId, 'existing');
  assert.equal(app.answers.length, 1);
  assert.ok(requests.some(r => r.url === '/api/roles?language=fi'));
  assert.ok(requests.some(r => r.url.includes('/api/briefing/tehtaan_johtaja?language=fi')));
  app.question = 'Hello';
  await app.ask();
  assert.equal(requests.find(r => r.url === '/api/ask').body.language, 'fi');
  await app.setLanguage('en');
  assert.equal(app.t('Lähetä'), 'Send');
  assert.equal(app.t('ORDER_NOW'), 'Order now');
  assert.equal(app.t('constructor'), 'constructor');
  assert.equal(app.locale, 'en-GB');
  assert.equal(alerts.length, 0);
});

test('blocked preference writes still allow switching; in-flight requests cannot switch language', async () => {
  const {app} = setup(undefined, true);
  await app.setLanguage('fi');
  assert.equal(app.language, 'fi');
  app.busy = true;
  await app.setLanguage('en');
  assert.equal(app.language, 'fi');
});

test('all literal UI translation keys have English translations', () => {
  const context = vm.createContext({});
  vm.runInContext(translations, context);
  for (const match of html.matchAll(/\bt\('([^']+)'\)/g)) {
    assert.ok(vm.runInContext(`Object.hasOwn(ENGLISH, ${JSON.stringify(match[1])})`, context), match[1]);
  }
});

test('pending clarification survives a language switch and new conversation explicitly abandons it', async () => {
  const {app, requests} = setup();
  app.sessionId = 'pending-session';
  app.pendingRequest = true;
  app.answers = [{decision: 'CLARIFY', answer: 'Choose a metric'}];
  await app.setLanguage('fi');
  assert.equal(app.sessionId, 'pending-session');
  assert.equal(app.pendingRequest, true);
  assert.equal(app.answers.length, 1);
  await app.newChat();
  const abandonment = requests.find(r => r.url === '/api/ask');
  assert.equal(abandonment.body.session_id, 'pending-session');
  assert.equal(abandonment.body.abandon_pending, true);
  assert.equal(app.pendingRequest, false);
  assert.equal(app.sessionId, null);
});

test('busy requests cannot abandon a conversation', async () => {
  const {app, requests} = setup();
  app.sessionId = 'pending-session'; app.pendingRequest = true; app.busy = true;
  assert.equal(await app.newChat(), false);
  assert.equal(app.sessionId, 'pending-session');
  assert.equal(requests.length, 0);
});

test('briefing action displays refreshed role cards, scrolls to them and preserves pending work', async () => {
  const brief = {role: 'Plant director', cards: [{key: 'otif', label: 'Delivery reliability', value: 97.5}]};
  const response = {decision: 'CHAT', answer: 'Here is your current briefing.', session_id: 'existing',
    intake: {pending: true}, action: {name: 'open_briefing', briefing: brief}};
  const {app, requests} = setup('en', false, response);
  let displayed = false;
  app.$refs.briefing = {scrollIntoView() { displayed = true; }};
  app.$refs.input = {scrollIntoView() { assert.fail('must focus the briefing'); }};
  app.sessionId = 'existing'; app.pendingRequest = true; app.question = 'Open teh briefing';
  app.brief = {cards: [{value: 0}]};
  await app.ask();
  assert.deepEqual(app.brief, brief);
  assert.equal(app.brief.cards[0].value, 97.5);
  assert.equal(displayed, true);
  assert.equal(app.sessionId, 'existing');
  assert.equal(app.pendingRequest, true);
  assert.equal(requests.filter(r => r.url === '/api/ask').length, 1);
  assert.match(html, /ref="briefing"/);
  assert.match(html, /v-for="c in brief.cards"/);
});

test('contextual suggestions submit the answer in the same session, role and language', async () => {
  const suggestion = {question_id: 'markets', label: 'Vain Suomi', answer: 'Vain Suomi'};
  const response = {decision: 'CHAT', session_id: 'existing', answer: 'Question', intake: {pending: true,
    questions: [{id: 'markets', text: 'Kaikki markkinat vai tietyt maat?'}]}, suggestions: [suggestion]};
  const {app, requests} = setup('fi', false, response);
  app.sessionId = 'existing'; app.pendingRequest = true; app.question = 'A request';
  await app.ask();
  const current = app.clarificationSuggestions[0];
  assert.equal(current.label, 'Vain Suomi');
  await app.chooseSuggestion(current);
  const body = requests.filter(r => r.url === '/api/ask').at(-1).body;
  assert.equal(body.question, 'Vain Suomi');
  assert.equal(body.session_id, 'existing');
  assert.equal(body.role, 'tehtaan_johtaja');
  assert.equal(body.language, 'fi');
});

test('stale suggestions cannot submit after typing, language change, completion or abandonment', async () => {
  const suggestion = {question_id: 'usage', label: 'One-off answer', answer: 'One-off answer'};
  const {app, requests} = setup();
  app.sessionId = 'existing'; app.pendingRequest = true; app.clarificationSuggestions = [suggestion];
  app.clearSuggestions(); // Same handler used by manual text input.
  await app.chooseSuggestion(suggestion);
  assert.equal(requests.length, 0);
  app.clarificationSuggestions = [suggestion];
  await app.setLanguage('fi');
  assert.equal(app.clarificationSuggestions.length, 0);
  app.clarificationSuggestions = [suggestion];
  app.question = 'A different request';
  await app.ask(); // Fixture returns a completed CHAT with no pending state.
  assert.equal(app.pendingRequest, false);
  assert.equal(app.clarificationSuggestions.length, 0);
  app.pendingRequest = true; app.clarificationSuggestions = [suggestion];
  await app.newChat();
  assert.equal(app.clarificationSuggestions.length, 0);
});

test('only latest question suggestions appear below the input, with plain-text labels', async () => {
  const response = {decision: 'CHAT', session_id: 'existing', answer: 'Question', intake: {pending: true,
    questions: [{id: 'current'}]}, suggestions: [
      {question_id: 'old', label: 'stale', answer: 'stale'},
      {question_id: 'current', label: '<b>plain text</b>', answer: 'current answer'}]};
  const {app} = setup('en', false, response);
  app.question = 'request';
  await app.ask();
  assert.equal(app.clarificationSuggestions.length, 1);
  assert.equal(app.clarificationSuggestions[0].question_id, 'current');
  assert.ok(html.indexOf('v-for="s in clarificationSuggestions"') > html.indexOf('<input v-model="question"'));
  assert.ok(!html.includes('v-for="s in a.suggestions"'));
  assert.ok(!html.includes('examples[role]'));
  assert.ok(!translations.includes('const EXAMPLES'));
  assert.match(html, /chooseSuggestion\(s\)[^>]*>\{\{ s.label \}\}/);
  assert.ok(!html.includes('v-html="s.label"'));
});

test('generation failure leaves manual clarification entry available without suggestions', async () => {
  const response = {decision: 'CHAT', session_id: 'existing', answer: 'Which markets?',
    intake: {pending: true, questions: [{id: 'markets'}]}, suggestions: []};
  const {app, alerts} = setup('en', false, response);
  app.question = 'request';
  await app.ask();
  assert.equal(app.pendingRequest, true);
  assert.equal(app.clarificationSuggestions.length, 0);
  assert.equal(app.busy, false);
  assert.equal(app.answers.at(-1).answer, 'Which markets?');
  assert.equal(alerts.length, 0);
});

test('validated live-response shape populates dynamic suggestions for a combined scope question', async () => {
  const labels = ['Kaikki markkinat ja kaikki tuotteet', 'Vain Suomi, kaikki tuotteet', 'Vain Saksa, kaikki tuotteet'];
  const response = {decision: 'CLARIFY', session_id: 'current-session', answer: 'Haluatko kaikki markkinat ja tuotteet?',
    intake: {pending: true, questions: [{id: 'scope', field: 'scope'}]},
    suggestions: labels.map(label => ({question_id: 'scope', label, answer: label}))};
  const {app, requests} = setup('fi', false, response);
  app.question = 'Mitkä tuotteet ovat loppumisvaarassa?';
  await app.ask();
  assert.deepEqual(Array.from(app.clarificationSuggestions, s => s.label), labels);
  await app.chooseSuggestion(app.clarificationSuggestions[1]);
  const submitted = requests.filter(r => r.url === '/api/ask').at(-1).body;
  assert.equal(submitted.question, 'Vain Suomi, kaikki tuotteet');
  assert.equal(submitted.session_id, 'current-session');
  assert.equal(submitted.language, 'fi');
});
