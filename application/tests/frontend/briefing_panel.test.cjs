// Run with: node tests/frontend/briefing_panel.test.cjs (no npm dependencies).
// The morning briefing panel is visible only in dashboard mode and renders
// before the view's main panel (the dashboard for factory roles, governance
// for the data steward). Inside the panel the content keeps its null-guard,
// and a skeleton placeholder shows while the briefing is loading.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');

const staticDir = path.join(__dirname, '../../frontend');
const html = fs.readFileSync(path.join(staticDir, 'index.html'), 'utf8');
const translations = fs.readFileSync(path.join(staticDir, 'i18n.js'), 'utf8');

test('the briefing panel is gated on dashboard mode, not on brief', () => {
  assert.ok(html.includes('<section class="panel" v-if="view === \'dash\'">'));
  assert.ok(!html.includes('<section class="panel" v-if="brief">'));
});

test('the briefing panel renders before the governance and dashboard panels', () => {
  const briefing = html.indexOf('<section class="panel" v-if="view === \'dash\'">');
  const governance = html.indexOf('<div class="panel" v-if="view === \'dash\' && role === \'data_steward\'">');
  const dashboard = html.indexOf('<div class="panel" v-else-if="view === \'dash\'">');
  assert.ok(briefing !== -1);
  assert.ok(governance !== -1);
  assert.ok(dashboard !== -1);
  assert.ok(briefing < governance);
  assert.ok(briefing < dashboard);
});

test('switching back to dashboard mode redraws the briefing sparklines', () => {
  assert.match(html, /async setView\(v\) \{ this\.view = v; this\.clearCharts\(\); if \(v === 'dash'\) \{ await nextTick\(\); this\.drawSparks\(\); this\.loadDash\(\); \} \}/);
});

test('the KPI cards render in a full-width row above the dashboard', () => {
  const briefing = html.indexOf('<section class="panel" v-if="view === \'dash\'">');
  const cards = html.indexOf('<div class="cards">', briefing);
  assert.ok(briefing !== -1);
  assert.ok(cards > briefing);
  assert.match(html, /<section :class="\{ dashcols: showBriefSide \}">/);
});

test('the replenishment items render in a sidebar beside the dashboard', () => {
  const sidebar = html.indexOf('<aside class="panel briefside" v-if="showBriefSide">');
  const items = html.indexOf('<ul class="items"', sidebar);
  const devs = html.indexOf('<div class="devs"', sidebar);
  const dashboard = html.indexOf('<div class="panel" v-else-if="view === \'dash\'">');
  assert.ok(sidebar !== -1);
  assert.ok(items > sidebar);
  assert.ok(devs > items);
  assert.ok(dashboard > sidebar);
});

test('the briefing content keeps its null-guard inside the panel', () => {
  assert.match(html, /<section class="panel" v-if="view === 'dash'">\s*<template v-if="brief">/);
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
