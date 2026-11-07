// Run with: node tests/frontend/clarify.test.cjs (no npm dependencies).
// CLARIFY/abilities answers carry clickable metric chips: the buttons are bound to
// a.suggestions and clicking sends s.question through the normal ask flow.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');

const staticDir = path.join(__dirname, '../../frontend');
const html = fs.readFileSync(path.join(staticDir, 'index.html'), 'utf8');

test('answers with suggestions render clickable metric chips', () => {
  assert.match(html, /<div class="chips" v-if="\(a\.suggestions \|\| \[\]\)\.length">/);
  assert.match(html, /v-for="s in a\.suggestions"/);
  assert.match(html, /@click="question = s\.question; ask\(\)"/);
  assert.match(html, /\{\{ s\.label \}\}/);
});

test('chips reuse the example-chip pattern (same disabled guards)', () => {
  const example = html.match(/<div class="chips"><button v-for="e in examples\[role\]"[^>]*>/)[0];
  const chip = html.match(/<div class="chips" v-if="\(a\.suggestions[^>]*>\n?<button v-for="s in a\.suggestions"[^>]*>/)[0];
  assert.ok(example.includes(':disabled="busy || languageLoading"'));
  assert.ok(chip.includes(':disabled="busy || languageLoading"'));
});
