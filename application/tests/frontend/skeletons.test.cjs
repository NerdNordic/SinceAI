// Run with: node tests/frontend/skeletons.test.cjs (no npm dependencies).
// Every busy state renders a shape-matching skeleton instead of a bare text
// spinner: the shimmer is themed for dark/light and disabled for reduced
// motion, and each skeleton stays announced via role="status" plus a
// translated caption and aria-label.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const staticDir = path.join(__dirname, '../../frontend');
const html = fs.readFileSync(path.join(staticDir, 'index.html'), 'utf8');
const translations = fs.readFileSync(path.join(staticDir, 'i18n.js'), 'utf8');

const states = [
  ['Haetaan aamubriefingiä…', 'v-else class="skel"'],
  ['Haetaan sertifioituja kaavioita…', 'class="skel" v-if="dashBusy"'],
  ['Gemini tulkitsee kysymystä ja moottori laskee…', 'class="skel" v-if="busy"'],
  ['Ladataan kortin tietoja…', 'v-else-if="modalBusy"'],
  ['Ladataan esikatselua…', 'v-else-if="previewBusy"'],
];

test('skeleton styling defines a themed shimmer that respects reduced motion', () => {
  assert.match(html, /\.skeleton \{ position: relative; overflow: hidden; border-radius: 6px; background: var\(--line\); \}/);
  assert.match(html, /@keyframes skel-shimmer \{ 100% \{ transform: translateX\(100%\); \} \}/);
  assert.match(html, /@media \(prefers-reduced-motion: reduce\) \{ \.skeleton::after \{ animation: none; \} \}/);
  assert.match(html, /:root \{[^{}]*--skel-shine: rgba\(229,238,235,\.08\);/);
  assert.match(html, /:root\[data-theme="light"\] \{[^{}]*--skel-shine: rgba\(255,255,255,\.8\);/);
});

test('every busy state renders one announced skeleton block', () => {
  assert.equal((html.match(/class="skel"/g) || []).length, 5);
  assert.equal((html.match(/role="status" :aria-label="t\('/g) || []).length, 5);
  assert.equal((html.match(/role="status"/g) || []).length, 5);
  assert.ok(!html.includes('class="spinner"'));
});

test('each skeleton keeps its translated caption next to the aria-label', () => {
  for (const [label, marker] of states) {
    assert.ok(html.includes(marker), marker);
    assert.ok(html.includes(`role="status" :aria-label="t('${label}')"`), label);
    assert.ok(html.includes(`<div class="sk-cap">{{ t('${label}') }}</div>`), label);
  }
});

test('skeletons mimic the shapes they replace', () => {
  assert.ok(/v-else class="skel"[\s\S]{0,600}?class="cards"[\s\S]{0,300}?skeleton sk-val[\s\S]{0,200}?skeleton sk-spark/.test(html));
  assert.ok(/class="skel" v-if="dashBusy"[\s\S]{0,400}?class="tiles"[\s\S]{0,300}?skeleton sk-chart/.test(html));
  assert.ok(/class="skel" v-if="busy"[\s\S]{0,400}?skeleton sk-bubble[\s\S]{0,400}?skeleton sk-chart/.test(html));
  assert.ok(/v-else-if="modalBusy"[\s\S]{0,400}?class="skeleton sk-chart sm"/.test(html));
  assert.ok(/v-else-if="previewBusy"[\s\S]{0,400}?class="skeleton sk-chart sm"/.test(html));
  for (const cls of ['skeleton sk-h', 'skeleton sk-l1', 'skeleton sk-l2'])
    assert.ok(html.includes(cls), cls);
});

test('all skeleton captions and labels are translated', () => {
  const context = vm.createContext({});
  vm.runInContext(translations, context);
  for (const [label] of states) {
    assert.ok(vm.runInContext(`Object.hasOwn(ENGLISH, ${JSON.stringify(label)})`, context), label);
  }
});
