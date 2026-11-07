// Run with: node tests/frontend/briefing_panel.test.cjs (no npm dependencies).
// The morning briefing side panel must always be visible: the section itself is
// not gated on brief, the inner content keeps its null-guard, and a skeleton
// placeholder shows while the briefing is loading.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');

const staticDir = path.join(__dirname, '../../frontend');
const html = fs.readFileSync(path.join(staticDir, 'index.html'), 'utf8');
const translations = fs.readFileSync(path.join(staticDir, 'i18n.js'), 'utf8');

test('the side panel section is always rendered, not gated on brief', () => {
  assert.ok(html.includes('<section class="panel">'));
  assert.ok(!html.includes('<section class="panel" v-if="brief">'));
});

test('the briefing content keeps its null-guard inside the panel', () => {
  assert.match(html, /<section class="panel">\s*<template v-if="brief">/);
});

test('a skeleton placeholder shows while brief is null', () => {
  assert.ok(html.includes('<div v-else class="skel" role="status" :aria-label="t(\'Haetaan aamubriefingiä…\')">'));
  assert.ok(/v-else class="skel"[\s\S]{0,400}?skeleton sk-val/.test(html));
});

test('the skeleton placeholder keeps a visible translated caption', () => {
  assert.ok(html.includes('<div class="sk-cap">{{ t(\'Haetaan aamubriefingiä…\') }}</div>'));
});

test('the loading placeholder text is translated', () => {
  assert.match(translations, /'Haetaan aamubriefingiä…': 'Loading morning briefing…'/);
});
