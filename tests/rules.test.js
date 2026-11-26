const test = require('node:test');
const assert = require('node:assert/strict');
const R = require('../site/rules.js');

const stock = (symbol, extra = {}) => ({ symbol, name: symbol, market: 'IN', sector: 'IT', lists: [], price: 100, change_pct: 1, ...extra });
const deep = { indicators: { rsi: 25, sma200: 90, hi252: 120, lo252: 60, macd_hist: 1 } };
const ctx = { watch: new Set(['A.NS']), lists: { Mine: ['B.NS'] } };

test('a numeric and an enum condition decide a match, and a missing value is not a match', () => {
  const rule = R.clean({ name: 'Oversold uptrend', mode: 'all', scope: { kind: 'ALL' }, conds: [{ field: 'rsi', op: '<', value: 30 }, { field: 'vs_sma200', op: '>', value: 0 }] });
  const stocks = [stock('A.NS', deep), stock('B.NS', { indicators: { rsi: 55, sma200: 90 } }), stock('C.NS')];
  const { matches, noData } = R.run(rule, stocks, ctx);
  assert.deepEqual(matches, ['A.NS']);
  assert.equal(noData, 1, 'C.NS has no indicators, so the rule could not be decided for it');
});

test('OR matches when any condition holds, AND needs all', () => {
  const conds = [{ field: 'change_pct', op: '>', value: 5 }, { field: 'rsi', op: '<', value: 30 }];
  const stocks = [stock('A.NS', deep)];
  assert.deepEqual(R.run(R.clean({ mode: 'any', conds }), stocks, ctx).matches, ['A.NS']);
  assert.deepEqual(R.run(R.clean({ mode: 'all', conds }), stocks, ctx).matches, []);
});

test('the scope limits a rule to the watchlist, a list or a sector', () => {
  const conds = [{ field: 'price', op: '>', value: 1 }];
  const stocks = [stock('A.NS'), stock('B.NS'), stock('C.NS', { sector: 'Banks' })];
  assert.deepEqual(R.run(R.clean({ conds, scope: { kind: 'WATCH' } }), stocks, ctx).matches, ['A.NS']);
  assert.deepEqual(R.run(R.clean({ conds, scope: { kind: 'LIST', value: 'Mine' } }), stocks, ctx).matches, ['B.NS']);
  assert.deepEqual(R.run(R.clean({ conds, scope: { kind: 'SECTOR', value: 'Banks' } }), stocks, ctx).matches, ['C.NS']);
});

test('readings, 52-week distance and volume are derived from the row', () => {
  const s = stock('A.NS', { ...deep, short: { label: 'Strong Buy', score: 70 }, long: { label: 'Hold', score: 10 }, volume: 3000, avg_volume: 1000 });
  assert.equal(R.test({ field: 'reading_short', op: 'is', value: 'bullish' }, s), true);
  assert.equal(R.test({ field: 'reading_both', op: 'is', value: 'bullish' }, s), false);
  assert.equal(R.test({ field: 'from_high', op: '<', value: 20 }, s), true);
  assert.equal(R.test({ field: 'volume_ratio', op: '>', value: 2.5 }, s), true);
  assert.equal(R.test({ field: 'reading_long', op: 'is', value: 'bullish' }, stock('X.NS')), null);
});

test('clean drops unknown fields, bad numbers and bad operators, and keeps at most six conditions', () => {
  assert.equal(R.clean({ conds: [{ field: 'nope', op: '>', value: 1 }] }), null);
  assert.equal(R.clean({ conds: [{ field: 'rsi', op: '>', value: 'abc' }] }), null);
  assert.equal(R.clean({ conds: [{ field: 'rsi', op: '=', value: 1 }] }), null);
  assert.equal(R.clean({ conds: [{ field: 'macd', op: 'is', value: 'sideways' }] }), null);
  assert.equal(R.clean('x'), null);
  const many = Array.from({ length: 9 }, () => ({ field: 'price', op: '>', value: 1 }));
  assert.equal(R.clean({ conds: many }).conds.length, 6);
  const rule = R.clean({ name: '  x'.repeat(40), conds: [{ field: 'price', op: '>', value: '12.5' }] });
  assert.equal(rule.name.length <= 40, true);
  assert.equal(rule.conds[0].value, 12.5);
});

test('a rule alerts only for stocks that newly join its matches, and not at all on the first check', () => {
  assert.deepEqual(R.newMatches(['A', 'B'], null), []);
  assert.deepEqual(R.newMatches(['A', 'B'], ['A']), ['B']);
  assert.deepEqual(R.newMatches(['A'], ['A']), []);
  assert.deepEqual(R.newMatches(['A'], []), ['A']);
});

