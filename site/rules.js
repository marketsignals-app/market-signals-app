/* Alert rules and alert types. Pure functions, no DOM and no storage, so they can be tested in Node.
 * A stock is any row the app holds: a curated record from data.json or a slim row from index.json. A rule never sees more than the row has;
 * a condition on a value the row lacks is simply false (the row is counted as "no data" by the screen, never guessed). */
(function (root) {
  'use strict';

  const num = (x) => (typeof x === 'number' && Number.isFinite(x) ? x : null);
  const ind = (s) => s.indicators || {};
  const fund = (s) => s.fundamentals || {};
  const sideOf = (label) => (label === 'Buy' || label === 'Strong Buy' ? 'bullish' : label === 'Sell' || label === 'Strong Sell' ? 'bearish' : label ? 'mixed' : null);
  const reading = (s, keys) => {
    const sides = keys.map((k) => sideOf((s[k] || {}).label && s[k].label !== 'N/A' ? s[k].label : null));
    if (sides.some((x) => x === null)) return null;
    return new Set(sides).size === 1 ? sides[0] : 'mixed';
  };
  const gap = (a, b) => (num(a) !== null && num(b) !== null && b !== 0 ? ((a - b) / b) * 100 : null);

  /* deep: the value comes from the indicator file of the other stocks, which the app loads on demand. */
  const NUMBERS = {
    change_pct: ['Change today (%)', 'Price', (s) => num(s.change_pct)],
    price: ['Price', 'Price', (s) => num(s.price)],
    from_high: ['Below 52-week high (%)', 'Price', (s) => { const hi = num(ind(s).hi252); return hi && num(s.price) !== null ? ((hi - s.price) / hi) * 100 : null; }],
    from_low: ['Above 52-week low (%)', 'Price', (s) => gap(s.price, ind(s).lo252)],
    volume_ratio: ['Volume against its 3-month average (times)', 'Price', (s) => (num(s.volume) !== null && num(s.avg_volume) ? s.volume / s.avg_volume : null)],
    cap_cr: ['Market cap (Rs crore)', 'Value', (s) => (num(fund(s).market_cap) !== null && /\.NS$/.test(s.symbol || '') ? fund(s).market_cap / 1e7 : null)],
    pe: ['P/E', 'Value', (s) => num(fund(s).pe)],
    pb: ['P/B', 'Value', (s) => num(fund(s).pb)],
    dividend_yield: ['Dividend yield (%)', 'Value', (s) => (num(s.dividend_yield) !== null ? s.dividend_yield * 100 : null)],
    score_short: ['Weeks-view score', 'Readings', (s) => num((s.short || {}).score)],
    score_long: ['Months-view score', 'Readings', (s) => num((s.long || {}).score)],
    rsi: ['RSI', 'Technical', (s) => num(ind(s).rsi), true],
    vs_sma20: ['Price above 20-day average (%)', 'Technical', (s) => gap(s.price, ind(s).sma20), true],
    vs_sma50: ['Price above 50-day average (%)', 'Technical', (s) => gap(s.price, ind(s).sma50), true],
    vs_sma200: ['Price above 200-day average (%)', 'Technical', (s) => gap(s.price, ind(s).sma200), true],
    momentum: ['6-month return (%)', 'Technical', (s) => (num(ind(s).momentum126) !== null ? ind(s).momentum126 * 100 : null), true],
    swing: ['Daily swing, ATR as % of price', 'Technical', (s) => (num(ind(s).atr) !== null && num(s.price) ? (ind(s).atr / s.price) * 100 : null), true],
  };
  const SIDES = [['bullish', 'Aligned bullish'], ['mixed', 'Mixed'], ['bearish', 'Aligned bearish']];
  const ENUMS = {
    reading_short: ['Weeks-view reading', 'Readings', SIDES, (s) => reading(s, ['short'])],
    reading_long: ['Months-view reading', 'Readings', SIDES, (s) => reading(s, ['long'])],
    reading_both: ['Both readings agree', 'Readings', SIDES, (s) => reading(s, ['short', 'long'])],
    macd: ['MACD', 'Technical', [['up', 'Above its signal line'], ['down', 'Below its signal line']], (s) => (num(ind(s).macd_hist) === null ? null : ind(s).macd_hist > 0 ? 'up' : 'down'), true],
    pressure: ['Buying or selling pressure', 'Technical', [['buy', 'Buying pressure'], ['sell', 'Selling pressure']],
      (s) => (s.pressure && s.pressure.label ? (s.pressure.label.startsWith('Buying') ? 'buy' : s.pressure.label.startsWith('Selling') ? 'sell' : null) : null), true],
    market: ['Market', 'Stock', [['IN', 'India'], ['US', 'United States']], (s) => s.market || null],
  };
  const NUMBER_OPS = [['>', 'is above'], ['<', 'is below']];
  const ENUM_OPS = [['is', 'is'], ['not', 'is not']];
  const ALLOWED = { all: 1, any: 1 };
  const MAX_CONDITIONS = 6;
  const MAX_RULES = 20;

  function fields() {
    return [
      ...Object.entries(NUMBERS).map(([key, v]) => ({ key, label: v[0], group: v[1], type: 'num', deep: !!v[3], get: v[2] })),
      ...Object.entries(ENUMS).map(([key, v]) => ({ key, label: v[0], group: v[1], type: 'enum', options: v[2], deep: !!v[4], get: v[3] })),
    ];
  }
  const FIELD_MAP = Object.fromEntries(fields().map((f) => [f.key, f]));

  /* One condition against one stock. Returns true, false, or null when the stock has no value for the field. */
  function test(cond, stock) {
    const f = FIELD_MAP[cond.field];
    if (!f) return null;
    const v = f.get(stock);
    if (v === null || v === undefined) return null;
    if (f.type === 'num') return cond.op === '>' ? v > cond.value : v < cond.value;
    return cond.op === 'not' ? v !== cond.value : v === cond.value;
  }

  function inScope(scope, stock, ctx) {
    const kind = (scope || {}).kind;
    if (!kind || kind === 'ALL') return true;
    if (kind === 'WATCH') return !!(ctx.watch && ctx.watch.has(stock.symbol));
    if (kind === 'LIST') return ((ctx.lists || {})[scope.value] || []).includes(stock.symbol);
    if (kind === 'SECTOR') return stock.sector === scope.value || (stock.lists || []).includes(scope.value);
    return false;
  }

  /* The stocks that match a rule right now, with how many were left out for lacking a value the rule needs. */
  function run(rule, stocks, ctx) {
    const matches = [];
    let noData = 0;
    for (const s of stocks) {
      if (!inScope(rule.scope, s, ctx || {})) continue;
      const results = rule.conds.map((c) => test(c, s));
      const hit = rule.mode === 'any' ? results.some((r) => r === true) : results.every((r) => r === true);
      if (hit) matches.push(s.symbol);
      else if (results.some((r) => r === null) && (rule.mode === 'any' ? !results.some((r) => r === true) : !results.some((r) => r === false))) noData += 1;
    }
    return { matches, noData };
  }

  const needsDeep = (rule) => rule.conds.some((c) => (FIELD_MAP[c.field] || {}).deep);

  /* A rule from storage or the form: only known fields and operators, finite numbers, a short name and few conditions. Returns null when nothing usable is left. */
  function clean(raw) {
    if (!raw || typeof raw !== 'object') return null;
    const conds = [];
    for (const c of Array.isArray(raw.conds) ? raw.conds : []) {
      const f = c && FIELD_MAP[c.field];
      if (!f) continue;
      if (f.type === 'num') {
        const value = typeof c.value === 'string' && c.value.trim() !== '' ? Number(c.value) : c.value;
        if (num(value) === null || !['>', '<'].includes(c.op)) continue;
        conds.push({ field: c.field, op: c.op, value });
      } else {
        if (!['is', 'not'].includes(c.op) || !f.options.some(([k]) => k === c.value)) continue;
        conds.push({ field: c.field, op: c.op, value: c.value });
      }
      if (conds.length >= MAX_CONDITIONS) break;
    }
    if (!conds.length) return null;
    const scope = raw.scope && ['ALL', 'WATCH', 'LIST', 'SECTOR'].includes(raw.scope.kind) ? { kind: raw.scope.kind, value: raw.scope.value === undefined ? undefined : String(raw.scope.value).slice(0, 60) } : { kind: 'ALL' };
    return { id: String(raw.id || '').slice(0, 40) || null, name: String(raw.name || '').trim().slice(0, 40) || 'My rule', on: raw.on !== false, mode: ALLOWED[raw.mode] ? raw.mode : 'all', scope, conds };
  }

  const scopeText = (scope) => (scope.kind === 'WATCH' ? 'in My watchlist' : scope.kind === 'LIST' ? `in the list ${scope.value}` : scope.kind === 'SECTOR' ? `in ${scope.value}` : 'in the whole market list');
  function describe(rule) {
    const join = rule.mode === 'any' ? ' OR ' : ' AND ';
    const parts = rule.conds.map((c) => {
      const f = FIELD_MAP[c.field];
      if (f.type === 'num') return `${f.label} ${c.op === '>' ? 'is above' : 'is below'} ${c.value}`;
      const label = (f.options.find(([k]) => k === c.value) || [])[1] || c.value;
      return `${f.label} ${c.op === 'not' ? 'is not' : 'is'} ${label}`;
    });
    return `${parts.join(join)}, ${scopeText(rule.scope)}`;
  }

  /* A rule alerts when a stock newly joins its matches, so a stock that stays a match is not announced again, and one that leaves and returns is.
     previous is the list of symbols that matched at the last check, or null when the rule has not been checked yet (then nothing is announced:
     the first check only records the starting point). */
  function newMatches(matches, previous) {
    if (!Array.isArray(previous)) return [];
    const before = new Set(previous);
    return matches.filter((s) => !before.has(s));
  }

  /* Alert types for the stocks of the watchlist. Each type has a key the person can switch on or off. */
  const TYPES = [
    { key: 'reading_bullish', label: 'A reading turns bullish', group: 'Readings' },
    { key: 'reading_bearish', label: 'A reading turns bearish', group: 'Readings' },
    { key: 'news', label: 'Fresh news about the stock', group: 'News' },
    { key: 'dividend', label: 'Ex-dividend date coming up', group: 'Company events' },
    { key: 'results', label: 'Results date coming up', group: 'Company events' },
    { key: 'share_actions', label: 'Split, bonus, rights or buyback', group: 'Company events' },
    { key: 'mergers', label: 'Merger, demerger or scheme', group: 'Company events' },
    { key: 'restrictions', label: 'Suspension, delisting, F&O ban, ASM or GSM', group: 'Exchange notices' },
    { key: 'circuits', label: 'Upper or lower circuit', group: 'Price moves' },
    { key: 'moves', label: 'Gap at the open, surge or crash', group: 'Price moves' },
    { key: 'range52', label: 'Reaches a 52-week high or low', group: 'Price moves' },
  ];
  const TYPE_OF_ANNOUNCEMENT = {
    bonus: 'share_actions', split: 'share_actions', buyback: 'share_actions', rights: 'share_actions', record_date: 'share_actions',
    merger: 'mergers', demerger: 'mergers', scheme: 'mergers', open_offer: 'mergers',
    suspension: 'restrictions', delisting: 'restrictions', fo_ban: 'restrictions', asm: 'restrictions', gsm: 'restrictions',
    upper_circuit: 'circuits', lower_circuit: 'circuits', gap_up: 'moves', gap_down: 'moves', surge: 'moves', crash: 'moves',
  };
  const TYPE_OF_EVENT = { ex_dividend: 'dividend', earnings: 'results', split: 'share_actions', bonus: 'share_actions' };
  const defaultPrefs = () => Object.fromEntries(TYPES.map((t) => [t.key, true]));

  /* The alerts for the watchlist from the exchange notices (announcements.json items) and the dated events (data.json events.items).
     Each alert has a stable id, so one that was shown before is never shown again. nowTs in seconds; notices older than a day are skipped. */
  function typeAlerts(prefs, watch, notices, events, nowTs, daysAhead) {
    const out = [];
    const day = (ts) => new Date((ts + 19800) * 1000).toISOString().slice(0, 10);
    for (const n of notices || []) {
      const type = TYPE_OF_ANNOUNCEMENT[n.type];
      if (!type || !prefs[type] || !watch.has(n.symbol) || !(n.ts >= nowTs - 86400)) continue;
      out.push({ id: `n|${n.id}`, type, symbol: n.symbol, name: n.name, text: `${n.label || n.type}: ${n.title || ''}`.trim(), ts: n.ts });
    }
    const today = Date.parse(day(nowTs));
    for (const e of events || []) {
      const type = TYPE_OF_EVENT[e.type];
      if (!type || !prefs[type] || !watch.has(e.symbol) || !e.date) continue;
      const away = Math.round((Date.parse(e.date) - today) / 86400000);
      if (!(away >= 0 && away <= (daysAhead || 3))) continue;
      const what = { ex_dividend: 'Ex-dividend date', earnings: 'Results', split: 'Stock split', bonus: 'Bonus issue' }[e.type];
      out.push({ id: `e|${e.type}|${e.symbol}|${e.date}`, type, symbol: e.symbol, name: e.name, text: `${what} ${away === 0 ? 'today' : away === 1 ? 'tomorrow' : `in ${away} days`} (${e.date})`, ts: nowTs });
    }
    return out;
  }

  /* 52-week range alerts from the stock rows (one per stock, side and day). */
  function rangeAlerts(prefs, stocks, watch, today) {
    if (!prefs.range52) return [];
    const out = [];
    for (const s of stocks) {
      if (!watch.has(s.symbol) || num(s.price) === null) continue;
      const hi = num(ind(s).hi252), lo = num(ind(s).lo252);
      if (hi && s.price >= hi * 0.999) out.push({ id: `r|${s.symbol}|high|${today}`, type: 'range52', symbol: s.symbol, name: s.name, text: 'At its 52-week high' });
      else if (lo && s.price <= lo / 0.999) out.push({ id: `r|${s.symbol}|low|${today}`, type: 'range52', symbol: s.symbol, name: s.name, text: 'At its 52-week low' });
    }
    return out;
  }


  /* A settings code: the watchlist, own lists, alert switches and rules as one short text, to copy to another device or keep in Telegram's Saved Messages.
     No server and no account are involved; the text is only what is on this device. */
  const PREFIX = 'SS1:';
  const names = (v, max) => (Array.isArray(v) ? v.filter((x) => typeof x === 'string' && x.length > 0 && x.length <= 40).slice(0, max) : []);
  function packSettings(settings) {
    const bytes = new TextEncoder().encode(JSON.stringify(settings));
    let binary = '';
    bytes.forEach((b) => { binary += String.fromCharCode(b); });
    return PREFIX + btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  /* The settings in a code, cleaned, or null when the text is not a code or holds nothing usable. Never throws. */
  function unpackSettings(text) {
    try {
      const raw = String(text || '');
      const found = raw.length > 200000 ? null : /SS1:([A-Za-z0-9_-]+)/.exec(raw);          // a code may arrive inside a message with a link before it
      if (!found) return null;
      const b64 = found[1].replace(/-/g, '+').replace(/_/g, '/');
      const binary = atob(b64 + '='.repeat((4 - (b64.length % 4)) % 4));
      const data = JSON.parse(new TextDecoder().decode(Uint8Array.from(binary, (c) => c.charCodeAt(0))));
      if (!data || typeof data !== 'object') return null;
      const prefs = defaultPrefs();
      for (const key of Object.keys(prefs)) if (data.prefs && typeof data.prefs[key] === 'boolean') prefs[key] = data.prefs[key];
      const lists = {};
      for (const [name, symbols] of Object.entries(data.lists && typeof data.lists === 'object' ? data.lists : {}).slice(0, 30)) if (name.length <= 40) lists[name] = names(symbols, 2000);
      const rules = (Array.isArray(data.rules) ? data.rules : []).slice(0, MAX_RULES).map(clean).filter(Boolean);
      return { watch: names(data.watch, 2000), lists, prefs, rules };
    } catch (e) { return null; }
  }

  const api = { NUMBER_OPS, ENUM_OPS, MAX_CONDITIONS, MAX_RULES, TYPES, fields, test, inScope, run, needsDeep, clean, describe, newMatches, defaultPrefs, typeAlerts, rangeAlerts, sideOf, packSettings, unpackSettings };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.Rules = api;
}(typeof window !== 'undefined' ? window : globalThis));
