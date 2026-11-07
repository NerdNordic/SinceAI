// Run with: node tests/frontend/chart_colors.test.cjs (no npm dependencies).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const staticDir = path.join(__dirname, '../../frontend');
const html = fs.readFileSync(path.join(staticDir, 'index.html'), 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(match => match[1]);
const translations = fs.readFileSync(path.join(staticDir, 'i18n.js'), 'utf8');

function setup() {
  const cssVars = {
    '--muted': '#a5b8b1', '--line': '#3b5048', '--forecast': '#f0c078',
    '--chart-palette': '#73d9b4, #9cc5ff, #f0c078, #c6a5ed',
  };
  let options;
  const context = vm.createContext({
    window: {addEventListener() {}},
    document: {documentElement: {lang: 'en', dataset: {}}, title: '', getElementById: () => null},
    getComputedStyle: () => ({getPropertyValue: name => cssVars[name] || ''}),
    localStorage: {getItem: () => null, setItem() {}},
    alert: () => {},
    Vue: {createApp(value) { options = value; return {mount() {}}; }, nextTick: async () => {}},
    fetch: async () => ({ok: true, json: async () => ({})}),
  });
  vm.runInContext(scripts[0], context);
  vm.runInContext(translations, context);
  vm.runInContext(scripts[1], context);
  const app = options.data();
  for (const [key, method] of Object.entries(options.methods)) app[key] = method.bind(app);
  for (const [key, get] of Object.entries(options.computed)) Object.defineProperty(app, key, {get: get.bind(app)});
  app.$refs = {};
  return {app, context};
}

test('mixHex interpolates channels and clamps at the ends', () => {
  const {context} = setup();
  assert.equal(context.mixHex('#000000', '#ffffff', 0), '#000000');
  assert.equal(context.mixHex('#000000', '#ffffff', 1), '#ffffff');
  assert.equal(context.mixHex('#000000', '#ffffff', 0.5), '#808080');
  assert.equal(context.mixHex('#730000', '#00ff00', 0.5), '#3a8000');
});

test('forecastColors keeps null and zero at base color, blends positive shares', () => {
  const {context} = setup();
  assert.deepEqual(context.forecastColors([null, 0, 1], '#73d9b4', '#f0c078'),
                   ['#73d9b4', '#73d9b4', '#f0c078']);
  assert.equal(context.forecastColors([0.5], '#73d9b4', '#f0c078')[0],
               context.mixHex('#73d9b4', '#f0c078', 0.5));
  assert.deepEqual(context.forecastColors([2, -1], '#73d9b4', '#f0c078'), ['#f0c078', '#73d9b4']);
});

test('applyChartTheme colors only datasets that carry a forecast share', () => {
  const {context} = setup();
  const mk = (type, datasets) => ({
    data: {datasets}, options: {plugins: {legend: {labels: {}}}, scales: {y: {ticks: {}, grid: {}, border: {}}}},
    config: {type}, updated: 0, update() { this.updated++; },
  });
  const line = mk('line', [{forecastShare: [0, 1, 0.5, null]}, {}]);
  context.applyChartTheme(line);
  assert.equal(line.data.datasets[0].borderColor, '#73d9b4');
  assert.deepEqual(line.data.datasets[0].pointBackgroundColor,
                   ['#73d9b4', '#f0c078', context.mixHex('#73d9b4', '#f0c078', 0.5), '#73d9b4']);
  assert.deepEqual(line.data.datasets[0].pointBorderColor, line.data.datasets[0].pointBackgroundColor);
  assert.equal(line.data.datasets[1].pointBackgroundColor, undefined);

  const bar = mk('bar', [{forecastShare: [1, 0]}]);
  context.applyChartTheme(bar);
  assert.deepEqual(bar.data.datasets[0].backgroundColor, ['#f0c078cc', '#73d9b4cc']);

  const plain = mk('line', [{}, {}]);
  context.applyChartTheme(plain);
  assert.equal(plain.data.datasets[0].backgroundColor, '#73d9b4');
  assert.equal(plain.data.datasets[1].backgroundColor, '#9cc5ff');
});

test('hasForecast detects any positive share and legends localize', () => {
  const {app} = setup();
  assert.equal(app.hasForecast({datasets: [{forecastShare: [0, 0.5]}]}), true);
  assert.equal(app.hasForecast({datasets: [{forecastShare: [1]}]}), true);
  assert.equal(app.hasForecast({datasets: [{forecastShare: [0, null]}, {}]}), false);
  assert.equal(app.hasForecast({datasets: [{}]}), false);
  assert.equal(app.hasForecast(null), false);

  app.language = 'en';
  assert.equal(app.legendActual, 'Actual (actual-like)');
  assert.equal(app.legendForecast, 'Forecast (forecast-like)');
  assert.equal(app.legendBlend, 'Blended color = partially forecast-based');
  app.language = 'fi';
  assert.equal(app.legendActual, 'Toteuma (actual-like)');
  assert.equal(app.legendForecast, 'Ennuste (forecast-like)');
  assert.equal(app.legendBlend, 'Sekoittunut väri = osittain ennusteperäistä');
});

test('forecastTooltipLine names the provenance of the hovered point', () => {
  const {app} = setup();
  const ctx = (share, i) => ({chart: {data: {datasets: [{forecastShare: share}]}}, datasetIndex: 0, dataIndex: i});
  app.language = 'en';
  assert.equal(app.forecastTooltipLine(ctx([0, 1, 0.49, null], 0)), 'Actual (actual-like)');
  assert.equal(app.forecastTooltipLine(ctx([0, 1, 0.49, null], 1)), 'Forecast (forecast-like)');
  assert.equal(app.forecastTooltipLine(ctx([0, 1, 0.49, null], 2)), 'Partially forecast-based: 49 %');
  assert.equal(app.forecastTooltipLine(ctx([0, 1, 0.49, null], 3)), 'Actual (actual-like)');
  assert.equal(app.forecastTooltipLine(ctx([0, 0], 0)), '');
  assert.equal(app.forecastTooltipLine(ctx([null], 0)), '');
  assert.equal(app.forecastTooltipLine({chart: {data: {datasets: [{}]}}, datasetIndex: 0, dataIndex: 0}), '');
  app.language = 'fi';
  assert.equal(app.forecastTooltipLine(ctx([1], 0)), 'Ennuste (forecast-like)');
  assert.equal(app.forecastTooltipLine(ctx([1, 0], 1)), 'Toteuma (actual-like)');
  assert.equal(app.forecastTooltipLine(ctx([0.49], 0)), 'Osittain ennusteperäistä: 49 %');
});

test('mkChart wires the forecast tooltip callback into Chart.js options', () => {
  const {app, context} = setup();
  let cfg;
  context.Chart = class {
    constructor(el, config) {
      cfg = config;
      this.config = config;
      this.data = config.data;
      this.options = config.options;
      this.update = () => {};
    }
  };
  app.mkChart(null, {type: 'line', labels: ['2026-01', '2026-02'],
    datasets: [{label: 'Net Sales', data: [1, 2], forecastShare: [0, 0.5]}]}, 'M€');
  assert.equal(typeof cfg.options.plugins.tooltip.callbacks.afterLabel, 'function');
  assert.deepEqual(cfg.data.datasets[0].forecastShare, [0, 0.5]);
  const afterLabel = cfg.options.plugins.tooltip.callbacks.afterLabel;
  assert.equal(afterLabel({chart: {data: {datasets: cfg.data.datasets}}, datasetIndex: 0, dataIndex: 0}),
               'Actual (actual-like)');
  assert.equal(afterLabel({chart: {data: {datasets: cfg.data.datasets}}, datasetIndex: 0, dataIndex: 1}),
               'Partially forecast-based: 50 %');
});
