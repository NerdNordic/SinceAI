// Run with: node tests/frontend_language.cjs (no npm dependencies).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const staticDir = path.join(__dirname, '../app/static');
const html = fs.readFileSync(path.join(staticDir, 'index.html'), 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(match => match[1]);
const translations = fs.readFileSync(path.join(staticDir, 'i18n.js'), 'utf8');

function setup(saved, blocked = false) {
  const storage = new Map(saved ? [['sinceai-language', saved]] : []);
  const requests = [];
  const alerts = [];
  const root = {lang: 'en', dataset: {}};
  let options;
  const context = vm.createContext({
    document: {documentElement: root, title: '', getElementById: () => null},
    localStorage: {
      getItem(key) { if (blocked) throw Error('Blocked'); return storage.get(key); },
      setItem(key, value) { if (blocked) throw Error('Blocked'); storage.set(key, value); },
    },
    alert: message => alerts.push(message),
    Vue: {createApp(value) { options = value; return {mount() {}}; }, nextTick: async () => {}},
    fetch: async (url, init) => {
      requests.push({url, body: init?.body && JSON.parse(init.body)});
      const data = url.startsWith('/api/ask') ? {decision: 'CHAT', answer: 'answer', session_id: 'test'} :
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
  assert.match(app.examples.tehtaan_johtaja[0], /Mitkä/);
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
