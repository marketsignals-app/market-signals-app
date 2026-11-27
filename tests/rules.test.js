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

test('quality, growth, cash and risk fields read the figures in the right units', () => {
  const s = stock('A.NS', { fundamentals: { roe: 0.183, operating_margin: 0.25, debt_to_equity: 0.4, pe: 20, peg: -1 },
    calc: { rev_cagr3: 12.5, profit_up_years: 3, debt_to_ebitda: 1.2, fcf_cr: 500, ev_ebitda: 11 }, risk: { beta: 1.1, max_drawdown: -0.32 }, indicators: { sma50: 110, sma200: 100, adx: 31, rs126: 8.5 } });
  const t = (field, op, value) => R.test({ field, op, value }, s, {});
  assert.equal(t('roe', '>', 18), true, 'ROE is a fraction in the data and a percent in the rule');
  assert.equal(t('roe', '>', 19), false);
  assert.equal(t('op_margin', '>', 24), true);
  assert.equal(t('fcf_cr', '>', 499), true);
  assert.equal(t('ev_ebitda', '<', 12), true);
  assert.equal(t('fcf_cr', '>', 501), false);
  assert.equal(t('worst_fall', '>', 30), true, 'a fall of 32% is 32, so "more than 30" matches');
  assert.equal(t('beta', '<', 1.2), true);
  assert.equal(t('sma_cross', '>', 9), true);
  assert.equal(t('earn_yield', '>', 4.9), true, 'P/E 20 is a 5% earnings yield');
  assert.equal(t('rev_cagr3', '>', 12), true);
  assert.equal(t('profit_up_years', '>', 2), true);
  assert.equal(t('adx', '>', 25), true);
  assert.equal(t('rs126', '>', 5), true);
  assert.equal(R.test({ field: 'peg', op: '>', value: -5 }, s, {}), null, 'a negative PEG is no figure at all');
  assert.equal(R.test({ field: 'ev_ebitda', op: '>', value: 1 }, { ...s, calc: {} }, {}), null, 'no figure from the engine means no figure, never one taken from Yahoo');
});

test('a bank is not asked about debt, cash flow or margins, and is counted as not applicable', () => {
  const bank = stock('BANK.NS', { fin: 1, fundamentals: { debt_to_equity: 9, roe: 0.14 } });
  const plain = stock('P.NS', { fundamentals: { debt_to_equity: 0.2 } });
  const rule = R.clean({ conds: [{ field: 'debt_equity', op: '<', value: 1 }] });
  assert.deepEqual(R.run(rule, [bank, plain], ctx), { matches: ['P.NS'], noData: 0, notApplicable: 1 });
  const roe = R.clean({ conds: [{ field: 'roe', op: '>', value: 10 }] });
  assert.deepEqual(R.run(roe, [bank], ctx).matches, ['BANK.NS'], 'ROE still applies to a bank');
  assert.deepEqual(R.run(rule, [stock('N.NS')], ctx), { matches: [], noData: 1, notApplicable: 0 });
});

test('sector medians need four stocks and ignore losses and the unclassified', () => {
  const mk = (sector, pe) => stock(sector + pe, { sector, fundamentals: { pe } });
  const medians = R.sectorMedians([mk('IT', 10), mk('IT', 20), mk('IT', 30), mk('IT', 40), mk('IT', -5), mk('Banks', 8), mk('Banks', 9), mk('Other', 5), mk('Other', 6), mk('Other', 7), mk('Other', 8)]);
  assert.deepEqual(medians, { IT: 25 });
  const s = stock('X', { sector: 'IT', fundamentals: { pe: 50 } });
  assert.equal(R.test({ field: 'pe_vs_sector', op: '>', value: 1.9 }, s, { sectorPE: medians }), true);
  assert.equal(R.test({ field: 'pe_vs_sector', op: '>', value: 1 }, s, {}), null);
});

test('a P/E under 2 and a return on equity over 100% are treated as no figure', () => {
  const t = (field, op, value, fundamentals) => R.test({ field, op, value }, stock('A.NS', { fundamentals }), { sectorPE: { IT: 20 } });
  assert.equal(t('pe', '<', 25, { pe: 0.53 }), null, 'a P/E of 0.53 is a distortion, not a bargain');
  assert.equal(t('pe', '<', 25, { pe: 1.99 }), null);
  assert.equal(t('pe', '<', 25, { pe: 2 }), true, 'the limit itself is allowed');
  assert.equal(t('roe', '>', 15, { roe: 1.15 }), null, 'an ROE of 115% is a distortion');
  assert.equal(t('roe', '>', 15, { roe: 1 }), true, '100% is allowed');
  assert.equal(t('earn_yield', '>', 10, { pe: 0.5 }), null, 'an earnings yield of 200% is not real');
  assert.equal(t('earn_yield', '>', 4.9, { pe: 20 }), true);
  assert.equal(R.test({ field: 'pe_vs_sector', op: '<', value: 1 }, stock('B.NS', { sector: 'IT', fundamentals: { pe: 0.5 } }), { sectorPE: { IT: 20 } }), null);
  const rule = R.clean({ conds: [{ field: 'pe', op: '<', value: 25 }] });
  assert.deepEqual(R.run(rule, [stock('X.NS', { fundamentals: { pe: 0.5 } }), stock('Y.NS', { fundamentals: { pe: 12 } })], ctx), { matches: ['Y.NS'], noData: 1, notApplicable: 0 });
});

test('sector medians ignore a P/E under 2', () => {
  const mk = (pe) => stock('S' + pe, { sector: 'IT', fundamentals: { pe } });
  assert.deepEqual(R.sectorMedians([mk(0.4), mk(1.5), mk(10), mk(20), mk(30), mk(40)]), { IT: 25 });
});