test('a description names every condition and the scope', () => {
  const rule = R.clean({ mode: 'any', scope: { kind: 'WATCH' }, conds: [{ field: 'rsi', op: '<', value: 30 }, { field: 'macd', op: 'is', value: 'up' }] });
  assert.equal(R.describe(rule), 'RSI is below 30 OR MACD is Above its signal line, in My watchlist');
});

test('type alerts follow the switches, the watchlist and the age of the notice', () => {
  const now = Date.parse('2026-11-26T05:00:00Z') / 1000;
  const prefs = R.defaultPrefs();
  const notices = [
    { id: '1', type: 'bonus', label: 'Bonus issue', symbol: 'A.NS', name: 'Alpha', title: '1:1', ts: now - 3600 },
    { id: '2', type: 'bonus', symbol: 'Z.NS', name: 'Zed', title: 'x', ts: now - 3600 },
    { id: '3', type: 'upper_circuit', symbol: 'A.NS', name: 'Alpha', title: 'y', ts: now - 3600 },
    { id: '4', type: 'split', symbol: 'A.NS', name: 'Alpha', title: 'old', ts: now - 3 * 86400 },
  ];
  const events = [{ type: 'ex_dividend', symbol: 'A.NS', name: 'Alpha', date: '2026-11-27' }, { type: 'ex_dividend', symbol: 'A.NS', name: 'Alpha', date: '2026-12-20' }];
  const watch = new Set(['A.NS']);
  let got = R.typeAlerts(prefs, watch, notices, events, now);
  assert.deepEqual(got.map((a) => a.id).sort(), ['e|ex_dividend|A.NS|2026-11-27', 'n|1', 'n|3']);
  assert.match(got.find((a) => a.type === 'dividend').text, /tomorrow/);
  got = R.typeAlerts({ ...prefs, circuits: false, dividend: false }, watch, notices, events, now);
  assert.deepEqual(got.map((a) => a.id), ['n|1']);
});

test('52-week alerts name the side once per day', () => {
  const s = stock('A.NS', { price: 120, indicators: { hi252: 120, lo252: 60 } });
  const got = R.rangeAlerts(R.defaultPrefs(), [s, stock('B.NS', { price: 60, indicators: { hi252: 120, lo252: 60 } })], new Set(['A.NS', 'B.NS']), '2026-11-26');
  assert.deepEqual(got.map((a) => a.id), ['r|A.NS|high|2026-11-26', 'r|B.NS|low|2026-11-26']);
  assert.deepEqual(R.rangeAlerts({ range52: false }, [s], new Set(['A.NS']), 'd'), []);
});

test('a settings code round-trips the watchlist, lists, switches and rules', () => {
  const settings = { watch: ['TCS.NS', 'INFY.NS'], lists: { 'Mine ₹': ['A.NS'] }, prefs: { ...R.defaultPrefs(), circuits: false },
    rules: [R.clean({ id: 'r1', name: 'Oversold', mode: 'all', scope: { kind: 'WATCH' }, conds: [{ field: 'rsi', op: '<', value: 30 }] })] };
  const code = R.packSettings(settings);
  assert.match(code, /^SS1:[A-Za-z0-9_-]+$/);
  assert.deepEqual(R.unpackSettings('  ' + code + '  '), settings);
});

test('a bad or hostile settings code is refused or cleaned, and never throws', () => {
  for (const bad of ['', null, 'hello', 'SS1:', 'SS1:@@@@', 'SS1:' + 'A'.repeat(300000), 'SS2:abc']) assert.equal(R.unpackSettings(bad), null);
  const hostile = R.packSettings({ watch: ['A.NS', 5, 'x'.repeat(80)], lists: { ok: ['B.NS', {}] }, prefs: { circuits: 'yes', evil: true }, rules: [{ conds: [{ field: 'nope' }] }, 'x'] });
  const got = R.unpackSettings(hostile);
  assert.deepEqual(got.watch, ['A.NS']);
  assert.deepEqual(got.lists, { ok: ['B.NS'] });
  assert.equal(got.prefs.circuits, true, 'a non-boolean switch keeps its default');
  assert.equal('evil' in got.prefs, false, 'unknown switches are dropped');
  assert.deepEqual(got.rules, []);
});

test('a code inside a message with a link before it is still found', () => {
  const code = R.packSettings({ watch: ['TCS.NS'], lists: {}, prefs: R.defaultPrefs(), rules: [] });
  assert.deepEqual(R.unpackSettings('https://example.com/app ' + code).watch, ['TCS.NS']);
});
