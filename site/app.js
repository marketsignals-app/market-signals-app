'use strict';
(function () {
  const IPO = window.IPO;
  const Rules = window.Rules;
  const REFRESH_MS = 5 * 60 * 1000;
  const CURRENCY = { INR: '₹', USD: '$' };
  const FREQ_CODE = { Monthly: 'M', Quarterly: 'Q', 'Half-yearly': 'H', Yearly: 'Y' };
  const FIXED_LISTS = ['Government-backed', 'High dividend', 'Low debt', 'Low volatility', 'Momentum leaders', 'Breakouts',
    'Strong long-term trend', 'Strong delivery buying', 'Oversold', 'Near 52-week high', 'Near 52-week low', 'New listings'];

  /* ---------- helpers ---------- */
  const $ = (sel, el = document) => el.querySelector(sel);
  const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
  const isNum = (x) => typeof x === 'number' && Number.isFinite(x);

  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key === 'class') el.className = value;
      else if (key.startsWith('on')) el.addEventListener(key.slice(2).toLowerCase(), value);
      else el.setAttribute(key, value === true ? '' : value);
    }
    append(el, kids);
    return el;
  }
  function append(el, kids) {
    for (const kid of kids.flat(Infinity)) {
      if (kid === null || kid === undefined || kid === false) continue;
      el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
  }
  function svg(tag, attrs, ...kids) {
    const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [key, value] of Object.entries(attrs || {})) el.setAttribute(key, value);
    append(el, kids);
    return el;
  }

  const store = {
    get(key, fallback) {
      try { const raw = localStorage.getItem('ss.' + key); return raw === null ? fallback : JSON.parse(raw); } catch (e) { return fallback; }
    },
    set(key, value) { try { localStorage.setItem('ss.' + key, JSON.stringify(value)); } catch (e) { /* storage unavailable */ } },
  };

  const money = (v, cur) => (isNum(v) ? (CURRENCY[cur] || '') + v.toLocaleString(undefined, { maximumFractionDigits: v < 10 ? 3 : 2 }) : '–');
  const signed = (v, digits = 2, suffix = '%') => (isNum(v) ? `${v > 0 ? '+' : ''}${v.toFixed(digits)}${suffix}` : '–');
  const percent = (v, digits = 1) => (isNum(v) ? `${(v * 100).toFixed(digits)}%` : '–');
  const number = (v, digits = 2) => (isNum(v) ? v.toFixed(digits) : '–');
  const big = (v, cur) => {
    if (!isNum(v)) return '–';
    const units = [[1e12, 'T'], [1e9, 'B'], [1e6, 'M']];
    for (const [size, name] of units) if (Math.abs(v) >= size) return (CURRENCY[cur] || '') + (v / size).toFixed(1) + name;
    return (CURRENCY[cur] || '') + v.toFixed(0);
  };
  function ago(minutes) {
    if (!isNum(minutes)) return 'date unknown';
    if (minutes < 60) return `${minutes} min ago`;
    if (minutes < 1440) return `${Math.floor(minutes / 60)} h ago`;
    return `${Math.floor(minutes / 1440)} d ago`;
  }
  const safeUrl = (url) => (typeof url === 'string' && url.startsWith('https://') ? url : null);
  const side = (label) => (label === 'Buy' || label === 'Strong Buy' ? 'buy' : label === 'Sell' || label === 'Strong Sell' ? 'sell' : 'hold');

  /* The horizon choice: weeks view, months-to-years view, or both. With both, a reading counts as bullish or bearish only when the two views agree,
     and anything else is mixed; the score is the average of the two. */
  const hzList = (hz) => (hz === 'both' ? ['short', 'long'] : [hz]);
  const horizonName = (hz) => (hz === 'short' ? 'weeks view' : hz === 'long' ? 'months-to-years view' : 'weeks and months-to-years views');
  const readingSide = (s, hz) => {
    const labels = hzList(hz).map((k) => (s[k] || {}).label).filter((l) => l && l !== 'N/A');
    if (labels.length < hzList(hz).length) return null;
    const sides = new Set(labels.map(side));
    return sides.size === 1 ? [...sides][0] : 'hold';
  };
  const readingScore = (s, hz) => {
    const v = hzList(hz).map((k) => (s[k] || {}).score).filter((x) => typeof x === 'number' && Number.isFinite(x));
    return v.length === hzList(hz).length ? v.reduce((a, b) => a + b, 0) / v.length : null;
  };
  /* With both views chosen, one badge says what they say together. Two badges side by side, one bullish and one bearish, read as a contradiction. */
  const SIDE_WORD = { buy: 'bullish', sell: 'bearish', hold: 'mixed' };
  function badges(s, hz) {
    if (hz !== 'both') return [badge(s[hz])];
    const a = s.short || {}, b = s.long || {};
    const both = readingSide(s, 'both');
    if (both === null) return hzList(hz).map((k) => badge(s[k]));
    const score = readingScore(s, 'both');
    if (both === 'hold' && side(a.label) !== side(b.label)) {
      const el = badge({ label: 'Hold', score: null });
      const detail = `weeks ${SIDE_WORD[side(a.label)]}, months ${SIDE_WORD[side(b.label)]}`;
      el.title = `The two views differ: ${detail}`;
      el.querySelector('.bfull').textContent = 'Views differ';
      return [el, h('div', { class: 'muted small bfull' }, detail)];
    }
    const strong = a.label === b.label && /^Strong/.test(a.label);
    const label = both === 'buy' ? (strong ? 'Strong Buy' : 'Buy') : both === 'sell' ? (strong ? 'Strong Sell' : 'Sell') : 'Hold';
    const el = badge({ label, score: isNum(score) ? Math.round(score) : null });
    el.title = `Both views agree: ${labelText(label)}`;
    return [el];
  }

  /* What each label is shown as. The stored labels stay Buy/Hold/Sell so filters and records keep working. */
  const LABEL_TEXT = { 'Strong Buy': 'Strongly aligned bullish', Buy: 'Aligned bullish', Hold: 'Mixed', Sell: 'Aligned bearish', 'Strong Sell': 'Strongly aligned bearish',
    Subscribe: 'Strong readings', Avoid: 'Weak readings', Neutral: 'Mixed' };
  const labelText = (label) => LABEL_TEXT[label] || label;

  function badge(sig) {
    const label = (sig && sig.label) || 'N/A';
    const cls = label.includes('Buy') ? 'buy' : label.includes('Sell') ? 'sell' : label === 'Hold' ? 'hold' : 'na';
    const shortText = { 'Strong Buy': 'Strong bullish', Buy: 'Bullish', Sell: 'Bearish', 'Strong Sell': 'Strong bearish' }[label] || labelText(label);
    return h('span', { class: `badge ${cls}`, title: labelText(label) }, h('span', { class: 'bfull' }, labelText(label)), h('span', { class: 'bshort' }, shortText),
      isNum(sig && sig.score) ? h('small', null, ` ${sig.score > 0 ? '+' : ''}${sig.score}`) : null);
  }

  /* ---------- state ---------- */
  const S = {
    data: null,
    error: null,
    tab: 'signals',
    others: [], shards: new Map(), shown: {}, catalog: 'loading', catalogInfo: null, sig: '',
    filters: Object.assign({ market: 'ALL', horizon: 'short', signal: 'ALL', list: 'ALL', sector: 'ALL', tech: {}, sort: 'score', view: 'overview', news: 'ALL' }, store.get('filters', {}), { market: 'ALL' }),
    q: '',
    watch: new Set(store.get('watch', [])),
    lists: store.get('lists', {}),
    newsFilters: { tone: 'ALL', sector: 'ALL', official: false, tracked: false, q: '' },
    annFilters: { group: 'ALL', type: 'ALL', main: false, q: '' }, ann: { state: 'idle', data: null },
    profile: Object.assign({ goal: 'balanced', horizon: 'long', risk: 'medium', market: 'ALL' }, store.get('profile', {}), { market: 'ALL' }),
    calc: Object.assign({ capital: 100000, risk: 1 }, store.get('calc', {})),
    notify: store.get('notify', false),
    ipoName: '',
  };
  const saveFilters = () => store.set('filters', S.filters);
  const saveWatch = () => store.set('watch', [...S.watch]);

  /* ---------- toasts and notifications ---------- */
  function toast(text) {
    const el = h('div', { class: 'toast' }, text);
    $('#toasts').append(el);
    setTimeout(() => el.remove(), 9000);
  }
  function announce(text) {
    toast(text);
    try {
      if (S.notify && 'Notification' in window && Notification.permission === 'granted') new Notification('Stock Signals', { body: text });
    } catch (e) { /* notifications unavailable */ }
  }
  /* ---------- alerts: switches for the watchlist, and rules over the whole market list (all checked on this device) ---------- */
  const AL = { prefs: Object.assign(Rules.defaultPrefs(), store.get('alertPrefs', {})), rules: store.get('alertRules', []).map(Rules.clean).filter(Boolean),
    seen: store.get('alertSeen', null), matched: store.get('ruleMatched', {}), log: store.get('alertLog', []), checking: false };
  const newId = () => Math.random().toString(36).slice(2, 10);
  AL.rules.forEach((r) => { if (!r.id) r.id = newId(); });
  const saveRules = () => store.set('alertRules', AL.rules);
  const savePrefs = () => store.set('alertPrefs', AL.prefs);
  const allStocks = () => S.data.stocks.concat(S.others);
  const ruleContext = () => {
    if (!AL.medians || AL.mediansAt !== S.loadedAt) { AL.medians = Rules.sectorMedians(S.data.stocks); AL.mediansAt = S.loadedAt; }
    return { watch: S.watch, lists: S.lists, sectorPE: AL.medians };
  };
  const nameOf = (symbol) => { const x = allStocks().find((r) => r.symbol === symbol); return x ? x.name : symbol; };

  function emitAlerts(items) {
    if (!items.length) return;
    const ts = Math.floor(Date.now() / 1000);
    AL.log = items.map((i) => ({ ts, ...i })).concat(AL.log).slice(0, 200);
    store.set('alertLog', AL.log);
    items.slice(0, 6).forEach((i) => announce(`${i.name || i.symbol}: ${i.text}`));
    if (items.length > 6) toast(`${items.length - 6} more alerts. See the Alerts tab.`);
    if (S.tab === 'alerts') render();
  }

  // A reading that changes side, and fresh news, for the stocks of the watchlist (compared with what was seen on the last visit).
  function readingAndNewsAlerts() {
    const previous = store.get('lastSeen', null);
    const current = {};
    const items = [];
    for (const s of S.data.stocks) {
      if (!S.watch.has(s.symbol)) continue;
      current[s.symbol] = { short: s.short.label, long: s.long.label, news: s.news.fresh.map((a) => a.link || a.title) };
      const before = previous && previous[s.symbol];
      if (!before) continue;
      for (const [key, name] of [['short', 'short-term'], ['long', 'long-term']]) {
        const was = before[key];
        const now = current[s.symbol][key];
        if (!was || was === 'N/A' || now === 'N/A' || side(was) === side(now)) continue;
        const type = side(now) === 'buy' || (side(now) === 'hold' && side(was) === 'sell') ? 'reading_bullish' : 'reading_bearish';
        items.push({ kind: 'type', type, symbol: s.symbol, name: s.name, text: `${name} reading ${labelText(was)} → ${labelText(now)}` });
      }
      for (const a of s.news.fresh) {
        if (!before.news.includes(a.link || a.title)) items.push({ kind: 'type', type: 'news', symbol: s.symbol, name: s.name, text: `News: ${a.title}` });
      }
    }
    store.set('lastSeen', current);
    return items.filter((i) => AL.prefs[i.type]);
  }
  function checkChanges() { emitAlerts(readingAndNewsAlerts()); }

  async function checkAlerts() {
    if (AL.checking || !S.data) return;
    AL.checking = true;
    try {
      const nowTs = Math.floor(Date.now() / 1000);
      const today = new Date(nowTs * 1000 + 19800000).toISOString().slice(0, 10);
      let notices = [];
      if (S.watch.size && Rules.TYPES.some((t) => AL.prefs[t.key] && ['share_actions', 'mergers', 'restrictions', 'circuits', 'moves'].includes(t.key))) {
        try { const r = await fetch('announcements.json', { cache: 'no-store' }); if (r.ok) notices = (await r.json()).items || []; } catch (e) { /* the other alerts still work */ }
      }
      const found = Rules.typeAlerts(AL.prefs, S.watch, notices, (S.data.events || {}).items, nowTs, 3).concat(Rules.rangeAlerts(AL.prefs, allStocks(), S.watch, today));
      const first = AL.seen === null;
      const seen = new Set(AL.seen || []);
      const fresh = found.filter((i) => !seen.has(i.id));
      fresh.forEach((i) => seen.add(i.id));
      AL.seen = [...seen].slice(-1500);
      store.set('alertSeen', AL.seen);
      if (!first) emitAlerts(fresh.map((i) => ({ kind: 'type', ...i })));       // the first check only records what already exists

      const active = AL.rules.filter((r) => r.on);
      if (active.some(Rules.needsDeep)) { await loadExtra(); }
      const items = [];
      for (const rule of active) {
        if (Rules.needsDeep(rule) && S.extra !== 'ready' && S.others.length) continue;       // the indicator file is not here yet: keep the last result
        const { matches } = Rules.run(rule, allStocks(), ruleContext());
        for (const symbol of Rules.newMatches(matches, AL.matched[rule.id]).slice(0, 20)) items.push({ kind: 'rule', rule: rule.name, symbol, name: nameOf(symbol), text: `${rule.name}: now matches` });
        AL.matched[rule.id] = matches;
      }
      store.set('ruleMatched', AL.matched);
      emitAlerts(items);
    } finally { AL.checking = false; }
  }

  /* ---------- data loading ---------- */
  async function load(manual) {
    // The start-up load, a "page became visible" event and the timer can fire together. Only one download runs at a time, and an automatic
    // reload is skipped if the data is under a minute old, so the same 2 MB is never fetched twice in a row.
    if (S.loading || (!manual && S.data && Date.now() - (S.loadedAt || 0) < 60000)) return;
    S.loading = true;
    const button = $('#refresh');
    button.disabled = true;
    const listPromise = fetch('index.json', { cache: 'no-store' }).catch(() => null);      // the other stocks, downloaded at the same time
    try {
      const response = await fetch('data.json', { cache: 'no-store' });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const data = await response.json();
      if (!data || !Array.isArray(data.stocks)) throw new Error('unexpected data');
      S.data = data;
      S.loadedAt = Date.now();
      S.shards.clear();                 // full records are per run, so none from an earlier run is reused
      S.error = null;
      checkChanges();
      if (manual) toast('Data refreshed');
    } catch (err) {
      S.error = S.data ? 'Could not refresh. Showing the data already loaded.' : 'Could not load data. Check your connection and try again.';
    } finally {
      button.disabled = false;
      S.loading = false;
    }
    updateHeader();
    render();
    openFromHash();
    loadCatalog(listPromise);
  }

  /* Every other listed stock: one small row each (index.json), loaded after the dashboard so it never delays it. A stock's full analysis
     is a separate file, fetched only when the stock is opened. */
  const slimStock = (r) => ({ ...r, lists: r.lists || [], tags: [], news: { fresh: [] }, slim: true,
    short: r.short || { label: null, score: null }, long: r.long || { label: null, score: null },
    dividend_yield: r.dividend_yield, dividend_check: r.dividend_check,
    fundamentals: { market_cap: r.cap, pe: r.pe, forward_pe: r.forward_pe, pb: r.pb, eps: r.eps, book_value: r.book_value }, indicators: { hi252: r.high52, lo252: r.low52 },
    pressure: null, patterns: [], flags: r.thin ? ['thin'] : [] });
  /* The indicator values, pattern names, pressure and fundamentals of the other stocks are a second file, fetched the first time something needs them: a technical
     filter, the technical panel, or a column view other than Overview. */
  function loadExtra() {
    if (!S.extraPromise || S.extra === null) S.extraPromise = fetchExtra();
    return S.extraPromise;
  }
  async function fetchExtra() {
    S.extra = 'loading';
    try {
      const response = await fetch('index_extra.json', { cache: 'no-store' });
      if (!response.ok) throw new Error('index_extra.json');
      const stocks = (await response.json()).stocks || {};
      for (const row of S.others) {
        const e = stocks[row.symbol];
        if (!e) continue;
        row.fundamentals = { ...row.fundamentals, ...(e.fund || {}) };
        row.indicators = { ...row.indicators, ...(e.ind || {}) };
        row.pressure = e.pressure ? { label: e.pressure } : null;
        row.patterns = (e.patterns || []).map(([name, bias]) => ({ name, bias }));
        row.risk = e.risk || null; row.calc = e.calc || null; row.fin = e.fin || null;
        row.techLoaded = true;
      }
      S.extra = 'ready';
    } catch (err) { S.extra = 'failed'; }
    if ($('#cats')) updateSignals();
  }
  const needsExtra = () => activeTech().length > 0 || S.filters.view !== 'overview' || S.techOpen;
  async function loadCatalog(prefetched) {
    S.catalog = 'loading';
    S.extra = null;
    S.extraPromise = null;
    if ($('#cats')) updateSignals();
    try {
      const response = await (prefetched || fetch('index.json', { cache: 'no-store' }));
      if (!response || !response.ok) throw new Error('index.json');
      const payload = await response.json();
      const known = new Set(S.data.stocks.map((s) => s.symbol));
      S.others = (payload.stocks || []).filter((r) => !known.has(r.symbol)).map(slimStock);
      S.catalogInfo = { count: S.others.length, analysed: S.others.filter((r) => r.analysed).length };
      S.catalog = 'ready';
      S.catalogLoaded = true;
      openFromHash();
    } catch (err) {
      S.catalog = 'failed';        // the dashboard keeps working with the curated list
    }
    if ($('#cats')) updateSignals();
    checkAlerts();
  }
  async function loadRecord(row) {
    let shard = S.shards.get(row.shard);
    if (!shard) {
      try {
        const response = await fetch(`detail/${row.shard}.json`, { cache: 'no-cache' });
        shard = response.ok ? await response.json() : null;
      } catch (err) { shard = null; }
      if (shard) S.shards.set(row.shard, shard);
    }
    return (shard && shard[row.symbol]) || null;
  }

  function updateHeader() {
    const banner = $('#banner');
    const label = $('#updated');
    const minutes = S.data ? Math.max(0, Math.round((Date.now() - Date.parse(S.data.generated_at)) / 60000)) : null;
    const late = minutes !== null && minutes > STALE_MINUTES && marketsOpenNow();
    const message = S.error || (late ? `The latest data is from ${ago(minutes)} and the markets are open. It should refresh about every 10 minutes, but GitHub sometimes delays runs, so prices and signals may be out of date.` : '');
    banner.hidden = !message;
    banner.textContent = message;
    if (!S.data) { label.textContent = 'No data'; return; }
    label.textContent = `Updated ${ago(minutes)}` + (minutes > 180 && !late ? ' (updates pause when markets are closed)' : '');
  }

  /* India opens at 03:45 UTC and the updates run until 21:00 UTC, Monday to Friday. */
  const STALE_MINUTES = 45;
  function marketsOpenNow(now = new Date()) {
    const day = now.getUTCDay();
    const minute = now.getUTCHours() * 60 + now.getUTCMinutes();
    return day >= 1 && day <= 5 && minute >= 3 * 60 + 45 && minute < 21 * 60;
  }

  /* ---------- shared pieces ---------- */
  function newsList(items, withTopic) {
    if (!items || !items.length) return h('p', { class: 'muted small' }, 'No recent headlines found.');
    return h('ul', { class: 'clean' }, items.map((item) => {
      const url = safeUrl(item.link);
      const title = url ? h('a', { href: url, target: '_blank', rel: 'noopener noreferrer' }, item.title) : item.title;
      return h('li', null,
        title,
        item.relevant === false ? h('span', { class: 'tag', title: 'The headline is not clearly about this company, so it is not treated as news for it' }, 'Related news') : null,
        h('div', { class: 'muted small' }, [item.source, ago(item.age_min), withTopic ? item.topic || item.market : null].filter(Boolean).join(' · ')));
    }));
  }

  function reasonsList(reasons) {
    return h('ul', { class: 'clean reasons' }, (reasons || []).map((r) => h('li', { class: r.tone }, r.text)));
  }

  const slug = (text) => text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

  function section(title, ...kids) {
    return h('section', { class: 'card', id: 'd-' + slug(title) }, h('h3', null, title), ...kids);
  }


  /* ---------- help text: a "?" next to each section heading opens a plain-language note ---------- */
  const HELP = [
    [/^India \(NSE\)$/, 'Every stock in this market for the time frame you chose. The label says how many of the fixed indicator rules point the same way: aligned bullish (most point up), mixed (they disagree) or aligned bearish (most point down). The number is the indicator alignment, from −100 to +100. It describes current conditions. It is not a forecast or a recommendation.'],
    [/^Stock screens$/, 'A short ranked list built from your answers (goal, time frame, risk, market). It filters by readings, fundamentals and risk. It is a screen to study, not personal advice.'],
    [/^Market conditions$/, 'How each market is behaving now, from seven simple checks on its main index. Each check is worth +1, 0 or −1 and the reason is shown. This describes the market. It is not a forecast and not a call on any stock.'],
    [/market conditions$/, 'The seven check scores added up, from −7 to +7. +5 or more is strongly bullish conditions, +2 to +4 bullish, −1 to +1 sideways, −2 to −4 bearish and −5 or less strongly bearish. The bar shows where today sits.'],
    [/^Indexes and global cues/, 'The latest close, today\'s move and the one-month move for the main indexes, volatility indexes, currency, oil, gold and the US 10-year yield. The line is the last 30 sessions. Uptrend means above the 50 and 200-day averages. A high volatility index (VIX above 25) means large swings.'],
    [/^Breadth and sectors$/, 'Breadth shows how many stocks are taking part in a move, not just the index. Sectors show which industries are leading or lagging. Both are counted over the stocks in this app\'s list, not the whole exchange.'],
    [/ breadth$/, 'Advancers rose today and decliners fell. The percentages show how many stocks are above their 20, 50 and 200-day averages. When most stocks are above their averages the move is broad. New 20-day highs and lows count stocks closing above or below the last 20 days\' range.'],
    [/ sectors$/, 'The average move of the stocks in each sector over 1, 5 and 20 trading days, every stock counted the same. The last column is how many stocks are in the sector in this app\'s list.'],
    [/^Upcoming events$/, 'Dates that matter to holders: when results are expected, the ex-dividend date (buy before it to receive the dividend), the dividend payment date, and splits or bonus issues when a prominent news outlet has reported them. Each date shows its sources: YAHOO (a date from Yahoo Finance), NEWS (a headline from a prominent outlet, shown below it) or ESTIMATED (worked out from past payments), and AGREED when two sources give the same date. Companies confirm their dates by notice to the exchange, so check it before acting.'],
    [/^Price accuracy$/, 'Yahoo is the main price source, so its closing prices on the last few completed sessions are compared with an independent source: the official NSE end-of-day file. "Match" means within 0.5%. A stock that differs by more than 2% is flagged and gets no new alerts until the sources agree. This checks completed sessions only. The live price during the session has no free independent source. A price feed that ends a session before the NSE file is marked as behind and gets no new alerts or tracked readings until it catches up.'],
    [/^Recent alerts$/, 'The latest alerts the app has raised: a change in a stock\'s reading, a fresh headline about the stock, or a price reaching its reference or risk level. Use "View analysis" to open the stock.'],
    [/^World and market news/, 'Headlines about markets, interest rates, oil, geopolitics and the economy, from outside news sources. They are not checked by this app.'],
    [/^India IPOs, dates and grey-market premium/, 'Open and upcoming India IPOs with their dates, price band, lot size and subscription. Grey-market premium (GMP) is an unofficial rumour of where the shares may list, and it can be wrong. The listing price and profit or loss are illustrations only.'],
    [/^Sentiment dashboard/, 'EXPERIMENTAL. A rough tone of the news across the market and sectors (-100 to +100, from a word list that has not been validated) and an impact from 0 to 100 (how important the event is, from its type, the source and how recent it is). Repeats are counted once. It describes the news, not the stock, is not used in any reading or alert, and never creates a Buy or Sell reading.'],
    [/^Recently listed stocks/, 'Stocks that have listed recently, found automatically on the NSE list. They need about 60 trading days of history before readings appear.'],
    [/^Check an IPO yourself/, 'Optional. Free sources do not publish an unlisted company\'s financials, so you type the figures here and the same fixed rules check them. It is the one place where you enter data.'],
    [/^IPO checker$/, 'Type in the figures of an IPO from its official documents and the fixed rules turn them into a reading for listing day and for holding long term. The reading is not a recommendation to apply.'],
    [/^Dates, price and grey-market premium$/, 'Optional. Add the dates, price band, lot size and your own grey-market premium figure to see the estimated listing price and profit or loss per lot. The premium is an unofficial rumour and is never used in the reading.'],
    [/^My IPO tracker$/, 'IPOs you saved from the checker. They are kept in this browser only, with their dates and the estimated profit or loss.'],
    [/^Track record$/, 'How the app\'s own bullish and bearish readings played out afterwards, as a plain record. It is not a forecast. Figures from fewer than 30 readings are unreliable.'],
    [/^By reading type$/, 'Results grouped by time frame (weeks view, months-to-years view) and direction (bullish, bearish). "Reference reached" means the price got to the reference level before the volatility risk level or the time limit.'],
    [/^By indicator alignment$/, 'The same results grouped by how strong the alignment was when the alert went out. If stronger alignment does not do better, the rules need review.'],
    [/^By market$/, 'The same results for each market.'],
    [/^Ideas to review$/, 'Observations drawn from the record, for you to judge. The app never changes its own rules.'],
    [/^Which indicators lined up/, 'For each indicator, how readings it supported moved on average compared with readings it opposed. It shows which inputs have been helping.'],
    [/^Latest results$/, 'The most recent readings that ended, with how they ended and the price move.'],
    [/^Open readings$/, 'Readings still running: price at the alert, the reference level and the volatility risk level they are being checked against.'],
    [/^Recent alerts for this stock$/, 'The latest alerts for this stock, with their reference level, volatility risk level and the indicator readings behind them.'],
    [/^Latest headlines$/, 'Headlines from the last few hours that are clearly about this company, shown as published with their source. No judgement of good or bad news is made from the words, and news is never part of a reading. Headlines come from outside sources and are not checked.'],
    [/^(Short-term view|Long-term view)/, 'The label counts how many fixed indicator rules point the same way for this time frame. Weeks view uses trend, momentum, RSI, volume and volume pressure. Months-to-years view uses the 200-day average, whether the 50-day average sits above or below it (alignment, with any crossover in the last 20 sessions named separately), 6-month return, 52-week position and volatility. Readings use completed daily candles. While the market is open, the unfinished candle of the day gets its own provisional reading. The bar runs from −100 to +100.'],
    [/^Buying and selling pressure$/, 'An estimate from trading volume (money flow and the share of volume on up days) of whether buyers or sellers dominated recently. For India it adds the share of shares actually delivered. It is not exchange order-book data.'],
    [/^Position size$/, 'A calculator, not advice. Enter your capital and the share you are willing to lose, and it works out how many shares keep a move to the volatility risk level within that amount. Prices can gap past the level.'],
    [/^Levels and risk$/, 'Support and resistance are price areas from history where the price has turned before. The volatility risk level is 2 times the average daily range from the price. Volatility is the yearly size of swings. The 1-day loss (95%) is a loss a normal day has stayed within on 95% of days. The worst fall is the biggest drop over the last year.'],
    [/^Patterns$/, 'Chart patterns spotted in the latest candles, with whether they lean bullish or bearish. Patterns are weak evidence on their own.'],
    [/^Fundamentals$/, 'Company size, profit, debt and valuation figures, refreshed about once a day. They show "unavailable" when the free source has no data.'],
    [/^Dividends$/, 'Actual dividend payments: how often they are paid, the yield over the last 12 months, special payments and any overdue one. Dividends are not guaranteed.'],
    [/^Peers in the same sector$/, 'Other stocks in this app\'s list from the same sector, to compare readings and valuation.'],
    [/^News$/, 'Recent headlines that are clearly about this company, shown as published with their source and age. They come from outside sources and are not checked. The app does not judge them as good or bad, and they do not change any reading.'],
    [/^How have these rules worked on this stock\?/, 'The same fixed rules run over up to 5 years of this stock, trading at the next open with assumed taxes, fees and slippage, compared with simply holding. The most recent 40% is reported on its own, but it is the same history with the same rules, not an independent test. It is past data only and does not predict the future.'],
    [/^Lists$/, 'Tick the lists this stock belongs to, such as your watchlist or your own lists.'],
  ];
  let helpCount = 0;

  function decorateHelp(root) {
    for (const heading of root.querySelectorAll('h2, h3')) {
      if (heading.querySelector('.helpbtn')) continue;
      const own = [...heading.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join('').trim();
      const entry = HELP.find(([pattern]) => pattern.test(own));
      if (!entry) continue;
      const note = h('p', { class: 'helptext', id: `help-${++helpCount}`, hidden: true }, entry[1]);
      const button = h('button', { type: 'button', class: 'helpbtn', 'aria-expanded': 'false', 'aria-controls': note.id, 'aria-label': `What does "${own}" show?`, title: 'What is this?' }, '?');
      button.addEventListener('click', (e) => {
        e.stopPropagation();
        note.hidden = !note.hidden;
        button.setAttribute('aria-expanded', String(!note.hidden));
      });
      heading.append(' ', button);
      const anchor = heading.parentElement && heading.parentElement.classList.contains('row') ? heading.parentElement : heading;
      anchor.after(note);
    }
  }

  /* Marks a detail-view card to span the full width of the two-column layout. */
  function wide(el) {
    el.classList.add('wide');
    return el;
  }

  function kv(pairs) {
    return h('div', { class: 'kv' }, pairs.map(([k, v]) => h('div', null, h('span', null, k), h('b', null, naOr(v)))));
  }

  /* ---------- signals tab ---------- */
  // Table headers sort the rows: a click sorts by that column (numbers largest first, text A to Z), a second click reverses it.
  function sortValue(s) {
    const f = S.filters;
    if (f.sort === 'name') return s.name;
    if (f.sort === 'price') return s.price;
    if (f.sort === 'change') return s.change_pct;
    if (f.sort === 'dividend') return s.dividend_yield;
    if (typeof f.sort === 'string' && f.sort.startsWith('col:')) {
      const column = extraColumns(f.view).find((c) => 'col:' + c.label === f.sort);
      if (column && column.val) return column.val(s);
    }
    return readingScore(s, f.horizon);
  }
  const defaultDir = (key) => (key === 'name' || key === 'col:Pays' || key === 'col:Last payment' || key === 'col:Pattern' || key === 'col:Pressure' ? 'asc' : 'desc');
  const currentDir = () => S.filters.dir || defaultDir(S.filters.sort);
  function sortBy(key) {
    const f = S.filters;
    f.dir = f.sort === key ? (currentDir() === 'asc' ? 'desc' : 'asc') : defaultDir(key);
    f.sort = key;
    saveFilters(); updateSignals();
  }
  function sortHead(key, label, cls) {
    const f = S.filters, on = f.sort === key || (key === 'score' && !['name', 'price', 'change', 'dividend'].includes(f.sort) && !String(f.sort).startsWith('col:'));
    const dir = on ? currentDir() : null;
    return h('th', { class: cls || '', 'aria-sort': on ? (dir === 'asc' ? 'ascending' : 'descending') : 'none' },
      h('button', { type: 'button', class: 'sorth' + (on ? ' on' : ''), title: `Sort by ${label}`, onclick: () => sortBy(key) }, label, on ? h('span', { class: 'arrow', 'aria-hidden': 'true' }, dir === 'asc' ? ' ▲' : ' ▼') : null));
  }

  // A list (screen, watchlist, own list) and a sector can be combined: a stock must be in both.
  function inList(s, key) {
    if (!key || key === 'ALL') return true;
    if (key === 'WATCH') return S.watch.has(s.symbol);
    if (key.startsWith('C:')) return (S.lists[key.slice(2)] || []).includes(s.symbol);
    return s.lists.includes(key);
  }
  const inSector = (s, sector) => !sector || sector === 'ALL' || s.lists.includes(sector);

  /* Search is a "like" match, not an exact one: case, punctuation and the order of words do not matter ("bajaj auto", "auto bajaj" and "bajaj-auto" all
     find Bajaj Auto), a word can be typed in part ("hdfc ba"), "&" and "and" are the same, and the legal suffix and exchange ending are ignored.
     If nothing matches that way, close matches are shown instead (one or two letters wrong, such as "relaince"), and the page says so. */
  const normText = (text) => String(text || '').toLowerCase().replace(/&/g, ' and ').replace(/\.(ns|bo)$/, '').replace(/[^a-z0-9]+/g, ' ').trim();
  function withinEdits(a, b, max) {
    if (Math.abs(a.length - b.length) > max) return false;
    let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
    for (let i = 1; i <= a.length; i += 1) {
      const row = [i];
      for (let j = 1; j <= b.length; j += 1) row[j] = Math.min(prev[j] + 1, row[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      if (Math.min(...row) > max) return false;
      prev = row;
    }
    return prev[b.length] <= max;
  }
  // A search word matches when a word of the name or the symbol starts with it, or (3 letters or more) it appears inside the name.
  // A symbol is only matched from its start, so "tcs" does not find a stock whose symbol happens to contain those letters.
  function searchKey(s) {
    if (!s._k) {
      const name = normText(s.name), symbol = normText(s.symbol);
      s._k = { name, symbol, compact: symbol.replace(/ /g, ''), words: name.split(' ').concat(symbol.split(' ')) };
    }
    return s._k;
  }
  function matchesQuery(s, tokens, fuzzy) {
    const key = searchKey(s);
    return tokens.every((tok) => key.words.some((w) => w.startsWith(tok)) || (tok.length >= 3 && key.name.includes(tok))
      || (fuzzy && tok.length >= 4 && key.words.some((w) => withinEdits(w.slice(0, tok.length), tok, tok.length >= 7 ? 2 : 1))));
  }
  // How good a match is: 0 the symbol or the whole name, 1 the start of the name or symbol, 2 anything else that matched.
  function matchRank(s, q) {
    const key = searchKey(s), compact = q.replace(/ /g, '');
    if (key.compact === compact || key.name === q) return 0;
    return key.name.startsWith(q) || key.compact.startsWith(compact) ? 1 : 2;
  }

  /* Technical filters. Each one is decided from the stock's own indicator values; a stock without them (not analysed yet) never passes an active one. */
  const PATTERN_NAMES = ['Doji', 'Hammer', 'Shooting star', 'Bullish engulfing', 'Bearish engulfing', 'Morning star', 'Evening star', 'Three white soldiers', 'Three black crows',
    'Bullish harami', 'Bearish harami', 'Inside day', 'Golden cross', 'Death cross', 'MACD bullish cross', 'MACD bearish cross', '20-day breakout', '20-day breakdown',
    'Near 52-week high', 'Near 52-week low', 'Gap up', 'Gap down', 'Tight range', 'Higher highs and lows', 'Lower highs and lows', 'Volume surge'];
  const indOf = (s) => s.indicators || {};
  const aboveAvg = (s, key, want) => (isNum(indOf(s)[key]) && isNum(s.price) ? (want === 'above' ? s.price > indOf(s)[key] : s.price < indOf(s)[key]) : false);
  const rangePos = (s) => (isNum(indOf(s).hi252) && isNum(indOf(s).lo252) && indOf(s).hi252 > indOf(s).lo252 ? (s.price - indOf(s).lo252) / (indOf(s).hi252 - indOf(s).lo252) : null);
  const TECH_FILTERS = [
    ['rsi', 'RSI', [['low', 'Oversold (under 30)'], ['mid', 'Neutral (30 to 70)'], ['high', 'Overbought (over 70)']],
      (s, v) => { const r = indOf(s).rsi; return isNum(r) && (v === 'low' ? r < 30 : v === 'high' ? r > 70 : r >= 30 && r <= 70); }],
    ['sma200', 'Price vs 200-day average', [['above', 'Above'], ['below', 'Below']], (s, v) => aboveAvg(s, 'sma200', v)],
    ['sma50', 'Price vs 50-day average', [['above', 'Above'], ['below', 'Below']], (s, v) => aboveAvg(s, 'sma50', v)],
    ['sma20', 'Price vs 20-day average', [['above', 'Above'], ['below', 'Below']], (s, v) => aboveAvg(s, 'sma20', v)],
    ['macd', 'MACD', [['up', 'Above its signal line'], ['down', 'Below its signal line']], (s, v) => isNum(indOf(s).macd_hist) && (v === 'up' ? indOf(s).macd_hist > 0 : indOf(s).macd_hist < 0)],
    ['mom', '6-month return', [['up', 'Positive'], ['down', 'Negative']], (s, v) => isNum(indOf(s).momentum126) && (v === 'up' ? indOf(s).momentum126 > 0 : indOf(s).momentum126 < 0)],
    ['pos', 'Position in 52-week range', [['high', 'Top 10%'], ['mid', 'Middle'], ['low', 'Bottom 10%']],
      (s, v) => { const x = rangePos(s); return x !== null && (v === 'high' ? x >= 0.9 : v === 'low' ? x <= 0.1 : x > 0.1 && x < 0.9); }],
    ['pressure', 'Buying or selling pressure', [['buy', 'Buying pressure'], ['sell', 'Selling pressure']],
      (s, v) => !!s.pressure && s.pressure.label.startsWith(v === 'buy' ? 'Buying' : 'Selling')],
    ['swing', 'Daily swing (ATR as % of price)', [['low', 'Calm (under 2.5%)'], ['mid', 'Moderate'], ['high', 'Wide (over 4%)']],
      (s, v) => { const a = indOf(s).atr; if (!isNum(a) || !isNum(s.price) || !s.price) return false; const x = (a / s.price) * 100; return v === 'low' ? x < 2.5 : v === 'high' ? x > 4 : x >= 2.5 && x <= 4; }],
    ['pattern', 'Pattern on the latest candles', [['bullish', 'Any bullish pattern'], ['bearish', 'Any bearish pattern']].concat(PATTERN_NAMES.map((n) => [n, n])),
      (s, v) => (s.patterns || []).some((p) => (v === 'bullish' || v === 'bearish' ? p.bias === v : p.name === v))],
  ];
  const activeTech = () => TECH_FILTERS.filter(([key]) => S.filters.tech && S.filters.tech[key]);
  const hasTech = (s) => (s.slim ? !!s.techLoaded : !!s.indicators);
  const techPass = (s) => activeTech().every(([key, , , test]) => test(s, S.filters.tech[key]));

  const searchTokens = () => {
    const tokens = normText(S.q).split(' ').filter(Boolean);
    return tokens.length > 1 ? tokens.filter((w) => w !== 'and') : tokens;          // "m&m" and "m and m" are the same; "and" alone says nothing
  };
  // Everything except the list and the sector: market, reading, search and technical filters. The chip counts use the same test as the table,
  // so a count is always the number of stocks you would see if you picked that chip.
  function passesOthers(s, tokens, fuzzy, skipSignal, skipTech) {
    const f = S.filters;
    if (f.market !== 'ALL' && s.market !== f.market) return false;
    const reading = readingSide(s, f.horizon);
    if (skipSignal) { /* counted separately */ }
    else if (f.signal === 'BUY' && reading !== 'buy') return false;
    else if (f.signal === 'HOLD' && reading !== 'hold') return false;
    else if (f.signal === 'SELL' && reading !== 'sell') return false;
    if (f.news && f.news !== 'ALL') {
      const n = s.news_intel;
      if (!n) return false;
      if (f.news === 'CONFIRMS' ? n.validation !== 'confirms' : f.news === 'CONFLICTS' ? n.validation !== 'conflicts' : n.label !== f.news) return false;
    }
    if (tokens.length && !matchesQuery(s, tokens, fuzzy)) return false;
    return skipTech || techPass(s);
  }

  function visibleStocks(skipSignal, skipTech) {
    const f = S.filters;
    const tokens = searchTokens();
    const query = normText(S.q);
    const pass = (fuzzy) => S.data.stocks.concat(S.others).filter((s) => inList(s, f.list) && inSector(s, f.sector) && passesOthers(s, tokens, fuzzy, skipSignal, skipTech));
    let rows = pass(false);
    S.fuzzy = false;
    if (tokens.length && !rows.length) { rows = pass(true); S.fuzzy = rows.length > 0; }
    const asc = currentDir() === 'asc';
    const byMatch = tokens.length && f.sort === 'score' && !skipSignal;       // while searching with the default order, the best matches come first
    const present = (v) => isNum(v) || (typeof v === 'string' && v !== '');
    rows.sort((a, b) => {
      if (byMatch) { const d = matchRank(a, query) - matchRank(b, query); if (d) return d; }
      const av = sortValue(a), bv = sortValue(b);
      if (!present(av) && !present(bv)) return 0;
      if (!present(av)) return 1;                       // rows without a value always go last
      if (!present(bv)) return -1;
      const order = typeof av === 'string' || typeof bv === 'string' ? String(av).localeCompare(String(bv)) : av - bv;
      return asc ? order : -order;
    });
    return rows;
  }

  /* Text cells are guarded so a spreadsheet never runs one as a formula. Numbers pass through untouched. */
  function csvCell(value) {
    if (value === null || value === undefined) return '';
    if (typeof value === 'number') return Number.isFinite(value) ? String(value) : '';
    let text = String(value);
    if (/^[=+\-@\t\r]/.test(text)) text = "'" + text;
    return /[",\n\r]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
  }

  async function exportCsv() {
    if (S.catalog === 'ready' && S.extra !== 'ready') { toast('Preparing the export…'); await loadExtra(); }       // the other stocks' ratios are in the second file
    const rows = visibleStocks();
    const head = ['Symbol', 'Name', 'Market', 'Sector', 'Series', 'Currency', 'Price', 'Day change %', 'Weeks-view reading', 'Weeks-view indicator alignment', 'Months-view reading',
      'Months-view indicator alignment', 'Pressure', 'Dividend yield', 'P/E', 'EPS', 'EV/EBITDA', 'EBITDA', 'ROE', 'Debt/Equity', 'RSI', 'Yearly volatility', 'Analysed', 'Last price date'];
    const lines = [head.map(csvCell).join(',')];
    for (const s of rows) {
      const fund = s.fundamentals || {};
      lines.push([s.symbol, s.name, s.market, s.sector, s.series || '', s.currency, s.price, s.change_pct, s.short.label ? labelText(s.short.label) : '', s.short.score,
        s.long.label ? labelText(s.long.label) : '', s.long.score, s.pressure ? s.pressure.label : '', s.dividend_yield, fund.pe, fund.eps, fund.ev_ebitda, fund.ebitda, fund.roe,
        fund.debt_to_equity, (s.indicators || {}).rsi, (s.risk || {}).annual_vol, s.slim && !s.analysed ? 'no' : 'yes', s.as_of].map(csvCell).join(','));
    }
    const url = URL.createObjectURL(new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' }));
    const link = h('a', { href: url, download: `stock-signals-${todayIso()}.csv` });
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast(`Exported ${rows.length} stock${rows.length === 1 ? '' : 's'}`);
  }

  function listChips(fuzzy) {
    const f = S.filters;
    const tokens = searchTokens();
    const pool = S.data.stocks.concat(S.others).filter((s) => passesOthers(s, tokens, fuzzy));
    const inSectorPool = pool.filter((s) => inSector(s, f.sector));      // list counts follow the chosen sector
    const inListPool = pool.filter((s) => inList(s, f.list));            // sector counts follow the chosen list
    const names = new Set();
    for (const s of pool) for (const name of s.lists) names.add(name);
    const countList = (key) => inSectorPool.filter((s) => inList(s, key)).length;
    const chips = [['ALL', 'All', countList('ALL')], ['WATCH', 'My watchlist', countList('WATCH')]];
    for (const name of Object.keys(S.lists)) chips.push(['C:' + name, name, countList('C:' + name)]);
    for (const name of FIXED_LISTS) if (names.has(name)) chips.push([name, name, countList(name)]);
    const sectors = [...names].filter((n) => !FIXED_LISTS.includes(n) && n !== 'Other').sort();
    const sectorChips = [['ALL', 'All sectors', inListPool.length], ...sectors.map((name) => [name, name, inListPool.filter((s) => inSector(s, name)).length])];
    const make = (field) => ([key, label, count]) => h('button', {
      type: 'button', class: 'chip' + (f[field] === key ? ' on' : ''), 'aria-pressed': f[field] === key ? 'true' : 'false',
      onclick: () => { f[field] = key; saveFilters(); updateSignals(); },
    }, `${label} (${count})`);
    const buttons = chips.map(make('list'));
    buttons.push(h('button', { type: 'button', class: 'chip', onclick: () => {
      const name = (prompt('Name for the new list (for example "Retirement")') || '').trim().slice(0, 30);
      if (!name) return;
      if (S.lists[name]) { toast('A list with that name already exists'); return; }
      S.lists[name] = []; store.set('lists', S.lists); f.list = 'C:' + name; saveFilters(); updateSignals();
      toast('List created. Open a stock to add it to this list.');
    } }, '+ New list'));
    return { lists: buttons, sectors: sectors.length ? sectorChips.map(make('sector')) : [] };
  }

  const VIEWS = [['overview', 'Overview'], ['valuation', 'Valuation'], ['dividend', 'Dividends'], ['technical', 'Technical'], ['risk', 'Risk']];
  const DASH = '–';

  const pressureText = (s) => (s.pressure ? s.pressure.label.replace(' pressure', '') : DASH);
  const pressureClass = (s) => (s.pressure && s.pressure.label.startsWith('Buying') ? 'pos' : s.pressure && s.pressure.label.startsWith('Selling') ? 'neg' : '');
  const dividendCell = (s) => (isNum(s.dividend_yield) && s.dividend_yield > 0
    ? [percent(s.dividend_yield, 2), s.slim && s.dividend_basis === 'indicated' ? h('span', { class: 'muted small', title: 'Yahoo\'s indicated annual dividend divided by the price. This stock is not analysed yet, so the yield is not worked out from its payments.' }, ' *') : null, s.dividend ? h('span', { class: 'muted small', title: `${s.dividend.frequency} dividend${s.dividend.overdue ? ', payment overdue' : ''}` }, ` ${FREQ_CODE[s.dividend.frequency] || ''}${s.dividend.overdue ? '!' : ''}`) : null]
    : DASH);
  const newsCell = (s) => {
    const n = s.news_intel;
    const fresh = s.news && s.news.fresh && s.news.fresh.length ? h('span', { class: 'tag', title: 'A headline about this company from the last few hours' }, 'New') : null;
    if (!n || !n.interpretation || n.interpretation === 'Neutral' && n.impact < 20) return fresh;
    return h('span', null, h('span', { class: `tag ${INTERPRETATION_CLASS[n.interpretation] || ''}`, title: `News ${n.interpretation.toLowerCase()}: sentiment ${signedInt(n.sentiment)}, impact ${n.impact}. ${(VALIDATION_TEXT[n.validation] || [])[1] || ''}` }, n.interpretation), n.validation === 'conflicts' ? h('span', { class: 'lag', title: 'The news conflicts with the reading' }, ' ≠') : null, fresh ? ' ' : null, fresh);
  };

  /* Extra columns for each table view, after the fixed Stock, Price, Day and Signal columns. */
  function extraColumns(view) {
    const fund = (s) => s.fundamentals || {};
    const ind = (s) => s.indicators || {};
    const risk = (s) => s.risk || {};
    const sets = {
      overview: [
        { label: 'Pressure', render: pressureText, cls: pressureClass },
        { label: 'Dividend', num: true, render: dividendCell },
        { label: 'News tone', render: newsCell, hideMd: true },
      ],
      valuation: [
        { label: 'Mkt cap', num: true, render: (s) => big(fund(s).market_cap, s.currency) },
        { label: 'P/E', num: true, render: (s) => number(fund(s).pe, 1) },
        { label: 'Forward P/E', num: true, render: (s) => number(fund(s).forward_pe, 1), hideMd: true },
        { label: 'P/B', num: true, render: (s) => number(fund(s).pb, 1) },
        { label: 'EV/EBITDA', num: true, render: (s) => number(fund(s).ev_ebitda, 1) },
        { label: 'P/S', num: true, render: (s) => number(fund(s).price_to_sales, 1), hideMd: true },
        { label: 'EPS', num: true, render: (s) => number(fund(s).eps, 2), hideMd: true },
        { label: 'EBITDA', num: true, render: (s) => big(fund(s).ebitda, s.currency), hideMd: true },
        { label: 'Op. margin', num: true, render: (s) => percent(fund(s).operating_margin, 0), hideMd: true },
        { label: 'ROE', num: true, render: (s) => percent(fund(s).roe, 0) },
        { label: 'Revenue growth', num: true, render: (s) => percent(fund(s).revenue_growth, 0), hideMd: true },
        { label: 'Debt/Equity', num: true, render: (s) => number(fund(s).debt_to_equity) },
        { label: 'Free cash flow', num: true, render: (s) => big(fund(s).free_cash_flow, s.currency), hideMd: true },
        { label: 'Current ratio', num: true, render: (s) => number(fund(s).current_ratio, 2), hideMd: true },
      ],
      dividend: [
        { label: 'Yield (12m)', num: true, render: (s) => (s.dividend_yield > 0 ? percent(s.dividend_yield, 2) : DASH) },
        { label: 'Recurring yield', num: true, render: (s) => (s.dividend && isNum(s.dividend.forward_yield) ? percent(s.dividend.forward_yield, 2) : DASH) },
        { label: 'Pays', render: (s) => (s.dividend ? s.dividend.frequency + (s.dividend.overdue ? ' (overdue)' : '') : DASH) },
        { label: 'Last payment', render: (s) => (s.dividend ? `${money(s.dividend.last_amount, s.currency)} on ${s.dividend.last_date}` : DASH), hideMd: true },
        { label: 'Change', num: true, render: (s) => (s.dividend && isNum(s.dividend.growth) ? signed(s.dividend.growth * 100, 1) : DASH) },
        { label: 'Payout', num: true, render: (s) => percent(fund(s).payout_ratio, 0) },
      ],
      technical: [
        { label: 'RSI', num: true, render: (s) => number(ind(s).rsi, 0) },
        { label: 'vs 200-day', num: true, render: (s) => (isNum(ind(s).sma200) ? signed((s.price / ind(s).sma200 - 1) * 100, 1) : DASH) },
        { label: '6-month', num: true, render: (s) => (isNum(ind(s).momentum126) ? signed(ind(s).momentum126 * 100, 1) : DASH) },
        { label: '52-week range', num: true, render: (s) => (isNum(ind(s).hi252) && ind(s).hi252 > ind(s).lo252 ? percent((s.price - ind(s).lo252) / (ind(s).hi252 - ind(s).lo252), 0) : DASH) },
        { label: 'Pressure', render: pressureText, cls: pressureClass },
        { label: 'Pattern', render: (s) => ((s.patterns || [])[0] ? s.patterns[0].name : DASH), hideMd: true },
      ],
      risk: [
        { label: 'Volatility', num: true, render: (s) => percent(risk(s).annual_vol, 0) },
        { label: '1-day VaR', num: true, render: (s) => percent(risk(s).var95, 1) },
        { label: 'Worst fall', num: true, render: (s) => percent(risk(s).max_drawdown, 0) },
        { label: 'Beta', num: true, render: (s) => number(risk(s).beta) },
        { label: 'Volatility risk level', num: true, render: (s) => (s.stop ? signed(s.stop.pct, 1) : DASH) },
        { label: 'Rule vs hold', render: (s) => { const b = (s.backtest || {}).short; return b ? (b.beats_buy_hold_oos ? 'Beat' : 'Lagged') : DASH; }, hideMd: true },
      ],
    };
    const values = {
      Pressure: (s) => (s.pressure ? (s.pressure.label.startsWith('Buying') ? 1 : s.pressure.label.startsWith('Selling') ? -1 : 0) : null),
      Dividend: (s) => s.dividend_yield, News: (s) => s.news.fresh.length,
      'Mkt cap': (s) => fund(s).market_cap, 'P/E': (s) => fund(s).pe, 'P/B': (s) => fund(s).pb, ROE: (s) => fund(s).roe,
      'Revenue growth': (s) => fund(s).revenue_growth, 'Debt/Equity': (s) => fund(s).debt_to_equity,
      'Forward P/E': (s) => fund(s).forward_pe, 'EV/EBITDA': (s) => fund(s).ev_ebitda, 'P/S': (s) => fund(s).price_to_sales, EPS: (s) => fund(s).eps,
      EBITDA: (s) => fund(s).ebitda, 'Op. margin': (s) => fund(s).operating_margin, 'Free cash flow': (s) => fund(s).free_cash_flow, 'Current ratio': (s) => fund(s).current_ratio,
      'Yield (12m)': (s) => s.dividend_yield, 'Recurring yield': (s) => (s.dividend ? s.dividend.forward_yield : null),
      Pays: (s) => (s.dividend ? s.dividend.frequency : null), 'Last payment': (s) => (s.dividend ? s.dividend.last_date : null),
      Change: (s) => (s.dividend ? s.dividend.growth : null), Payout: (s) => fund(s).payout_ratio,
      RSI: (s) => ind(s).rsi, 'vs 200-day': (s) => (isNum(ind(s).sma200) ? s.price / ind(s).sma200 - 1 : null), '6-month': (s) => ind(s).momentum126,
      '52-week range': (s) => (isNum(ind(s).hi252) && ind(s).hi252 > ind(s).lo252 ? (s.price - ind(s).lo252) / (ind(s).hi252 - ind(s).lo252) : null),
      Pattern: (s) => ((s.patterns || [])[0] ? s.patterns[0].name : null),
      Volatility: (s) => risk(s).annual_vol, '1-day VaR': (s) => risk(s).var95, 'Worst fall': (s) => risk(s).max_drawdown, Beta: (s) => risk(s).beta,
      'Volatility risk level': (s) => (s.stop ? s.stop.pct : null), 'Rule vs hold': (s) => { const b = (s.backtest || {}).short; return b ? (b.beats_buy_hold_oos ? 1 : 0) : null; },
    };
    return (sets[view] || sets.overview).map((c) => ({ ...c, val: values[c.label] }));
  }
  const columnClass = (column) => `${column.num ? 'num ' : ''}hide-sm${column.hideMd ? ' hide-md' : ''}`;

  function stockRow(s) {
    const f = S.filters;
    const star = h('button', {
      type: 'button', class: 'star' + (S.watch.has(s.symbol) ? ' on' : ''), 'aria-label': `${S.watch.has(s.symbol) ? 'Remove' : 'Add'} ${s.name} ${S.watch.has(s.symbol) ? 'from' : 'to'} watchlist`,
      'aria-pressed': S.watch.has(s.symbol) ? 'true' : 'false',
      onclick: (e) => { e.stopPropagation(); S.watch.has(s.symbol) ? S.watch.delete(s.symbol) : S.watch.add(s.symbol); saveWatch(); updateSignals(); },
    }, S.watch.has(s.symbol) ? '★' : '☆');
    const row = h('tr', { class: 'stock', tabindex: '0', 'aria-label': `${s.name} details` },
      h('td', null, star),
      h('td', { class: 'name' }, h('b', null, s.name), h('span', null, s.symbol, s.new ? ' · new listing' : '', s.stale ? ' · stale price' : '', s.provenance_ok === false ? ' · data not current' : '', s.slim && !s.analysed ? ' · quote only' : '', s.series ? ` · ${s.series} series` : '', (s.flags || []).includes('thin') ? ' · thinly traded' : '')),
      h('td', { class: 'num' }, money(s.price, s.currency)),
      h('td', { class: `num ${isNum(s.change_pct) ? (s.change_pct >= 0 ? 'up' : 'down') : ''}` }, signed(s.change_pct)),
      h('td', null, badges(s, f.horizon), lagMark(s)),
      extraColumns(f.view).map((column) => h('td', { class: `${columnClass(column)}${column.cls ? ' ' + column.cls(s) : ''}` }, column.render(s))));
    row.addEventListener('click', () => openDetail(s.symbol, row));
    row.addEventListener('keydown', (e) => { if (e.key === 'Enter') openDetail(s.symbol, row); });
    return row;
  }

  const PAGE = 150;                       // rows drawn at a time; the sort and filters always cover every stock
  const MARKET_NAMES = { IN: 'India (NSE)' };
  const MARKET_INDEX = { IN: '^NSEI' };

  /* One panel per market: a header with buy/hold/sell counts and the index trend, then its table. */
  function marketPanel(code, rows) {
    const horizon = S.filters.horizon;
    const count = { buy: 0, hold: 0, sell: 0 };
    for (const s of rows) { const reading = readingSide(s, horizon); if (reading) count[reading] += 1; }
    const index = ((S.data.market || {}).watch || []).find((w) => w.symbol === MARKET_INDEX[code]);
    const head = h('div', { class: 'panelhead' },
      h('h2', null, MARKET_NAMES[code]),
      h('span', { class: 'muted small' }, `${rows.length} stock${rows.length === 1 ? '' : 's'}`),
      index && index.regime ? h('span', { class: `tag ${index.regime === 'Downtrend' ? 'warn' : ''}`, title: `${index.name} ${signed(index.change_pct)} today` }, `${index.name}: ${index.regime}`, isNum(index.change_pct) ? ` ${signed(index.change_pct)}` : '') : null);
    const bar = rows.length ? h('div', null,
      h('div', { class: 'leanbar', role: 'img', 'aria-label': `${count.buy} aligned bullish, ${count.hold} mixed, ${count.sell} aligned bearish` },
        [['u', count.buy], ['n', count.hold], ['d', count.sell]].map(([k, n]) => (n ? h('i', { class: k, style: `flex:${n}` }) : null))),
      h('div', { class: 'leanlegend' }, h('span', { class: 'up' }, `${count.buy} bullish`), h('span', { class: 'muted' }, `${count.hold} mixed`), h('span', { class: 'down' }, `${count.sell} bearish`))) : null;
    const body = rows.length
      ? h('div', { class: 'tablewrap' }, h('table', null,
        h('thead', null, h('tr', null, h('th', null, ''), sortHead('name', 'Stock'), sortHead('price', 'Price', 'num'), sortHead('change', 'Day', 'num'),
          sortHead('score', 'Signal'), extraColumns(S.filters.view).map((column) => (column.val ? sortHead('col:' + column.label, column.label, columnClass(column)) : h('th', { class: columnClass(column) }, column.label))))),
        h('tbody', null, rows.slice(0, S.shown[code] || PAGE).map(stockRow))),
        rows.length > (S.shown[code] || PAGE) ? h('button', { type: 'button', class: 'btn ghost more', onclick: () => { S.shown[code] = (S.shown[code] || PAGE) + PAGE; updateSignals(); } },
          `Show ${Math.min(PAGE, rows.length - (S.shown[code] || PAGE))} more (${rows.length - (S.shown[code] || PAGE)} not shown)`) : null)
      : h('div', { class: 'empty' }, 'No stocks match these filters.');
    return h('section', { class: 'card panel', 'aria-label': MARKET_NAMES[code] }, head, bar, body);
  }

  function updateSignals() {
    const cats = $('#cats'), sectorRail = $('#sectorrail'), results = $('#results');
    if (!cats || !sectorRail || !results) return;
    if (needsExtra() && S.catalog === 'ready' && !S.extra) loadExtra();
    const rows = visibleStocks();
    const fuzzy = S.fuzzy;                 // a later call below recomputes S.fuzzy
    const strips = listChips(fuzzy);
    cats.replaceChildren(h('div', { class: 'railtitle' }, 'Categories'), h('div', { class: 'chips', role: 'group', 'aria-label': 'Lists and technical screens' }, strips.lists));
    sectorRail.replaceChildren(...[strips.sectors.length ? h('div', { class: 'railtitle' }, 'Sectors') : null,
      strips.sectors.length ? h('div', { class: 'chips', role: 'group', 'aria-label': 'Sectors' }, strips.sectors) : null].filter(Boolean));
    const f = S.filters;
    const signature = [f.market, f.list, f.sector, f.signal, f.news, S.q, JSON.stringify(f.tech || {})].join('|');
    if (signature !== S.sig) { S.sig = signature; S.shown = {}; }        // a new search or filter starts again at the first page
    const hidden = f.signal === 'ALL' ? 0 : visibleStocks(true).filter((s) => readingSide(s, f.horizon) === null).length;
    const hiddenTech = activeTech().length ? visibleStocks(false, true).filter((s) => !hasTech(s)).length : 0;
    const extraNote = needsExtra() && S.catalog === 'ready' ? (S.extra === 'failed' ? h('p', { class: 'small notice warnline' }, 'The indicator values of the other stocks could not be loaded, so technical filters and the extra columns only cover the main list. ', h('button', { type: 'button', class: 'chip', onclick: () => { S.extra = null; updateSignals(); } }, 'Try again'))
      : S.extra !== 'ready' ? h('p', { class: 'muted small notice' }, 'Loading indicator values for the other stocks…') : null) : null;
    const info = S.catalogInfo;
    const status = S.catalog === 'loading' ? h('p', { class: 'muted small notice' }, 'Loading every other listed stock… the table shows the main list for now.')
      : S.catalog === 'failed' ? h('p', { class: 'small notice warnline' }, 'The full list of listed stocks could not be loaded, so only the main list is shown. ',
        h('button', { type: 'button', class: 'chip', onclick: () => loadCatalog() }, 'Try again'))
        : info && info.analysed < info.count * 0.98 ? h('p', { class: 'muted small notice' }, `${info.analysed.toLocaleString()} of ${info.count.toLocaleString()} other listed stocks are analysed so far. The rest show their quote only and fill in over the next few hours.`) : null;
    const READING = { BUY: 'Aligned bullish', HOLD: 'Mixed', SELL: 'Aligned bearish' };
    const on = [];
    if (f.market !== 'ALL') on.push(['India only', () => { f.market = 'ALL'; f.list = 'ALL'; f.sector = 'ALL'; }]);
    if (f.signal !== 'ALL') on.push([`Reading: ${READING[f.signal]}`, () => { f.signal = 'ALL'; }]);
    if (f.news && f.news !== 'ALL') on.push([`News: ${({ Positive: 'positive', Negative: 'negative', Mixed: 'mixed', CONFIRMS: 'confirms the reading', CONFLICTS: 'conflicts with the reading' })[f.news] || f.news}`, () => { f.news = 'ALL'; }]);
    if (S.q.trim()) on.push([`Search: "${S.q.trim()}"`, () => { S.q = ''; const box = document.querySelector('input[type=search]'); if (box) box.value = ''; }]);
    for (const [key, label, options] of activeTech()) on.push([`${label}: ${(options.find(([v]) => v === f.tech[key]) || [])[1] || f.tech[key]}`, () => { delete f.tech[key]; renderTech(); }]);
    const activeBar = on.length ? h('div', { class: 'chips', role: 'group', 'aria-label': 'Filters that are on' },
      h('span', { class: 'muted small', style: 'align-self:center' }, 'Filters on:'),
      on.map(([text, undo]) => h('button', { type: 'button', class: 'chip on', title: 'Remove this filter', onclick: () => { undo(); saveFilters(); updateSignals(); } }, `${text} ✕`))) : null;
    const head = h('div', { class: 'row small muted', style: 'justify-content:space-between;margin-bottom:6px' },
      h('span', null, `${rows.length} stock${rows.length === 1 ? '' : 's'} · ${horizonName(f.horizon)} reading`,
        hidden ? ` · ${hidden.toLocaleString()} without a reading yet hidden by the Reading filter` : '',
        hiddenTech ? ` · ${hiddenTech.toLocaleString()} without technical data hidden by the technical filters` : '', fuzzy ? ` · no exact match for "${S.q.trim()}", showing close matches` : ''),
      f.list.startsWith('C:') ? h('button', { type: 'button', class: 'chip', onclick: () => {
        if (!confirm(`Delete the list "${f.list.slice(2)}"? The stocks are not deleted.`)) return;
        delete S.lists[f.list.slice(2)]; store.set('lists', S.lists); f.list = 'ALL'; saveFilters(); updateSignals();
      } }, 'Delete this list') : null);
    if (!rows.length) {
      const clear = () => { f.market = 'ALL'; f.list = 'ALL'; f.sector = 'ALL'; f.signal = 'ALL'; f.tech = {}; S.q = ''; saveFilters(); render(); };
      results.replaceChildren(...[status, extraNote, activeBar, head, h('div', { class: 'empty' },
        f.list === 'WATCH' && !S.q ? 'Your watchlist is empty. Tap the star next to a stock to add it.'
          : S.catalog === 'loading' && S.q ? 'Nothing found in the main list yet. Every other listed stock is still loading.'
          : S.q ? `No stock matches "${S.q.trim()}". This app covers stocks listed on the NSE (main board and SME) ; a company listed only on the BSE is not included. ` : 'No stocks match these filters. ',
        f.list === 'WATCH' && !S.q ? null : h('button', { type: 'button', class: 'chip', onclick: clear }, 'Clear filters'))].filter(Boolean));
      return;
    }
    const codes = ['IN'];
    results.replaceChildren(...[status, extraNote, activeBar, head, h('div', { class: 'cols' + (codes.length > 1 ? ' two' : '') + (f.view !== 'overview' ? ' wide-view' : '') }, codes.map((code) => marketPanel(code, rows.filter((s) => s.market === code))))].filter(Boolean));
    decorateHelp(results);
  }

  function select(label, value, options, onChange) {
    const el = h('select', { onchange: (e) => onChange(e.target.value) }, options.map(([v, text]) => h('option', { value: v, selected: v === value }, text)));
    return h('label', { class: 'field' }, label, el);
  }

  function techPanel(open) {
    const f = S.filters;
    f.tech = f.tech || {};
    const n = activeTech().length;
    const choose = (key, label, options) => h('label', { class: 'field' }, label,
      h('select', { onchange: (e) => { if (e.target.value) f.tech[key] = e.target.value; else delete f.tech[key]; saveFilters(); renderTech(); updateSignals(); } },
        [['', 'Any']].concat(options).map(([v, text]) => h('option', { value: v, selected: v === (f.tech[key] || '') }, text))));
    const panel = h('details', { class: 'card techfilters', open: open ? 'open' : null },
      h('summary', null, 'Technical filters', n ? h('span', { class: 'tag', style: 'margin-left:8px' }, `${n} on`) : null),
      h('div', { class: 'row', style: 'margin-top:8px' }, TECH_FILTERS.map(([key, label, options]) => choose(key, label, options))),
      h('p', { class: 'muted small', style: 'margin:6px 0 0' }, 'Every filter you set must be true for a stock to show. Each one reads the stock\'s indicator values; a stock that is not analysed yet has none, so it is hidden while a technical filter is on. ',
        n ? h('button', { type: 'button', class: 'chip', onclick: () => { f.tech = {}; saveFilters(); renderTech(); updateSignals(); } }, 'Clear technical filters') : null));
    panel.addEventListener('toggle', () => { S.techOpen = panel.open; if (panel.open) updateSignals(); });
    return panel;
  }
  function renderTech() {
    const box = $('#techbox');
    if (!box) return;
    const open = !!(box.firstChild && box.firstChild.open);
    box.replaceChildren(techPanel(open));
  }

  function viewSignals() {
    const f = S.filters;
    const search = h('input', { type: 'search', placeholder: 'Name or symbol', value: S.q, 'aria-label': 'Search stocks', oninput: (e) => { S.q = e.target.value; updateSignals(); } });
    const bar = h('div', { class: 'card filterbar' }, h('div', { class: 'row' },
      h('label', { class: 'field' }, 'Search', search),
      select('Reading', f.signal, [['ALL', 'Any'], ['BUY', 'Aligned bullish'], ['HOLD', 'Mixed'], ['SELL', 'Aligned bearish']], (v) => { f.signal = v; saveFilters(); updateSignals(); }),
      select('News tone (experimental)', f.news || 'ALL', [['ALL', 'Any'], ['Positive', 'Positive'], ['Negative', 'Negative'], ['Mixed', 'Mixed'], ['CONFIRMS', 'Agrees with the reading'], ['CONFLICTS', 'Conflicts with the reading']], (v) => { f.news = v; saveFilters(); updateSignals(); }),
      select('Sort by', f.sort, [['score', 'Indicator alignment'], ['change', 'Day change'], ['dividend', 'Dividend yield'], ['name', 'Name']].concat(['score', 'change', 'dividend', 'name'].includes(f.sort) ? [] : [[f.sort, 'Table column']]), (v) => { f.sort = v; f.dir = defaultDir(v); saveFilters(); updateSignals(); }),
      h('div', { class: 'field' }, 'Horizon', h('div', { class: 'row', style: 'gap:6px' },
        ['short', 'long', 'both'].map((hz) => h('button', { type: 'button', class: 'chip' + (f.horizon === hz ? ' on' : ''), 'aria-pressed': f.horizon === hz ? 'true' : 'false',
          onclick: () => { f.horizon = hz; saveFilters(); render(); } }, hz === 'short' ? 'Short-term' : hz === 'long' ? 'Long-term' : 'Both')))),
      select('Columns', f.view, VIEWS, (v) => { f.view = v; saveFilters(); updateSignals(); }),
      h('button', { type: 'button', class: 'chip', title: 'Download the stocks shown as a spreadsheet file', onclick: exportCsv }, 'Export CSV')));
    const root = h('div', null, evidenceStrip(), bar, h('div', { class: 'signals-layout' },
      h('aside', { id: 'cats', class: 'rail', 'aria-label': 'Categories' }),
      h('div', { class: 'signals-main' }, h('div', { id: 'techbox' }), h('div', { id: 'results' })),
      h('aside', { id: 'sectorrail', class: 'rail', 'aria-label': 'Sectors' })));
    queueMicrotask(() => { renderTech(); updateSignals(); });
    return root;
  }

  /* ---------- detail dialog ---------- */
  let lastFocus = null;
  function quoteView(row, note) {
    const range = isNum(row.high52) && isNum(row.low52) && row.high52 > row.low52 ? percent((row.price - row.low52) / (row.high52 - row.low52), 0) : DASH;
    return h('div', { class: 'detailview' },
      h('div', { class: 'row', style: 'justify-content:space-between;gap:8px;padding:12px' },
        h('div', null, h('h2', { style: 'margin:0' }, row.name), h('span', { class: 'muted small' }, row.symbol)),
        h('div', { class: 'row', style: 'gap:6px' },
          h('button', { type: 'button', class: 'chip' + (S.watch.has(row.symbol) ? ' on' : ''), 'aria-pressed': S.watch.has(row.symbol) ? 'true' : 'false',
            onclick: (e) => { S.watch.has(row.symbol) ? S.watch.delete(row.symbol) : S.watch.add(row.symbol); saveWatch(); e.currentTarget.classList.toggle('on', S.watch.has(row.symbol));
              e.currentTarget.textContent = S.watch.has(row.symbol) ? '★ In watchlist' : '☆ Add to watchlist'; e.currentTarget.setAttribute('aria-pressed', String(S.watch.has(row.symbol))); updateSignals(); } },
          S.watch.has(row.symbol) ? '★ In watchlist' : '☆ Add to watchlist'),
          h('button', { type: 'button', class: 'dclose', 'aria-label': 'Close', onclick: closeDetail }, '✕'))),
      h('div', { class: 'kv', style: 'padding:0 12px' }, [['Price', money(row.price, row.currency)], ['Day', signed(row.change_pct)], ['Market cap', big(row.cap, row.currency)],
        ['P/E', number(row.pe, 1)], ['P/B', number(row.pb, 1)], ['EPS', number(row.eps, 2)], ['Book value per share', number(row.book_value, 2)],
        ['Dividend (Yahoo indicated)', isNum(row.dividend_rate) && row.dividend_rate > 0 ? `${money(row.dividend_rate, row.currency)} a year (${percent(row.dividend_yield, 2)} of the price)` : DASH],
        ['Position in 52-week range', range], ['Volume vs average', isNum(row.volume) && row.avg_volume ? `${(row.volume / row.avg_volume).toFixed(1)}x` : DASH]]
        .map(([k, v]) => h('div', null, h('span', null, k), h('b', null, naOr(v))))),
      h('p', { class: 'muted small', style: 'padding:8px 12px' }, note),
      h('p', { class: 'small', style: 'padding:0 12px 12px' }, 'Official pages: ',
        row.symbol.endsWith('.NS') ? [h('a', { href: `https://www.nseindia.com/get-quotes/equity?symbol=${encodeURIComponent(row.symbol.slice(0, -3))}`, target: '_blank', rel: 'noopener' }, 'NSE quote'), ' · '] : null,
        h('a', { href: `https://finance.yahoo.com/quote/${encodeURIComponent(row.symbol)}`, target: '_blank', rel: 'noopener' }, 'Yahoo Finance')));
  }

  async function openDetail(symbol, opener, tab) {
    const s = S.data.stocks.find((x) => x.symbol === symbol);
    if (!s) {
      const row = S.others.find((x) => x.symbol === symbol);
      if (!row) return;
      lastFocus = opener || document.activeElement;
      const dlg = $('#detail');
      dlg.replaceChildren(quoteView(row, 'Loading the analysis…'));
      if (!dlg.open) dlg.showModal();
      const record = row.analysed ? await loadRecord(row) : null;
      if (!dlg.open) return;
      if (record) showDetail(record, tab);
      else dlg.replaceChildren(quoteView(row, row.analysed ? 'The analysis could not be loaded. Try again in a moment.' : 'This stock has not been analysed yet. Every listed stock is analysed in turn and refreshed about once a day. Until then only its quote is shown.'));
      return;
    }
    lastFocus = opener || document.activeElement;
    if (s.lite) {
      const dlg = $('#detail');
      dlg.replaceChildren(h('div', { class: 'detailview' }, h('div', { class: 'row', style: 'justify-content:space-between;gap:8px;padding:12px' },
        h('div', null, h('h2', { style: 'margin:0' }, s.name), h('span', { class: 'muted small' }, s.symbol)),
        h('button', { type: 'button', class: 'dclose', 'aria-label': 'Close', onclick: closeDetail }, '✕')), h('p', { class: 'muted small', style: 'padding:0 12px 16px' }, 'Loading the analysis…')));
      if (!dlg.open) dlg.showModal();
      const full = await loadRecord(s);
      if (!dlg.open) return;
      if (!full) {                      // the summary record cannot draw the whole page, so show the quote and say so
        const f = s.fundamentals || {}, i = s.indicators || {};
        dlg.replaceChildren(quoteView({ ...s, cap: f.market_cap, high52: i.hi252, low52: i.lo252 }, 'The full analysis could not be loaded. Close this and try again in a moment.'));
        return;
      }
      showDetail(full, tab);
      return;
    }
    showDetail(s, tab);
  }
  function showDetail(s, tab) {
    const dlg = $('#detail');
    dlg.replaceChildren(detailView(s));
    decorateHelp(dlg);
    activateDetailTab(tab || 'overview');
    if (!dlg.open) dlg.showModal();
    dlg.scrollTop = 0;
  }
  function closeDetail() { const dlg = $('#detail'); if (dlg.open) dlg.close(); }

  /* Links from alerts look like #stock=AAPL&section=signals and open that stock's analysis. */
  let handledHash = '';
  function clearHash() {
    if (location.hash) history.replaceState(null, '', location.pathname + location.search);
    handledHash = '';
  }
  function openFromHash() {
    const match = /^#stock=([^&]+)(?:&section=([a-z-]+))?$/.exec(location.hash);
    if (!match || !S.data || handledHash === location.hash) return;
    handledHash = location.hash;
    let symbol;
    try { symbol = decodeURIComponent(match[1]); } catch (e) { clearHash(); return; }
    if (!S.data.stocks.some((s) => s.symbol === symbol) && !S.others.some((s) => s.symbol === symbol)) {
      if (!S.catalogLoaded) { handledHash = ''; return; }
      toast(`${symbol} is not on the list right now.`);
      clearHash();
      return;
    }
    openDetail(symbol, null, SECTION_TAB[match[2]]);
    if (match[2]) {
      setTimeout(() => { const target = document.getElementById('d-' + match[2]); if (target) target.scrollIntoView({ block: 'start' }); }, 150);
    }
  }

  /* The latest alerts for one stock, with their targets and reasons, shown at the top of its page. */
  function alertsForStock(s) {
    const recent = (S.data.alerts || []).filter((a) => a && a.symbol === s.symbol).slice(-3).reverse();
    if (!recent.length) return null;
    return wide(section('Recent alerts for this stock', h('ul', { class: 'clean' }, recent.map((a) => h('li', null,
      h('span', { style: 'white-space:pre-line' }, a.text),
      h('div', { class: 'muted small' }, ago(Math.max(0, Math.round((Date.now() / 1000 - a.ts) / 60)))))))));
  }

  const PART_NAMES = { trend: 'trend', macd: 'MACD momentum', rsi: 'RSI', volume: 'volume spike check', pressure: 'volume pressure',
    trend200: '200-day average', cross: '50/200-day average', momentum: '6-month return', position: '52-week range', volatility: 'volatility' };

  /* Why a reading is what it is: what supports it, what pulls against it, how complete the data was, and what would weaken it. */
  function signalCard(title, sig) {
    const pos = isNum(sig.score) ? clamp((sig.score + 100) / 2, 0, 100) : 50;
    const reasons = sig.reasons || [];
    const up = reasons.filter((r) => r.tone === 'pos').length, down = reasons.filter((r) => r.tone === 'neg').length;
    const missing = (sig.missing || []).map((k) => PART_NAMES[k] || k);
    const sure = sig.confidence && sig.confidence !== 'full'
      ? h('p', { class: 'small warnline' }, `${sig.confidence === 'limited' ? 'Limited' : 'Reduced'} confidence: no data for ${missing.join(' and ')}, so this reading rests on the other parts only.`) : null;
    return h('div', null, h('h3', null, title), badge(sig),
      isNum(sig.score) ? h('div', { class: 'meter', role: 'img', 'aria-label': `Score ${sig.score} on a scale from minus 100 to plus 100` }, h('i', { style: `left:${pos}%` })) : null,
      reasons.length ? h('p', { class: 'small muted', style: 'margin:4px 0' }, `${up} part${up === 1 ? '' : 's'} supporting, ${down} against, ${reasons.length - up - down} neutral.`) : null,
      reasonsList(reasons), sure,
      (sig.invalidation || []).length ? h('div', { class: 'small invalid' }, h('b', null, 'What would weaken this: '), sig.invalidation.join('; '), '.') : null);
  }


  /* ---------- where every figure comes from, when it was read, and whether it is current ---------- */
  const STATE_TAG = { fresh: ['buy', 'Current'], verified: ['buy', 'Verified'], aging: ['', 'Ageing'], unverified: ['', 'Not cross-checked'], unknown: ['', 'Unknown'],
    stale: ['warn', 'Not current'], disputed: ['warn', 'Disputed'] };
  const GROUP_NAMES = { price: 'Price', indicators: 'Indicators and readings', end_of_day: 'Closing price cross-check', live: 'Live price cross-check',
    outlook: 'Outlook from the past', fundamentals: 'Fundamentals (ratios)', statements: 'Quarterly results and statements', dividends: 'Dividends', news: 'Headlines' };
  const readStamp = (iso) => { const d = iso ? new Date(iso) : null; return d && !Number.isNaN(d.getTime()) ? d.toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '–'; };

  function provenanceCard(s) {
    const p = s.provenance;
    if (!p) return null;
    const rows = Object.keys(GROUP_NAMES).filter((k) => p[k]).map((k) => {
      const e = p[k], [cls, text] = STATE_TAG[e.state] || ['', e.state];
      const age = isNum(e.age_days) ? `${e.age_days} day${e.age_days === 1 ? '' : 's'} old` : '';
      return h('tr', null, h('td', null, GROUP_NAMES[k]), h('td', { class: 'small' }, e.source), h('td', { class: 'num' }, e.as_of || '–'),
        h('td', { class: 'num hide-sm' }, readStamp(e.read_at), age ? h('div', { class: 'muted small' }, age) : null),
        h('td', null, h('span', { class: `tag ${cls}` }, text), e.note ? h('div', { class: 'muted small' }, e.note) : null));
    });
    const notCurrent = ['price', 'indicators', 'end_of_day', 'live'].filter((k) => p[k] && ['stale', 'disputed'].includes(p[k].state)).map((k) => GROUP_NAMES[k].toLowerCase());
    return h('details', { class: 'card wide provenance', open: s.provenance_ok === false },
      h('summary', null, h('b', null, 'Data sources and freshness '), s.provenance_ok === false ? h('span', { class: 'tag warn' }, 'Some inputs are not current') : h('span', { class: 'tag buy' }, 'Inputs current')),
      s.quarantine ? h('p', { class: 'small warnline' }, `Paused by the data-health monitor since ${readStamp(s.quarantine.since)}: ${(s.quarantine.reasons || []).join('; ')}. No alerts or tracked readings until the data has been clean for several runs.`) : null,
      s.provenance_ok === false ? h('p', { class: 'small warnline' }, `The ${notCurrent.join(' and ') || 'inputs'} behind this reading ${notCurrent.length > 1 ? 'are' : 'is'} not current or not confirmed, so treat the reading with care. New alerts and tracked readings for this stock are paused until the data catches up.`) : null,
      h('div', { style: 'overflow-x:auto' }, h('table', null, h('thead', null, h('tr', null, h('th', null, 'Figures'), h('th', null, 'Source'), h('th', { class: 'num' }, 'Data as of'), h('th', { class: 'num hide-sm' }, 'Read'), h('th', null, 'Status'))), h('tbody', null, rows))),
      h('p', { class: 'muted small', style: 'margin-bottom:0' }, 'Every group of figures carries its source, the date it describes and the time it was read. No alert is sent and no reading is tracked on a price series that is missing the newest session or that a second source disputes.'));
  }

  const QUARTER_ROWS = [['revenue', 'Revenue'], ['operating_income', 'Operating income'], ['ebitda', 'EBITDA'], ['net_income', 'Net income'], ['eps', 'Diluted EPS']];
  const YEAR_ROWS = QUARTER_ROWS.concat([['equity', "Shareholders' equity"], ['total_debt', 'Total debt'], ['operating_cash_flow', 'Operating cash flow'], ['free_cash_flow', 'Free cash flow']]);

  function statementsBlock(s) {
    const st = s.statements;
    if (!st || !st.quarterly) return h('p', { class: 'muted small' }, st ? 'The statement figures are loaded when this page opens.' : 'No quarterly results or statements have been read for this stock yet. They are read automatically, a few stocks at a time.');
    const money = (key, v) => (!isNum(v) ? '–' : key === 'eps' ? number(v, 2) : big(v, st.currency));
    const table = (period, rowsDef, cols) => {
      const dates = [...new Set(rowsDef.flatMap(([k]) => ((st[period] || {})[k] || []).map((r) => r.date)))].sort().slice(-cols).reverse();
      if (!dates.length) return null;
      return h('div', { style: 'overflow-x:auto' }, h('table', null, h('thead', null, h('tr', null, h('th', null, period === 'quarterly' ? 'Quarter ended' : 'Year ended'), dates.map((d) => h('th', { class: 'num' }, d)))),
        h('tbody', null, rowsDef.filter(([k]) => (st[period] || {})[k]).map(([k, label]) => h('tr', null, h('td', null, label),
          dates.map((d) => { const row = (st[period][k] || []).find((r) => r.date === d); return h('td', { class: 'num' }, money(k, row && row.value)); }))))));
    };
    const sum = st.summary || {}, change = (o, k) => (isNum((o || {})[k]) ? signed(o[k], 1) : 'no comparable quarter');
    return h('div', null,
      sum.latest_quarter ? h('p', { class: 'small' }, h('b', null, `Latest quarter ${sum.latest_quarter}: `), `revenue ${change(sum.qoq, 'revenue')} on the quarter before, net income ${change(sum.qoq, 'net_income')}`,
        isNum((sum.yoy || {}).revenue) ? `; against the same quarter a year before: revenue ${signed(sum.yoy.revenue, 1)}, net income ${change(sum.yoy, 'net_income')}` : '; no figure for the same quarter a year before, so no yearly change is shown',
        isNum(sum.net_margin_pct) ? `. Net margin ${sum.net_margin_pct}%.` : '.') : null,
      st.currency && s.currency && st.currency !== s.currency ? h('p', { class: 'small warnline' }, `These statements are reported in ${st.currency} while the price is in ${s.currency}: do not mix them in ratios.`) : null,
      h('h4', null, 'By quarter'), table('quarterly', QUARTER_ROWS, 8) || h('p', { class: 'muted small' }, 'No quarterly figures.'),
      h('h4', null, 'By financial year'), table('annual', YEAR_ROWS, 6) || h('p', { class: 'muted small' }, 'No yearly figures.'),
      h('p', { class: 'muted small' }, `Source: ${st.source || 'Yahoo Finance'}, read ${readStamp(st.fetched_at)}${st.currency ? `, in ${st.currency}` : ''}. A quarter Yahoo does not list is left blank, never filled in, and no growth rate is worked out across a gap.`));
  }

  /* Fundamental quality and valuation, scored with the same fixed rules as a new listing (profit margin, revenue growth, debt, return on equity, P/E against
     the sector's median P/E). A part without data is left out, never counted as zero. */
  function qualityBlock(s) {
    const f = s.fundamentals || {};
    const peers = S.data.stocks.filter((p) => p.sector === s.sector && p.market === s.market && p.symbol !== s.symbol).map((p) => (p.fundamentals || {}).pe);
    const peerPe = IPO.median(peers);
    const v = IPO.qualityFromFundamentals(f, peerPe);
    if (!isNum(v.score)) return h('p', { class: 'muted small' }, 'Not enough fundamentals to score quality and valuation for this stock.');
    const words = v.score >= 30 ? ['buy', 'Stronger fundamentals'] : v.score <= -20 ? ['warn', 'Weaker fundamentals'] : ['', 'Mixed fundamentals'];
    const names = { profitability: 'profit margin', growth: 'revenue growth', leverage: 'debt', returns: 'return on equity', valuation: 'valuation against sector P/E' };
    return h('div', null, h('p', null, h('span', { class: `tag ${words[0]}` }, words[1]), ` score ${v.score > 0 ? '+' : ''}${v.score} on a scale from -100 to +100. `,
      h('span', { class: 'muted small' }, `Fundamentals as of ${f.most_recent_quarter || 'an unknown date'}, read ${readStamp(((s.provenance || {}).fundamentals || {}).read_at)}.`)),
      reasonsList(v.reasons),
      v.missing.length ? h('p', { class: 'muted small' }, 'Not used (no data): ' + v.missing.map((k) => names[k] || k).join(', ') + '.') : null,
      h('p', { class: 'muted small', style: 'margin-bottom:0' }, "A description of the reported figures against fixed bands, not a forecast or a recommendation. Banks have no debt or EBITDA figure, and the sector P/E is the median of the stocks in this app's list."));
  }


  /* ---------- outlook: what happened after situations like today's ---------- */
  const OUTLOOK_HORIZONS = [['5', '5 trading days'], ['20', '20 trading days (about a month)'], ['60', '60 trading days (about three months)']];
  const pc = (v, d = 0) => (isNum(v) ? `${(v * 100).toFixed(d)}%` : '–');

  function outlookCard(s) {
    const o = s.outlook;
    if (!o || !o.horizons) return null;
    const rows = OUTLOOK_HORIZONS.filter(([k]) => o.horizons[k]).map(([k, label]) => {
      const x = o.horizons[k];
      return h('tr', null, h('td', null, label),
        h('td', { class: 'num' }, h('b', null, pc(x.p_up)), x.ci ? h('div', { class: 'muted small' }, `range ${pc(x.ci[0])} to ${pc(x.ci[1])}`) : null),
        h('td', { class: 'num hide-sm' }, pc(x.base)),
        h('td', { class: 'num hide-sm' }, signed(x.median * 100, 1), h('div', { class: 'muted small' }, `${signed(x.p10 * 100, 0)} to ${signed(x.p90 * 100, 0)}`)),
        h('td', { class: 'num hide-sm' }, x.n.toLocaleString(), h('div', { class: 'muted small' }, `${x.level === 'L3' ? 'exact match' : x.level === 'L0' ? 'all situations' : 'broader match'}`)),
        h('td', null, h('span', { class: `tag ${x.edge ? 'buy' : ''}` }, x.edge ? 'Beat the base rate' : 'No better than base rate')));
    });
    const anyEdge = Object.values(o.horizons).some((x) => x.edge);
    const card = (S.data.learning || {}).scorecard;
    return h('details', { class: 'card wide outlook', open: true },
      h('summary', null, h('b', null, 'Outlook from the past '), h('span', { class: 'muted small' }, 'what happened after situations like this one')),
      h('p', { class: 'small', style: 'margin:6px 0' }, 'Today: ', (o.factors || []).map((f) => h('span', { class: 'tag', title: f.name }, f.text))),
      h('div', { style: 'overflow-x:auto' }, h('table', null, h('thead', null, h('tr', null, h('th', null, 'Looking ahead'), h('th', { class: 'num' }, 'Price was higher'), h('th', { class: 'num hide-sm' }, 'All situations'),
        h('th', { class: 'num hide-sm' }, 'Typical move (middle, 10th to 90th)'), h('th', { class: 'num hide-sm' }, 'Past cases'), h('th', null, 'Later-data test'))), h('tbody', null, rows))),
      h('p', { class: 'small muted', style: 'margin:6px 0 0' }, anyEdge ? 'Where the tag says "Beat the base rate", this table did better than simply using the all-situations share on prices it had not seen.' : 'In a test on later prices this table did not do meaningfully better than simply using the all-situations share, so read it as context, not as a forecast.',
        ' The range is how much the share moves when whole trading days are resampled.'),
      card && card.n ? h('p', { class: 'small muted', style: 'margin:4px 0 0' }, `Live check: of ${card.n} forecasts of this kind the app has made and resolved, the error was ${isNum(card.skill) && card.skill > 0 ? `${(card.skill * 100).toFixed(1)}% lower` : 'not lower'} than always saying the all-situations share.`) : null,
      h('p', { class: 'muted small', style: 'margin:4px 0 0' }, `A description of the past, not a prediction or a recommendation. Learned ${readStamp(o.generated_at)} from ${o.universe} stocks (${(o.span || []).join(' to ')}). Only price and volume factors are learned: past fundamentals are not available point in time. Prices exclude costs and dividends, the stock list is today's, and market conditions change.`));
  }

  function learningCard() {
    const l = S.data.learning;
    if (!l) return null;
    const rows = OUTLOOK_HORIZONS.filter(([k]) => (l.validation || {})[k]).map(([k, label]) => {
      const v = l.validation[k];
      return h('tr', null, h('td', null, label), h('td', { class: 'num' }, pc((l.base_rates || {})[k])), h('td', { class: 'num hide-sm' }, isNum(v.tested) ? v.tested.toLocaleString() : '–'),
        h('td', { class: 'num hide-sm' }, isNum(v.skill) ? `${(v.skill * 100).toFixed(2)}%` : '–'), h('td', null, h('span', { class: `tag ${v.edge ? 'buy' : ''}` }, v.edge ? 'Beat the base rate' : 'No reliable edge'), h('div', { class: 'muted small' }, v.reason || '')));
    });
    const c = l.scorecard || {};
    return h('details', { class: 'card', open: true },
      h('summary', null, h('b', null, 'What the app has learned '), h('span', { class: 'muted small' }, `from ${l.universe} stocks, ${(l.span || []).join(' to ')}, ${isNum(l.samples) ? l.samples.toLocaleString() : ''} situations, learned ${readStamp(l.generated_at)}`)),
      h('p', { class: 'small' }, 'Every week the app re-learns how often the price was higher after each combination of trend, RSI, MACD, 52-week position and volatility, and tests that on the later 40% of the dates. A pattern is called an edge only if it beat the all-situations share there by a margin that matters with its whole range above zero.'),
      h('div', { style: 'overflow-x:auto' }, h('table', null, h('thead', null, h('tr', null, h('th', null, 'Looking ahead'), h('th', { class: 'num' }, 'Price was higher (all situations)'), h('th', { class: 'num hide-sm' }, 'Later cases tested'), h('th', { class: 'num hide-sm' }, 'Error cut vs all-situations'), h('th', null, 'Result'))), h('tbody', null, rows))),
      c.n ? h('div', null, h('h4', null, `Forecasts made and resolved so far (${c.n})`), h('p', { class: 'small' }, `Error score ${c.brier} against ${c.brier_base} for always saying the all-situations share${isNum(c.skill) ? ` (${c.skill > 0 ? '' : '+'}${(-c.skill * 100).toFixed(1)}% change)` : ''}. A band that came true as often as it said is well calibrated.`),
        h('div', { style: 'overflow-x:auto' }, h('table', null, h('thead', null, h('tr', null, h('th', null, 'Said'), h('th', { class: 'num' }, 'Forecasts'), h('th', { class: 'num' }, 'Came true'))),
          h('tbody', null, (c.bands || []).map((b) => h('tr', null, h('td', null, `${b.from_pct}% to ${b.to_pct}%`), h('td', { class: 'num' }, b.n), h('td', { class: 'num' }, `${b.came_true_pct}%`))))))) : h('p', { class: 'muted small' }, 'No forecast has reached its date yet, so there is no live accuracy figure. The first ones resolve after 20 trading days.'),
      h('p', { class: 'muted small', style: 'margin-bottom:0' }, 'This describes the past. It does not change any reading, threshold or alert, and it is not tuned to beat buy-and-hold.'));
  }



  /* ---------- news intelligence: sources, de-duplicated stories, sentiment, impact, reaction and validation ---------- */
  const TONE_CLASS = { Positive: 'buy', Negative: 'warn', Mixed: '', Neutral: '' };
  const INTERPRETATION_CLASS = { Bullish: 'buy', Bearish: 'warn', Mixed: '', Neutral: '' };
  const VALIDATION_TEXT = { confirms: ['buy', 'Rough news tone agrees with the reading (experimental)'], conflicts: ['warn', 'Rough news tone runs against the reading (experimental)'], neutral: ['', 'Rough news tone neither agrees nor disagrees'] };
  const REACTION_TEXT = { 'price confirms': ['buy', 'Price confirms'], 'price diverges': ['warn', 'Price diverges'], 'no clear reaction': ['', 'No clear reaction'], unknown: ['', 'No price to compare'] };
  const when = (ts) => (isNum(ts) ? new Date(ts * 1000).toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : 'time not given');
  const signedInt = (v) => (isNum(v) ? `${v > 0 ? '+' : ''}${Math.round(v)}` : '–');

  function storyRow(st, withStock) {
    const official = st.kind === 'nse' || st.kind === 'bse';
    const sources = (st.sources && st.sources.length ? st.sources : [st.source]).filter(Boolean);
    return h('li', { class: 'newsstory' },
      h('div', null,
        withStock && st.symbol ? h('a', { href: '#stock=' + st.symbol, class: 'small', title: 'Open the stock' }, h('b', null, st.name || st.symbol), ' ') : (withStock ? h('b', { class: 'small' }, `${st.sector || 'Market'} `) : null),
        h('span', { class: `tag ${TONE_CLASS[st.tone] || ''}` }, `${st.tone} ${signedInt(st.sentiment)}`), ' ',
        h('span', { class: 'tag', title: 'How much this could matter: event type, credibility, relevance and how recent it is, from 0 to 100' }, `Impact ${st.impact}`), ' ',
        official ? h('span', { class: 'tag buy', title: 'An official filing on the exchange' }, 'Official') : null, isNum(st.ai_sentiment) ? h('span', { class: 'tag', title: `A language model scored this headline ${signedInt(st.ai_sentiment)} (the rule-based score is ${signedInt(st.rule_sentiment)}). It is shown for comparison and is not used in the sentiment above.` }, `AI view ${signedInt(st.ai_sentiment)}`) : null,
        h('span', { class: 'muted small' }, ` ${st.event_label}`)),
      h('div', null, safeUrl(st.link) ? h('a', { href: st.link, target: '_blank', rel: 'noopener noreferrer' }, st.title) : st.title),
      h('div', { class: 'muted small' }, `${sources.join(', ')} · ${when(st.ts)} · credibility ${st.credibility}`, st.duplicates ? ` · ${st.duplicates} repeat${st.duplicates === 1 ? '' : 's'} not counted` : '',
        isNum(st.age_hours) ? '' : ''));
  }

  function newsIntelCard(s) {
    const n = s.news_intel;
    if (!n || !n.stories) return h('section', { class: 'card wide', id: 'd-news-intel' }, h('h3', null, 'News intelligence'), h('p', { class: 'muted small', style: 'margin:0' }, n ? 'The stories load when this page opens.' : 'No recent news about this company was found in the exchange announcements, the news feeds or the headline search.'));
    const [vc, vt] = VALIDATION_TEXT[(n.validation || {}).state] || VALIDATION_TEXT.neutral;
    const [rc, rt] = REACTION_TEXT[(n.reaction || {}).state] || ['', ''];
    const f = n.fundamental || {};
    return h('section', { class: 'card wide', id: 'd-news-intel' },
      h('h3', null, 'News and rough tone (experimental) ', h('span', { class: `tag ${INTERPRETATION_CLASS[n.interpretation] || ''}` }, `Tone: ${n.interpretation}`), ' ', h('span', { class: `tag ${vc}` }, vt)),
      h('div', { class: 'kv' }, kv([['Overall sentiment', `${n.label} (${signedInt(n.sentiment)} on a scale from -100 to +100)`], ['News impact', `${n.impact} of 100`], ['Average credibility', `${n.credibility} of 100`],
        ['Fundamental impact', f.text || '–'], ['Market reaction', n.reaction ? h('span', null, h('span', { class: `tag ${rc}` }, rt), ' ', n.reaction.text) : '–']])),
      n.horizons && (n.horizons.short || n.horizons.long) ? h('p', { class: 'small' }, n.horizons.short ? h('span', null, h('b', null, 'Short term: '), n.horizons.short, ' ') : null, n.horizons.long ? h('span', null, h('b', null, 'Long term: '), n.horizons.long) : null) : null,
      h('p', { class: 'small' }, h('b', null, 'Explanation: '), n.explanation),
      (n.risks || []).length ? h('div', null, h('b', { class: 'small' }, 'Key risks'), h('ul', { class: 'clean small' }, n.risks.map((x) => h('li', null, x)))) : null,
      h('h4', null, 'Latest important news'), h('ul', { class: 'clean' }, (n.stories || []).slice(0, 6).map((st) => storyRow(st, false))),
      h('p', { class: 'muted small', style: 'margin-bottom:0' }, (n.validation || {}).text ? `${n.validation.text} ` : '', 'This is an experimental, rule-based reading of exchange filings and headlines (event type, word list, source credibility, recency), not a language model understanding the articles, except stories marked AI-scored. The tone is not used in the Buy or Sell reading, which comes from price and volume rules only. Headlines are shown as published, with their source and a link to the original.'));
  }

  const newsLine = (s) => {
    const n = s.news_intel;
    if (!n) return null;
    const [vc, vt] = VALIDATION_TEXT[typeof n.validation === 'object' ? (n.validation || {}).state : n.validation] || VALIDATION_TEXT.neutral;
    return h('div', { class: 'wide small', style: 'margin:6px 0' }, h('b', null, 'News: '), h('span', { class: `tag ${INTERPRETATION_CLASS[n.interpretation] || ''}` }, n.interpretation), ` sentiment ${signedInt(n.sentiment)}, impact ${n.impact}, ${n.n} stor${n.n === 1 ? 'y' : 'ies'} `, h('span', { class: `tag ${vc}` }, vt),
      n.top && n.top.title ? h('div', { class: 'muted' }, `${n.top.event_label || 'Latest'}: ${n.top.title} (${n.top.source || ''})`) : null);
  };

  /* The optional language-model job: what it did last, and how its scores compare with the rules (agreement is not accuracy). */
  function aiNote(ai) {
    if (!ai) return null;
    const st = ai.status;
    const lines = [];
    lines.push(ai.shadow ? 'AI scoring is in test mode: a hosted language model (GitHub Models) scores new headlines, and its score is shown beside the rule-based one but is not used in any sentiment, reading or alert.' : `AI scoring is on (weight ${ai.weight}).`);
    if (st) lines.push(`Last model run ${st.at ? new Date(st.at).toLocaleString() : 'unknown'}: ${st.outcome || 'no outcome recorded'}; ${st.scored || 0} scored, ${st.already_scored || 0} already scored, ${st.worth_scoring || 0} headlines worth scoring${st.error ? `. Stopped on: ${st.error}` : ''}.`);
    else lines.push('The model job has not reported a run yet, so there are no AI scores.');
    const a = ai.agreement;
    if (a && a.compared) lines.push(`Compared with the rules on ${a.compared} headlines: mean difference ${a.mean_abs_difference} points${isNum(a.same_direction_pct) ? `, same direction on ${a.same_direction_pct}% of ${a.firm_pairs} clear cases` : ''}. Agreement is not accuracy: there is no labelled test of either score yet.`);
    return h('div', { class: 'card' }, h('b', null, 'AI scoring (optional) '), lines.map((t) => h('p', { class: 'muted small', style: 'margin:4px 0' }, t)));
  }

  /* ---------- the Announcements tab: corporate actions, circuits, surveillance, gaps and the other market events (announcements.json) ---------- */
  async function fetchAnnouncements() {
    S.ann.state = 'loading';
    try {
      const response = await fetch('announcements.json', { cache: 'no-store' });
      if (!response.ok) throw new Error('announcements.json');
      S.ann.data = await response.json();
      S.ann.state = 'ready';
    } catch (err) { S.ann.state = 'failed'; }
    if (S.tab === 'announcements') render();
  }
  const ANN_TONE = { upper_circuit: 'buy', surge: 'buy', gap_up: 'buy', lower_circuit: 'warn', crash: 'warn', gap_down: 'warn', suspension: 'warn', delisting: 'warn', fo_ban: 'warn', asm: 'warn', gsm: 'warn' };
  const istParts = (ts) => {
    if (!isNum(ts)) return { day: 'Date unknown', time: '' };
    const d = new Date(ts * 1000);
    const fmt = (opts) => new Intl.DateTimeFormat('en-IN', Object.assign({ timeZone: 'Asia/Kolkata' }, opts)).format(d);
    const key = fmt({ year: 'numeric', month: '2-digit', day: '2-digit' });
    const today = new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
    const yesterday = new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(Date.now() - 86400000));
    return { day: key === today ? 'Today' : key === yesterday ? 'Yesterday' : fmt({ weekday: 'short', day: 'numeric', month: 'short' }), time: fmt({ hour: '2-digit', minute: '2-digit', hour12: false }) + ' IST' };
  };
  function annRow(r, mainSymbols) {
    const url = safeUrl(r.link);
    const parts = istParts(r.ts);
    const name = r.symbol ? h('a', { href: '#stock=' + r.symbol }, h('b', null, r.name || r.symbol)) : h('b', null, r.name || 'Market');
    return h('li', { class: 'newsstory' },
      h('div', null, h('span', { class: `tag ${ANN_TONE[r.type] || ''}`, title: r.group }, r.label), ' ', name, r.symbol && mainSymbols.has(r.symbol) ? h('span', { class: 'muted small' }, ' · main list') : null),
      h('div', { class: 'small' }, r.title || ''),
      r.detail ? h('div', { class: 'small muted' }, r.detail) : null,
      h('div', { class: 'small muted' }, `${r.source || ''} · ${parts.time}`, r.date ? ` · date ${r.date}` : '', url ? [' · ', h('a', { href: url, target: '_blank', rel: 'noopener noreferrer' }, 'Open the filing')] : ''));
  }
  function viewAnnouncements() {
    if (S.ann.state === 'idle') fetchAnnouncements();
    if (S.ann.state !== 'ready') {
      return h('div', null, h('h2', null, 'Announcements'), h('div', { class: 'empty' }, S.ann.state === 'failed' ? 'The announcements could not be loaded. They appear after the next update.' : 'Loading announcements...'));
    }
    const d = S.ann.data;
    const f = S.annFilters;
    const mainSymbols = new Set((S.data.stocks || []).map((x) => x.symbol));
    const types = d.types || {};
    const groups = [...new Set(Object.values(types).map((t) => t.group))];
    const list = h('div', null);
    const status = h('p', { class: 'muted small' });
    const draw = () => {
      const q = f.q.trim().toLowerCase();
      const rows = (d.items || []).filter((r) => (f.group === 'ALL' || r.group === f.group) && (f.type === 'ALL' || r.type === f.type) && (!f.main || mainSymbols.has(r.symbol))
        && (!q || `${r.name || ''} ${r.symbol || ''} ${r.title || ''} ${r.label}`.toLowerCase().includes(q)));
      status.textContent = `${rows.length} of ${(d.items || []).length} events from the last 7 days. Newest first.`;
      const days = [];
      for (const r of rows.slice(0, 300)) {
        const day = istParts(r.ts).day;
        if (!days.length || days[days.length - 1].day !== day) days.push({ day, rows: [] });
        days[days.length - 1].rows.push(r);
      }
      list.replaceChildren(...(days.length ? days.map((g) => h('div', { class: 'card' }, h('h4', { style: 'margin:0 0 4px' }, g.day), h('ul', { class: 'clean' }, g.rows.map((r) => annRow(r, mainSymbols)))))
        : [h('div', { class: 'empty' }, 'No event matches these filters.')]));
    };
    const sel = (label, key, options) => h('label', { class: 'field' }, label, h('select', { onchange: (e) => { f[key] = e.target.value; if (key === 'group') f.type = 'ALL'; render(); } },
      options.map(([v, text]) => h('option', { value: v, selected: f[key] === v }, text))));
    const typeOptions = [['ALL', 'Any type']].concat(Object.entries(types).filter(([, t]) => f.group === 'ALL' || t.group === f.group).map(([k, t]) => [k, `${t.label} (${(d.counts || {})[k] || 0})`]));
    const sources = (d.sources || []).map((x) => h('tr', null, h('td', null, x.name), h('td', null, h('span', { class: `tag ${x.ok ? 'buy' : 'warn'}` }, x.ok ? 'Working' : 'Not read yet')),
      h('td', { class: 'small muted hide-sm' }, x.error || (x.fetched_at ? `read ${readStamp(x.fetched_at)}` : ''))));
    const root = h('div', null,
      h('h2', null, 'Announcements and market events ', h('span', { class: 'muted small' }, `updated ${readStamp(d.generated_at)}`)),
      h('p', { class: 'muted small' }, 'Mergers, demergers and schemes, bonus, splits, buybacks and rights, record dates, trading suspensions and delistings, upper and lower circuits, ASM and GSM lists, the F&O ban list, gaps at the open, surges and crashes. Kept for 7 days.'),
      h('div', { class: 'card filterbar' }, h('div', { class: 'row' },
        h('label', { class: 'field' }, 'Search', h('input', { type: 'search', placeholder: 'Company, symbol or words', value: f.q, oninput: (e) => { f.q = e.target.value; draw(); } })),
        sel('Group', 'group', [['ALL', 'All groups']].concat(groups.map((g) => [g, g]))),
        sel('Type', 'type', typeOptions),
        h('label', { class: 'field' }, h('span', null, 'Stocks in the main list'), h('input', { type: 'checkbox', checked: f.main, onchange: (e) => { f.main = e.target.checked; draw(); } })))),
      status, list,
      h('details', { class: 'card' }, h('summary', null, h('b', null, 'Sources '), h('span', { class: 'muted small' }, `${(d.sources || []).filter((x) => x.ok).length} of ${(d.sources || []).length} working`)),
        h('div', { style: 'overflow-x:auto' }, h('table', null, h('thead', null, h('tr', null, h('th', null, 'Source'), h('th', null, 'State'), h('th', { class: 'hide-sm' }, 'Detail'))), h('tbody', null, sources))),
        h('p', { class: 'muted small', style: 'margin-bottom:0' }, 'Filings and lists come from the NSE and BSE and are official. What kind of announcement it is gets decided by the exchange category, then by fixed phrases, so an unusual wording can be missed. Circuits are worked out from the NSE price bands, gaps, surges and crashes from delayed Yahoo quotes. This is information, not advice.')));
    draw();
    return root;
  }

  /* ---------- the News tab and the Sentiment Dashboard ---------- */
  function viewNews() {
    const d = S.data.news_intel;
    if (!d) return h('div', null, h('h2', null, 'News'), h('div', { class: 'empty' }, 'News intelligence is not available in this data yet. It appears after the next update.'));
    const nf = S.newsFilters;
    const sectors = [...new Set((d.stories || []).map((x) => x.sector).filter(Boolean))].sort();
    const list = h('ul', { class: 'clean' });
    const status = h('p', { class: 'muted small' });
    const draw = () => {
      const q = nf.q.trim().toLowerCase();
      const rows = (d.stories || []).filter((x) => (nf.tone === 'ALL' || x.tone === nf.tone) && (!nf.official || x.kind === 'nse' || x.kind === 'bse') && (nf.sector === 'ALL' || x.sector === nf.sector)
        && (!nf.tracked || x.tracked) && (!q || `${x.title} ${x.name || ''} ${x.symbol || ''} ${x.event_label}`.toLowerCase().includes(q)));
      status.textContent = `${rows.length} stor${rows.length === 1 ? 'y' : 'ies'} shown of the ${d.stories.length} most important. Sorted by impact and recency; repeats of the same story across outlets and exchanges count once.`;
      list.replaceChildren(...(rows.length ? rows.slice(0, 80).map((x) => storyRow(x, true)) : [h('li', { class: 'empty' }, 'No story matches these filters.')]));
    };
    const sel = (label, key, options) => h('label', { class: 'field' }, label, h('select', { onchange: (e) => { nf[key] = e.target.value; draw(); } }, options.map(([v, text]) => h('option', { value: v, selected: nf[key] === v }, text))));
    const toneWord = d.market_tone >= 20 ? 'leaning positive' : d.market_tone <= -20 ? 'leaning negative' : 'neutral';
    const cnt = d.counts || {};
    const sectorRows = (d.sectors || []).map((x) => h('tr', null, h('td', null, x.sector), h('td', { class: 'num' }, x.stocks),
      h('td', { class: 'num' }, h('span', { class: `tag ${x.sentiment >= 20 ? 'buy' : x.sentiment <= -20 ? 'warn' : ''}` }, signedInt(x.sentiment))), h('td', { class: 'num hide-sm' }, x.impact),
      h('td', { class: 'num hide-sm' }, `${x.positive} / ${x.negative} / ${x.mixed}`), h('td', { class: 'num' }, isNum(x.price_move_pct) ? signed(x.price_move_pct) : '–'),
      h('td', null, h('span', { class: `tag ${(REACTION_TEXT[x.state] || [''])[0]}` }, (REACTION_TEXT[x.state] || ['', x.state])[1]))));
    const stockList = (title, rows) => (rows || []).length ? h('div', { class: 'card' }, h('h4', { style: 'margin:0 0 4px' }, title),
      h('ul', { class: 'clean small' }, rows.map((r) => h('li', null, h('a', { href: '#stock=' + r.symbol }, h('b', null, r.name)), ` ${signedInt(r.sentiment)}, impact ${r.impact}`, isNum(r.change_pct) ? `, price ${signed(r.change_pct)}` : '', r.validation && r.validation !== 'neutral' ? ` · ${VALIDATION_TEXT[r.validation][1].toLowerCase()}` : '')))) : null;
    const providers = (d.providers || []).map((x) => h('tr', null, h('td', null, x.name), h('td', null, h('span', { class: `tag ${x.ok ? 'buy' : 'warn'}` }, x.ok ? 'Working' : 'Down')),
      h('td', { class: 'num' }, x.items), h('td', { class: 'small muted hide-sm' }, x.error || (x.fetched_at ? `read ${readStamp(x.fetched_at)}` : ''))));
    const root = h('div', null,
      h('h2', null, 'News ', h('span', { class: 'muted small' }, `updated ${readStamp(d.generated_at)}`)),
      h('div', { class: 'card small' }, h('b', null, 'Headlines, sources and official filings are the reliable part. '),
        'The tone score and the market tone below are experimental: they come from a word list that has not been tested against labelled headlines, so they can be wrong (for example on a fall from a record high). They are not used in any Buy or Sell reading, any Telegram alert or the track record.'),
      h('details', { class: 'card', open: true },
        h('summary', null, h('b', null, 'Rough tone dashboard (experimental) '), h('span', { class: `tag ${d.market_tone >= 20 ? 'buy' : d.market_tone <= -20 ? 'warn' : ''}` }, `Market news ${toneWord} (${signedInt(d.market_tone)})`)),
        h('p', { class: 'small' }, `${cnt.stories_shown} important stories from ${cnt.stocks_with_news} stocks; ${cnt.duplicates_removed} repeated copies were not counted; ${cnt.official_share_pct === null ? 'no' : cnt.official_share_pct + '%'} are official exchange filings.`,
          d.ai && d.ai.enabled ? ` ${d.ai.scored} are also scored by a language model (${d.ai.model}, via GitHub Models).` : ' Sentiment is rule-based; no language model score is available right now.'),
        (d.sectors || []).length ? h('div', { style: 'overflow-x:auto' }, h('table', null, h('thead', null, h('tr', null, h('th', null, 'Sector'), h('th', { class: 'num' }, 'Stocks with news'), h('th', { class: 'num' }, 'Sentiment'), h('th', { class: 'num hide-sm' }, 'Impact'),
          h('th', { class: 'num hide-sm' }, 'Pos / neg / mixed'), h('th', { class: 'num' }, 'Sector move today'), h('th', null, 'Price vs news'))), h('tbody', null, sectorRows))) : h('p', { class: 'muted small' }, 'No sector has enough news yet.'),
        h('div', { class: 'grid', style: 'margin-top:8px' }, stockList('Most positive news', d.top_positive), stockList('Most negative news', d.top_negative), stockList('Price disagrees with the news', d.divergences)),
        h('p', { class: 'muted small' }, 'Events in the stories: ' + (Object.entries(d.events || {}).slice(0, 8).map(([k, v]) => `${k} ${v}`).join(', ') || 'none') + '.')),
      h('details', { class: 'card' }, h('summary', null, h('b', null, 'News sources '), h('span', { class: 'muted small' }, `${(d.providers || []).filter((x) => x.ok).length} of ${(d.providers || []).length} working`)),
        h('div', { style: 'overflow-x:auto' }, h('table', null, h('thead', null, h('tr', null, h('th', null, 'Source'), h('th', null, 'State'), h('th', { class: 'num' }, 'Items'), h('th', { class: 'hide-sm' }, 'Detail'))), h('tbody', null, providers))),
        h('p', { class: 'muted small', style: 'margin-bottom:0' }, 'Official: NSE corporate announcements and BSE corporate announcements. News: Business Standard, Mint, The Economic Times, Moneycontrol and The Hindu BusinessLine (public RSS feeds, headlines and links only) and Google News for each company. If a source is down the others carry on and recent items are kept. Stories link to the original; attribution is to the source named.',
          ''),
        aiNote(d.ai)),
      h('div', { class: 'card filterbar' }, h('div', { class: 'row' },
        h('label', { class: 'field' }, 'Search', h('input', { type: 'search', placeholder: 'Company, event or words', value: nf.q, oninput: (e) => { nf.q = e.target.value; draw(); } })),
        sel('Sentiment', 'tone', [['ALL', 'Any'], ['Positive', 'Positive'], ['Negative', 'Negative'], ['Neutral', 'Neutral']]),
        sel('Sector', 'sector', [['ALL', 'All sectors']].concat(sectors.map((x) => [x, x]))),
        h('label', { class: 'field' }, h('span', null, 'Official filings only'), h('input', { type: 'checkbox', checked: nf.official, onchange: (e) => { nf.official = e.target.checked; draw(); } })),
        h('label', { class: 'field' }, h('span', null, 'Stocks in the main list'), h('input', { type: 'checkbox', checked: nf.tracked, onchange: (e) => { nf.tracked = e.target.checked; draw(); } })))),
      status, list,
      h('p', { class: 'muted small' }, 'Sentiment runs from -100 (very negative) to +100 (very positive) and impact from 0 to 100. They describe the news, not the stock: they are not a Buy or Sell reading and are not a forecast.'));
    draw();
    return root;
  }

  const ageText = (minutes) => (!isNum(minutes) ? '' : minutes < 60 ? `${minutes} min ago` : minutes < 2880 ? `${Math.round(minutes / 60)} h ago` : `${Math.round(minutes / 1440)} days ago`);

  /* ---------- data health: what the app has learned about its own data ---------- */
  function dataHealthCard() {
    const d = S.data.data_health;
    if (!d) return null;
    const rows = (d.sources || []).map((x) => h('tr', null, h('td', null, x.name), h('td', { class: 'num' }, isNum(x.reliability) ? `${Math.round(x.reliability * 100)}%` : '–', h('div', { class: 'muted small' }, `last ${x.runs} runs`)),
      h('td', null, h('span', { class: `tag ${x.state === 'degraded' ? 'warn' : 'buy'}` }, x.state === 'degraded' ? 'Degraded' : 'Working')),
      h('td', { class: 'small hide-sm' }, x.last_fail ? `${readStamp(x.last_fail)}${x.detail ? ': ' + x.detail : ''}` : '–')));
    const hours = (d.lag_hours_ist || []);
    const q = d.quarantined || [];
    return h('details', { class: 'card', open: q.length > 0 || (d.sources || []).some((x) => x.state === 'degraded') },
      h('summary', null, h('b', null, 'Data health '), h('span', { class: 'muted small' }, `learned from ${d.runs_observed} runs`),
        q.length ? h('span', { class: 'tag warn' }, `${q.length} stock${q.length === 1 ? '' : 's'} paused`) : h('span', { class: 'tag buy' }, 'No stock paused')),
      h('p', { class: 'small' }, 'Every run the app records which data sources worked and which stocks had data problems. A stock with problems in ' + (d.rules || {}).quarantine + ' is paused (no alerts, no tracked readings) until it has been clean for ' + (d.rules || {}).release + '. Sources below ' + Math.round(((d.rules || {}).degraded_below || 0.8) * 100) + '% are shown as degraded.'),
      h('div', { style: 'overflow-x:auto' }, h('table', null, h('thead', null, h('tr', null, h('th', null, 'Source'), h('th', { class: 'num' }, 'Reliability'), h('th', null, 'State'), h('th', { class: 'hide-sm' }, 'Last problem'))), h('tbody', null, rows))),
      hours.length ? h('p', { class: 'small' }, h('b', null, 'Observed lag hours (IST): '), hours.map((x) => `${String(x).padStart(2, '0')}:00`).join(', '), '. Yahoo\'s daily series was seen missing the newest session in these hours, so new readings in them wait for the series to catch up.') : h('p', { class: 'small muted' }, 'No hour of the day has shown a pattern of lagging prices yet.'),
      q.length ? h('div', null, h('h4', null, 'Paused stocks'), h('ul', { class: 'clean small' }, q.map((x) => h('li', null, h('b', null, x.symbol), ` since ${readStamp(x.since)}: ${(x.reasons || []).join('; ')}`)))) : null,
      h('p', { class: 'muted small', style: 'margin-bottom:0' }, 'This decides how far the data can be trusted right now. It never changes a reading, a score or a threshold.'));
  }

  /* Where the numbers come from and how current they are. */
  function dataNote(s) {
    const lines = [`Prices: free Yahoo Finance data, delayed by up to about 15 minutes. Price date ${s.as_of}.`,
      `Readings use completed daily candles up to ${s.confirmed_as_of || s.as_of}.`];
    const live = s.live;
    return h('div', { class: 'card wide small datanote' },
      lines.map((l) => h('div', null, l)),
      s.provisional ? h('div', { class: 'provnote' }, h('b', null, 'Market open: '), `today's candle is unfinished, so the readings above are from the last completed day. Provisional reading with today's price so far (volume left out): ${live ? `weeks view ${labelText(live.short.label)}${isNum(live.short.score) ? ` ${live.short.score > 0 ? '+' : ''}${live.short.score}` : ''}, months-to-years view ${labelText(live.long.label)}${isNum(live.long.score) ? ` ${live.long.score > 0 ? '+' : ''}${live.long.score}` : ''}` : 'not available'}. It is recalculated after the close.`) : null);
  }

  /* Every level in one list, highest price first, so the gaps above and below the price read at a glance. */
  function levelRows(s) {
    const zones = ((s.levels || {}).zones) || { support: [], resistance: [] };
    const rows = [];
    for (const z of zones.resistance.slice(0, 1)) rows.push({ kind: 'res', label: 'Resistance', note: 'a price area where rises have stalled before', v: z.level });
    for (const z of zones.support.slice(0, 1)) rows.push({ kind: 'sup', label: 'Support', note: 'a price area where falls have paused before', v: z.level });
    if (s.stop && isNum(s.stop.price)) rows.push({ kind: 'risk', label: 'Risk level', note: 'two average daily ranges below the price; a close below it means the move has gone against the reading', v: s.stop.price });
    return rows.filter((r) => isNum(r.v)).sort((a, b) => b.v - a.v);
  }

  /* Where the price sits: resistance, support and risk level as one small table, with the 52-week range under it. */
  const shortDay = (iso) => (typeof iso === 'string' && iso.length === 10 ? new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' }) : 'unknown date');
  /* A bar from a low to a high with a marker at the price. Nothing is drawn unless low, high and price are all numbers and the high is above the low. */
  function rangeBar(title, low, high, price, currency) {
    if (!(isNum(low) && isNum(high) && isNum(price) && high > low)) return null;
    const pos = clamp((price - low) / (high - low) * 100, 0, 100);
    return h('div', { class: 'rangebox' },
      h('div', { class: 'rangetop small' }, h('span', { class: 'muted' }, title), h('span', null, `${pos.toFixed(0)}% of the way up`)),
      h('div', { class: 'rangeline small' }, h('span', null, money(low, currency)),
        h('div', { class: 'rangebar', role: 'img', 'aria-label': `${title}: the price is at ${pos.toFixed(0)} percent of the range from ${money(low, currency)} to ${money(high, currency)}` }, h('i', { style: `left:${pos}%` })),
        h('span', null, money(high, currency))));
  }

  /* Today's range (the newest candle: the day so far while the market is open, else the last session) and the 52-week range. */
  function rangesBlock(s) {
    const i = s.indicators || {}, day = s.day || {};
    const bars = [rangeBar(s.provisional ? "Today's range so far" : `Day range, ${shortDay(s.as_of)}`, day.low, day.high, s.price, s.currency),
      rangeBar('52-week range', i.lo252, i.hi252, s.price, s.currency)].filter(Boolean);
    return bars.length ? h('div', { class: 'ranges' }, bars) : null;
  }

  /* The latest results and the price against the index, one factual card each. A card with no figure behind it is not shown, and nothing is called good or bad:
     the colour only says up or down. */
  function insightCards(s) {
    const sum = (s.statements || {}).summary || {};
    const cards = [];
    const trend = (label, key) => {
      const q = (sum.qoq || {})[key], y = (sum.yoy || {})[key];
      if (!isNum(q) && !isNum(y)) return;
      const main = isNum(q) ? q : y;
      cards.push({ label, value: signed(main, 1), tone: main > 0 ? 'up' : main < 0 ? 'down' : '',
        text: isNum(q) ? (isNum(y) ? `qtr · YoY ${signed(y, 0)}` : 'vs last quarter') : 'vs a year ago', hint: isNum(q) ? `${signed(q, 1)} on the quarter before${isNum(y) ? `; ${signed(y, 1)} on a year earlier` : ''}` : `${signed(y, 1)} on a year earlier` });
    };
    trend('Revenue', 'revenue'); trend('Op. profit', 'operating_income'); trend('Net profit', 'net_income');
    const rs = (s.indicators || {}).rs126;
    if (isNum(rs)) cards.push({ label: 'Vs index', value: signed(rs, 1, ' pts'), tone: rs > 0 ? 'up' : rs < 0 ? 'down' : '', text: '6 months', hint: `${rs >= 0 ? 'Ahead of' : 'Behind'} the index by ${Math.abs(rs).toFixed(1)} percentage points over 6 months` });
    const pe = (s.fundamentals || {}).pe, median = (ruleContext().sectorPE || {})[s.sector];
    if (isNum(pe) && pe > 0 && median) cards.push({ label: 'P/E vs sector', value: `${(pe / median).toFixed(2)}×`, tone: '', text: `${pe.toFixed(1)} vs ${median.toFixed(1)}`, hint: `P/E ${pe.toFixed(1)} against a sector median of ${median.toFixed(1)}` });
    if (!cards.length) return null;
    return h('div', { class: 'insightbox' },
      h('div', { class: 'insights', role: 'list', 'aria-label': 'Results at a glance' }, cards.map((c) => h('div', { class: 'insight', role: 'listitem', title: c.hint || '' },
        h('span', { class: 'muted small' }, c.label), h('b', { class: c.tone }, c.value), h('span', { class: 'small muted' }, c.text)))),
      sum.latest_quarter ? h('p', { class: 'muted small', style: 'margin:4px 0 0' }, `Quarter to ${quarterDay(sum.latest_quarter)} · reported facts, not a view`) : null);
  }

  function priceMap(s) {
    const rows = levelRows(s);
    if (!rows.length || !isNum(s.price)) return null;
    const tiles = rows.map((r) => h('div', { class: `ltile l-${r.kind}`, title: `${r.label}: ${r.note}` },
      h('span', { class: 'small' }, r.label), h('b', null, money(r.v, s.currency)), h('span', { class: 'small muted' }, signed((r.v / s.price - 1) * 100, 1))));
    const help = rows.length ? h('details', { class: 'mapnote small' }, h('summary', null, 'What do these levels mean?'),
      h('p', { class: 'muted', style: 'margin:4px 0 0' }, 'Resistance: rises have stalled here before. Support: falls have paused here before. Risk level: two average daily ranges below the price. They come from fixed rules on past prices and are references, not advice.')) : null;
    return h('div', { class: 'pmap' }, h('div', { class: 'levelstrip', role: 'list', 'aria-label': 'Reference levels' }, tiles), help);
  }

  function positionCalculator(s) {
    const out = h('p', { class: 'small', 'aria-live': 'polite' });
    const capital = h('input', { type: 'number', min: '0', step: 'any', value: S.calc.capital, 'aria-label': 'Capital' });
    const risk = h('input', { type: 'number', min: '0.1', max: '100', step: '0.1', value: S.calc.risk, 'aria-label': 'Risk per trade in percent' });
    const update = () => {
      const cap = parseFloat(capital.value), pct = parseFloat(risk.value);
      if (!(cap > 0) || !(pct > 0 && pct <= 100)) { out.textContent = 'Enter a capital above 0 and a risk between 0.1% and 100%.'; return; }
      S.calc = { capital: cap, risk: pct }; store.set('calc', S.calc);
      if (!s.stop) { out.textContent = 'No volatility risk level is available for this stock, so a position size cannot be worked out.'; return; }
      const perShare = s.price - s.stop.price;
      const shares = Math.floor((cap * pct / 100) / perShare);
      const value = shares * s.price;
      out.textContent = `If the price reaches the volatility risk level at ${money(s.stop.price, s.currency)} you lose about ${money(cap * pct / 100, s.currency)} (${pct}% of capital). That allows ${shares} share${shares === 1 ? '' : 's'}, a position of ${money(value, s.currency)} (${(value / cap * 100).toFixed(0)}% of capital).` + (value > cap ? ' This is larger than your capital: use a smaller risk or a wider risk level.' : '');
    };
    capital.addEventListener('input', update); risk.addEventListener('input', update);
    update();
    return section('Position size', h('div', { class: 'row' },
      h('label', { class: 'field' }, `Capital (${CURRENCY[s.currency] || s.currency || ''})`, capital), h('label', { class: 'field' }, 'Risk per trade (%)', risk)), out,
      h('p', { class: 'muted small' }, 'Prices can gap past the risk level, so the real loss can be bigger.'));
  }

  function backtestBlock(b, title) {
    if (!b) return h('div', null, h('h3', null, title), h('p', { class: 'muted small' }, 'Not enough history to test this rule.'));
    const o = b.oos;
    const years = Math.round(b.tested_days / 252 * 10) / 10;
    const verdict = b.total_return > b.buy_hold_return
      ? `Over the whole ${years} years the rule beat buy-and-hold.` : `Over the whole ${years} years the rule did NOT beat buy-and-hold.`;
    const recent = o.total_return > o.buy_hold_return ? 'It also beat it in the most recent 40%.' : 'It did not beat it in the most recent 40% either.';
    const both = (b.total_return > b.buy_hold_return) === (o.total_return > o.buy_hold_return);
    return h('div', null, h('h3', null, title),
      h('p', { class: b.total_return > b.buy_hold_return ? 'pos' : 'neg' }, verdict, ' ', both ? recent : (o.total_return > o.buy_hold_return ? 'It did beat it in the most recent 40%.' : 'It did not beat it in the most recent 40%.')),
      b.few_trades ? h('p', { class: 'tag warn' }, 'Few trades, so the result is not reliable') : null,
      h('table', null, h('thead', null, h('tr', null, h('th', null, ''), h('th', { class: 'num' }, 'Rule (after costs)'), h('th', { class: 'num' }, 'Buy and hold'))),
        h('tbody', null,
          h('tr', null, h('td', null, `Whole test, total`), h('td', { class: 'num' }, percent(b.total_return)), h('td', { class: 'num' }, percent(b.buy_hold_return))),
          h('tr', null, h('td', null, 'Whole test, per year'), h('td', { class: 'num' }, percent(b.cagr)), h('td', { class: 'num' }, percent(b.buy_hold_cagr))),
          h('tr', null, h('td', null, 'Recent 40%, total'), h('td', { class: 'num' }, percent(o.total_return)), h('td', { class: 'num' }, percent(o.buy_hold_return))),
          b.total ? [h('tr', { class: 'divrow' }, h('td', null, 'With dividends: whole test'), h('td', { class: 'num' }, percent(b.total.total_return)), h('td', { class: 'num' }, percent(b.total.buy_hold_return))),
            h('tr', { class: 'divrow' }, h('td', null, 'With dividends: recent 40%'), h('td', { class: 'num' }, percent(b.total.recent_total_return)), h('td', { class: 'num' }, percent(b.total.recent_buy_hold_return)))] : null)),
      kv([['Before costs', percent(b.gross_return)], ['Cost drag', percent(b.cost_drag)], ['Trades', b.trades], ['Win rate', percent(b.win_rate, 0)], ['Profit factor', number(b.profit_factor)],
        ['Average trade', percent(b.expectancy)], ['Worst fall', percent(b.max_drawdown, 0)], ['Sharpe', number(b.sharpe)], ['Sortino', number(b.sortino)], ['Time invested', percent(b.exposure, 0)]]),
      b.open_at_end ? h('p', { class: 'muted small' }, 'A position was still open at the end; it is counted as sold at the last close, less costs.') : null);
  }

  /* The assumptions and limits behind every backtest figure, published with the data. */
  function backtestMethod(s) {
    const m = S.data.backtest_method;
    if (!m) return null;
    const c = (m.costs || {}).IN;
    return h('details', { class: 'card wide' }, h('summary', null, 'Assumptions and limits of these tests'),
      c ? h('p', { class: 'small' }, `Costs assumed for this market: ${c.entry_pct}% to buy and ${c.exit_pct}% to sell (${c.round_trip_pct}% for a round trip), including taxes, fees and slippage. These are assumptions: your broker's charges differ.`) : null,
      h('ul', { class: 'clean small' }, (m.notes || []).map((n) => h('li', null, n))));
  }

  function fundamentalsBlock(s) {
    const f = s.fundamentals || {};
    if (!Object.keys(f).length && !isNum(s.dividend_yield)) return h('p', { class: 'muted small' }, 'Fundamentals are not available for this stock right now.');
    const cur = s.currency;
    const group = (title, pairs) => h('div', { style: 'margin-bottom:10px' }, h('h4', { style: 'margin:8px 0 4px' }, title), kv(pairs));
    return h('div', null,
      group('Valuation', [['Market cap', big(f.market_cap, cur)], ['Enterprise value', big(f.enterprise_value, cur)], ['P/E (trailing)', number(f.pe, 1)], ['Forward P/E', number(f.forward_pe, 1)],
        ['PEG', number(f.peg, 2)], ['Price/Book', number(f.pb, 1)], ['Price/Sales', number(f.price_to_sales, 1)], ['EV/EBITDA', number(f.ev_ebitda, 1)], ['EV/Revenue', number(f.ev_revenue, 1)]]),
      group('Earnings and margins', [['Revenue', big(f.revenue, cur)], ['EBITDA', big(f.ebitda, cur)], ['EBITDA margin', percent(f.ebitda_margin)], ['Operating margin', percent(f.operating_margin)],
        ['Gross margin', percent(f.gross_margin)], ['Profit margin', percent(f.profit_margin)], ['EPS (trailing)', number(f.eps, 2)], ['Revenue growth', percent(f.revenue_growth)],
        ['Earnings growth', percent(f.earnings_growth)]]),
      group('Balance sheet and returns', [['Return on equity', percent(f.roe)], ['Return on assets', percent(f.roa)], ['Debt/Equity', number(f.debt_to_equity)], ['Total debt', big(f.total_debt, cur)],
        ['Cash', big(f.total_cash, cur)], ['Current ratio', number(f.current_ratio, 2)], ['Free cash flow', big(f.free_cash_flow, cur)], ['Operating cash flow', big(f.operating_cash_flow, cur)],
        ['Book value per share', number(f.book_value, 2)]]),
      group('Shareholder returns', [['Dividend yield (12 months)', percent(s.dividend_yield, 2)], ['Payout ratio', percent(f.payout_ratio, 0)]]),
      h('p', { class: 'muted small' }, 'Figures are as reported by Yahoo Finance for the last twelve months, in the company\'s reporting currency. A blank (n/a) means Yahoo has no value; nothing is estimated. They are shown as they are: no rating or "cheap/expensive" label is made from them.'));
  }

  /* Every dividend figure with the payments it is added up from, so it can be checked by hand, then a cross-check against Yahoo's own indicated amount. */
  function dividendCheck(s) {
    const c = s.dividend_check;
    if (!c) return h('p', { class: 'muted small' }, 'Cross-check: Yahoo shows no indicated annual dividend for this stock, so there is nothing to compare with.');
    const f = (v) => money(v, s.currency);
    const cls = c.status === 'agrees' ? '' : 'warn';
    const verdict = { agrees: 'Agrees', differs: 'Differs', not_paid: 'No payment here yet' }[c.status] || c.status;
    return h('div', { class: 'card', style: 'padding:10px 12px;margin-top:10px' },
      h('p', { style: 'margin:0 0 4px' }, h('strong', null, 'Cross-check with Yahoo: '), h('span', { class: `tag ${cls}` }, verdict)),
      h('p', { class: 'small', style: 'margin:0' }, `Yahoo's indicated annual dividend is ${f(c.rate)} a share (${percent(c.yield, 2)} of the price). `,
        isNum(c.ours_ttm) ? `Here, the last 12 months add up to ${f(c.ours_ttm)}` : '', isNum(c.ours_forward) ? ` and the recurring yearly dividend to ${f(c.ours_forward)}. ` : '. ',
        c.status === 'agrees' ? 'The two are within 15% of each other.' : ''),
      c.note ? h('p', { class: 'muted small', style: 'margin:4px 0 0' }, c.note) : null);
  }

  function dividendBlock(s) {
    const d = s.dividend;
    const f = (v) => money(v, s.currency);
    if (!d) return h('div', null, h('p', { class: 'muted small' }, 'No dividend has gone ex-dividend in the last two years.'), dividendCheck(s));
    const per = d.payments_per_year;
    const plural = (n) => (n === 1 ? '' : 's');
    const sum = (list) => list.map((p) => `${p.date} ${f(p.amount)}`).join(' + ');
    const ttm = d.ttm_payments || [];
    const oneOffs = ttm.filter((p) => p.special);
    const inYear = new Set(ttm.map((p) => p.date));
    const rhythm = d.rhythm === 'uneven' ? 'The gaps between payments are uneven (for example an interim and a final dividend), so the number of payments a year was used.'
      : d.rhythm === 'even' ? 'The payments come at an even rhythm.' : '';
    const steps = [
      `1. Payments with an ex-dividend date in the last 12 months (${d.ttm_count}): ${ttm.length ? sum(ttm) : 'none'} = ${f(d.ttm_amount)}.`,
      `2. 12-month yield = ${f(d.ttm_amount)} ÷ price ${f(s.price)} = ${percent(d.ttm_yield, 2)}.`,
      oneOffs.length ? `3. One-off payment${plural(oneOffs.length)} (more than 3 times the usual and not repeated): ${sum(oneOffs)}. Without ${oneOffs.length === 1 ? 'it' : 'them'} the 12-month amount is ${f(d.ttm_regular_amount)} (${percent(d.ttm_regular_yield, 2)}).`
        : `3. No one-off payments were found, so the recurring figure is the same as the 12-month one.${(d.large_kept || []).length ? ` Payment${(d.large_kept || []).length === 1 ? '' : 's'} much larger than the usual (${sum(d.large_kept)}) ${(d.large_kept || []).length === 1 ? 'was' : 'were'} kept as regular because ${(d.large_kept || []).length === 1 ? 'it repeats' : 'they repeat'} at the same time each year or ${(d.large_kept || []).length === 1 ? 'sits' : 'sit'} next to another payment at the same level. If the company calls ${(d.large_kept || []).length === 1 ? 'it' : 'them'} a special dividend, expect the recurring figure to be lower.` : ''}`,
      per ? `4. Pattern: ${d.frequency} (${per} payment${plural(per)} a year). ${rhythm}` : `4. Pattern: ${d.frequency}. ${d.frequency === 'Single payment' ? 'One regular payment is not enough to say it recurs.' : 'There is no clear pattern.'}`,
      isNum(d.forward_amount) ? `5. Recurring yearly dividend = the last ${per} regular payment${plural(per)}: ${sum(d.forward_payments || [])} = ${f(d.forward_amount)}; yield ${f(d.forward_amount)} ÷ ${f(s.price)} = ${percent(d.forward_yield, 2)}.`
        : '5. Recurring yearly dividend: cannot be estimated from this history.'];
    return h('div', null,
      h('div', { class: 'card', style: 'padding:10px 12px' }, h('h4', { style: 'margin:0 0 6px' }, 'How the figures are worked out'),
        steps.map((line) => h('p', { class: 'small', style: 'margin:0 0 4px' }, line))),
      kv([
        ['Payment pattern', d.frequency + (per ? ` (${per} a year)` : '')],
        ['Paid in last 12 months', `${d.ttm_count} payment${plural(d.ttm_count)}, ${f(d.ttm_amount)} per share`],
        ['Yield on 12-month payments', percent(d.ttm_yield, 2)],
        ['Recurring yearly dividend', isNum(d.forward_amount) ? `${f(d.forward_amount)} per share` : 'Cannot be estimated'],
        ['Yield on recurring dividend', isNum(d.forward_yield) ? percent(d.forward_yield, 2) : '–'],
        ['Last payment', `${f(d.last_amount)} on ${d.last_date} (${percent(d.last_pct_of_price, 2)} of price)`],
        ['Change vs previous 12 months', isNum(d.growth) ? signed(d.growth * 100, 1) : 'Not comparable'],
        ['Payout ratio', percent((s.fundamentals || {}).payout_ratio, 0)]]),
      dividendCheck(s),
      d.overdue ? h('p', { class: 'tag warn' }, 'A payment looks overdue. The usual schedule says one should have been paid by now, so the dividend may have been cut or paused.') : null,
      h('table', null, h('thead', null, h('tr', null, h('th', null, 'Paid on'), h('th', { class: 'num' }, 'Per share'), h('th', null, 'Type'), h('th', null, 'In the 12 months'))),
        h('tbody', null, (d.history || []).map((p) => h('tr', null, h('td', null, p.date), h('td', { class: 'num' }, f(p.amount)), h('td', null, p.special ? 'One-off' : 'Regular'), h('td', null, inYear.has(p.date) ? 'Yes' : 'No'))))),
      h('p', { class: 'muted small' }, 'Amounts are per share as reported by Yahoo Finance, on the ex-dividend date, adjusted for splits. A past dividend can be cut, and the yield moves with the share price.'));
  }

  /* The peer ratio table: this stock, its largest peers in the same sector, and the median of every stock of that sector in the list. The figures are the
     ones the alert rules use (Rules.fields), so the table and a rule never disagree. Banks and lenders show "n/a" for debt, EBITDA and ROCE, which do not
     mean the same for them, and are left out of those medians. A median needs at least three figures. */
  const PEER_COLUMNS = [['Mkt cap, Rs cr', 'cap_cr', (v) => Math.round(v).toLocaleString('en-IN')], ['P/E', 'pe', (v) => v.toFixed(1)], ['P/B', 'pb', (v) => v.toFixed(1)],
    ['ROE', 'roe', (v) => `${v.toFixed(0)}%`], ['ROCE*', 'roce', (v) => `${v.toFixed(0)}%`], ['EV/EBITDA', 'ev_ebitda', (v) => v.toFixed(1)], ['Debt/equity', 'debt_equity', (v) => v.toFixed(2)]];
  function peerFigure(stock, key) {
    const f = FIELD_BY_KEY[key];
    if (f.nf && stock.fin) return { na: 'Does not apply to banks and lenders' };
    const v = f.get(stock, ruleContext());
    return isNum(v) ? { v } : {};
  }
  function median(values) {
    if (values.length < 3) return null;
    const sorted = [...values].sort((x, y) => x - y), mid = sorted.length >> 1;
    return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  }
  function peersBlock(s) {
    if (s.sector === 'Other') return h('p', { class: 'muted small' }, 'The exchange does not publish a sector for this stock, so there is no peer group to compare.');
    const group = S.data.stocks.filter((p) => p.sector === s.sector && p.market === s.market);
    const peers = group.filter((p) => p.symbol !== s.symbol).sort((a, b) => ((b.fundamentals || {}).market_cap || 0) - ((a.fundamentals || {}).market_cap || 0)).slice(0, 7);
    if (!peers.length) return h('p', { class: 'muted small' }, 'No peers in the same sector.');
    const shown = [s, ...peers];
    const columns = PEER_COLUMNS.filter(([, key]) => !shown.every((p) => peerFigure(p, key).na));          // a column that is n/a for every row (debt figures in a bank sector) is left out
    const hidden = PEER_COLUMNS.length - columns.length;
    const cell = (stock, [, key, fmt]) => {
      const r = peerFigure(stock, key);
      if (r.na) return h('td', { class: 'num' }, h('span', { class: 'na', title: r.na }, 'n/a'));
      return h('td', { class: 'num' }, r.v === undefined ? naOr(DASH) : fmt(r.v));
    };
    const row = (p, me) => h('tr', { class: me ? 'me' : '' }, h('td', null, p.name), columns.map((c) => cell(p, c)), h('td', { class: 'hide-sm' }, badge(p.long)));
    const medianRow = h('tr', { class: 'median' }, h('td', null, 'Sector median'), columns.map(([, key, fmt]) => {
      const m = median(group.map((p) => peerFigure(p, key).v).filter(isNum));
      return h('td', { class: 'num' }, m === null ? '–' : fmt(m));
    }), h('td', { class: 'hide-sm' }));
    return h('div', null,
      h('div', { class: 'peerwrap' }, h('table', { class: 'peertable' },
        h('thead', null, h('tr', null, h('th', null, 'Company'), columns.map(([label]) => h('th', { class: 'num' }, label)), h('th', { class: 'hide-sm' }, 'Long-term'))),
        h('tbody', null, row(s, true), peers.map((p) => row(p, false)), medianRow))),
      h('p', { class: 'muted small', style: 'margin:6px 0 0' }, `The largest peers by market value in the same sector, from the list in this app. The median covers all ${group.length} stocks of the sector in the list and needs at least three figures. ${hidden ? 'Debt, EBITDA and ROCE figures are left out because they do not mean the same for banks and lenders. ' : 'A bank or lender shows n/a for debt, EBITDA and ROCE. '}${columns.some(([, k]) => k === 'roce') ? '*ROCE is approximate: operating income over equity plus debt. ' : ''}Facts from reported figures, not a recommendation.`));
  }

  function pressureBlock(s) {
    const parts = [];
    if (s.pressure) {
      parts.push(h('p', null, h('b', null, s.pressure.label), ` over the last 20 days. Money flow ${number(s.pressure.money_flow)} (from -1 selling to +1 buying); ${percent(s.pressure.up_volume_share, 0)} of volume traded on rising days.`));
    } else parts.push(h('p', { class: 'muted' }, 'No volume data to measure pressure.'));
    if (s.delivery) parts.push(h('p', { class: s.delivery.tone }, `NSE delivery: ${s.delivery.latest.toFixed(0)}% of shares were taken for delivery on ${s.delivery.date} (recent average ${s.delivery.average.toFixed(0)}%). ${s.delivery.text}.`));
    if (s.deals) {
      parts.push(h('p', null, `Exchange bulk/block deals on ${s.deals.date}: ${big(s.deals.buy_value, s.currency)} bought, ${big(s.deals.sell_value, s.currency)} sold.`));
      parts.push(h('ul', { class: 'clean small' }, s.deals.deals.map((d) => h('li', null, `${d.side === 'BUY' ? 'Bought' : 'Sold'} ${d.qty.toLocaleString()} at ${d.price} by ${d.client} (${d.kind})`))));
    }
    parts.push(h('p', { class: 'muted small' }, 'This is volume-based evidence of buying and selling. The exchange order book (bid and ask depth) is not published for free, so it is not shown.'));
    return parts;
  }

  function listsBlock(s) {
    const names = Object.keys(S.lists);
    const boxes = names.map((name) => {
      const input = h('input', { type: 'checkbox', checked: S.lists[name].includes(s.symbol), onchange: (e) => {
        const set = new Set(S.lists[name]); e.target.checked ? set.add(s.symbol) : set.delete(s.symbol);
        S.lists[name] = [...set]; store.set('lists', S.lists); updateSignals();
      } });
      return h('label', { class: 'chip' }, input, ' ', name);
    });
    const watch = h('label', { class: 'chip' }, h('input', { type: 'checkbox', checked: S.watch.has(s.symbol), onchange: (e) => {
      e.target.checked ? S.watch.add(s.symbol) : S.watch.delete(s.symbol); saveWatch(); updateSignals();
    } }), ' My watchlist (alerts)');
    return h('div', { class: 'row', style: 'gap:6px' }, watch, boxes, !names.length ? h('span', { class: 'muted small' }, 'Create more lists on the Signals tab with "+ New list".') : null);
  }

  /* ---------- stock page: glance first, then tabs ---------- */
  const DETAIL_TABS = [['overview', 'Overview'], ['technicals', 'Technicals'], ['fundamentals', 'Fundamentals'], ['news', 'News & events'], ['backtest', 'Backtest']];
  const SECTION_TAB = { signals: 'overview', 'price-chart': 'overview', 'recent-alerts-for-this-stock': 'overview',
    'buying-and-selling-pressure': 'technicals', 'position-size': 'technicals', 'levels-and-risk': 'technicals', patterns: 'technicals',
    fundamentals: 'fundamentals', dividends: 'fundamentals', 'peers-in-the-same-sector': 'fundamentals', lists: 'fundamentals',
    news: 'news', 'upcoming-events': 'news', 'latest-headlines': 'news', 'how-have-these-rules-worked-on-this-stock': 'backtest' };

  function activateDetailTab(tab) {
    const dlg = $('#detail');
    for (const b of dlg.querySelectorAll('.dtab')) b.setAttribute('aria-selected', String(b.dataset.tab === tab));
    for (const p of dlg.querySelectorAll('.tabpanel')) p.hidden = p.dataset.tab !== tab;
    S.detailTab = tab;
  }

  const changeChip = (pct) => (isNum(pct) ? h('span', { class: `chg ${pct >= 0 ? 'up' : 'down'}` }, `${pct >= 0 ? '▲' : '▼'} ${signed(pct)}`) : null);

  function verdictCard(title, sig) {
    const pos = isNum(sig.score) ? clamp((sig.score + 100) / 2, 0, 100) : 50;
    return h('button', { type: 'button', class: 'verdict', onclick: () => { activateDetailTab('overview'); const t = document.getElementById('d-signals'); if (t) t.scrollIntoView({ block: 'start', behavior: 'smooth' }); } },
      h('span', { class: 'muted small' }, title), badge(sig),
      isNum(sig.score) ? h('div', { class: 'meter', 'aria-hidden': 'true' }, h('i', { style: `left:${pos}%` })) : null);
  }

  /* One line that answers "which way do the checks lean?": both views, and how many of the fixed checks point up, down or neither. */
  function verdictBlock(s) {
    const checks = [...(s.short.reasons || []), ...(s.long.reasons || [])];
    const up = checks.filter((c) => c.tone === 'pos').length, down = checks.filter((c) => c.tone === 'neg').length, flat = checks.length - up - down;
    const sides = [side(s.short.label), side(s.long.label)];
    const lean = sides[0] === sides[1] ? { buy: 'Both views aligned bullish', sell: 'Both views aligned bearish', hold: 'Both views mixed' }[sides[0]] : 'The two views differ';
    const part = (n, k) => (n ? h('i', { class: k, style: `flex:${n}` }) : null);
    return h('div', { class: 'vblock' },
      h('div', { class: 'verdicts' }, verdictCard('Weeks view', s.short), verdictCard('Months-to-years view', s.long)),
      ['short', 'long'].some((hz) => pastTest(s, hz)) ? h('div', { class: 'small muted', style: 'margin:6px 0' }, ['short', 'long'].map((hz) => (pastTest(s, hz) ? h('p', { style: 'margin:2px 0' }, h('b', null, hz === 'short' ? 'Weeks view. ' : 'Months-to-years view. '), pastTest(s, hz)) : null)), h('p', { style: 'margin:2px 0' }, 'Past results do not predict future ones.')) : null,
      checks.length ? h('div', { class: 'vsum' },
        h('div', { class: 'small' }, h('b', null, lean), h('span', { class: 'muted' }, ` \u00B7 ${up} of ${checks.length} checks point up, ${down} down, ${flat} neutral`)),
        h('div', { class: 'stackbar', role: 'img', 'aria-label': `${up} checks point up, ${down} point down, ${flat} neutral` }, part(up, 'u'), part(flat, 'n'), part(down, 'd'))) : null);
  }

  /* Evidence beside a reading: what the same fixed rule did on this stock in the past test, and across the whole list. Shown so a reading is never taken for a promise. */
  const pastTest = (s, horizon) => {
    const e = (s.evidence || {})[horizon];
    if (!e) return null;
    return `Past test on this stock (${e.years} years, after costs and with dividends): the rule returned ${signed(e.rule * 100, 0)} against ${signed(e.hold * 100, 0)} for simply holding, so it ${e.beat ? 'beat' : 'lagged'} holding${e.few_trades ? ' (few trades, so little to go on)' : ''}.`;
  };
  const lagMark = (s) => {
    const lagged = hzList(S.filters.horizon).filter((hz) => { const e = (s.evidence || {})[hz]; return e && !e.beat; });
    return lagged.length ? h('span', { class: 'lag', title: lagged.map((hz) => pastTest(s, hz)).join(' ') + ' Past results do not predict future ones.' }, ' ▽') : null;
  };
  const FLAG_TEXT = { thin: ['Thinly traded', 'Small daily turnover: a few trades move the price, so indicators on this stock say little.'], short_history: ['Under a year of prices', 'Long-term checks need about a year of prices, so the months-to-years reading rests on less.'] };
  const flagTags = (s) => (s.flags || []).filter((f) => FLAG_TEXT[f]).map((f) => h('span', { class: 'tag warn', title: FLAG_TEXT[f][1] }, FLAG_TEXT[f][0]));

  function evidenceStrip() {
    const ev = (S.data && S.data.evidence) || {};
    const lines = [];
    for (const [market, name] of [['IN', 'NSE']]) {
      for (const [hz, label] of [['short', 'weeks view'], ['long', 'months-to-years view']]) {
        const x = (ev[market] || {})[hz];
        if (x) lines.push([`${name}, ${label}`, `${x.beat} of ${x.n} stocks (${x.beat_pct}%) beat buy-and-hold; median return ${signed(x.median_rule * 100, 0)} for the rule against ${signed(x.median_hold * 100, 0)} for holding, over about ${x.median_years} years`]);
      }
    }
    const tr = (S.data && S.data.track_record) || {};
    const o = tr.overall || {};
    const live = o.n ? (o.reliable ? `${o.n} resolved calls; ${o.target_pct}% reached their target before their stop` : `${o.n} resolved calls so far, too few to judge (at least ${tr.min_sample || 30} are needed)`) : 'no resolved calls yet under the current rules';
    const best = ev.IN && ev.IN.short ? ev.IN.short : null;
    return h('details', { class: 'card evidence' },
      h('summary', null, h('b', null, 'How much weight can a reading carry? '),
        best ? `In the past test the weeks-view rule beat buy-and-hold on ${best.beat_pct}% of NSE stocks. ` : '', h('span', { class: 'muted' }, 'Tap for the evidence')),
      h('p', { class: 'small', style: 'margin:8px 0 4px' }, 'A reading says how price and volume indicators line up today. It is not a recommendation and not a forecast. These are the results of the same fixed rules in a past test (next-day prices, assumed costs, dividends included):'),
      h('ul', { class: 'clean small' }, lines.map(([k, v]) => h('li', null, h('b', null, k + ': '), v)),
        h('li', null, h('b', null, 'Live record: '), live + '. ', h('a', { href: '#', onclick: (e) => { e.preventDefault(); S.tab = 'track'; render(); } }, 'See the track record'))),
      h('p', { class: 'muted small', style: 'margin:4px 0 0' }, 'The test uses today\'s stock list, so it is NOT free of survivorship bias (companies that failed or were removed are missing), and past results do not predict future ones. ▽ in the table marks a stock where the rule lagged simply holding it. Prices are delayed up to 15 minutes and come from Yahoo Finance; ratios are as Yahoo reports them.'));
  }

  /* Small data-check tag for the top of the page; the full sentence is at the bottom of the Overview tab. */
  function qualityTag(s) {
    const q = s.quality;
    if (!q) return h('span', { class: 'tag', title: 'No second price source covers this stock' }, 'Price not cross-checked');
    const [cls, text] = q.status === 'match' ? ['buy', 'Price cross-checked'] : q.status === 'minor' ? ['', 'Small price difference'] : ['warn', 'Prices disagree'];
    return h('span', { class: `tag ${cls}`, title: `${q.max_diff_pct}% largest difference against ${q.source}` }, text);
  }

  /* A figure that is not available is shown as "n/a" with the reason, never as zero. */
  const naOr = (v) => (v === DASH || v === '–' ? h('span', { class: 'na', title: 'Not available from the data source for this stock right now' }, 'n/a') : v);

  function statsGrid(s) {
    const f = s.fundamentals || {};
    const items = [['Market cap', big(f.market_cap, s.currency)], ['P/E', number(f.pe, 1)], ['Dividend yield', percent(s.dividend_yield, 2)],
      ['ROE', percent(f.roe, 0)], ['Beta', s.risk ? number(s.risk.beta) : DASH], ['Volatility / yr', s.risk ? percent(s.risk.annual_vol, 0) : DASH]];
    return h('div', { class: 'stats' }, items.map(([k, v]) => h('div', null, h('span', { class: 'muted small' }, k), h('b', null, naOr(v)))));
  }

  function glanceChips(s) {
    const chips = [];
    const next = ((S.data.events || {}).items || []).find((e) => e.symbol === s.symbol && daysUntil(e.until || e.date) >= 0);
    if (next) chips.push(h('button', { type: 'button', class: 'chip', onclick: () => activateDetailTab('news') }, `Next: ${EVENT_LABELS[next.type] || next.type} ${inDays(Math.max(0, daysUntil(next.date)))}`));
    if (s.news.fresh.length) chips.push(h('button', { type: 'button', class: 'chip', onclick: () => activateDetailTab('news') }, `${s.news.fresh.length} new headline${s.news.fresh.length === 1 ? '' : 's'}`));
    if (s.dividend && s.dividend.overdue) chips.push(h('span', { class: 'tag warn' }, 'Dividend overdue'));
    if (s.new) chips.push(h('span', { class: 'tag warn' }, 'New listing: few signals'));
    if (s.stale) chips.push(h('span', { class: 'tag warn' }, 'Price looks stale'));
    if (s.provisional) chips.push(h('span', { class: 'tag warn', title: "Today's candle is unfinished. Readings use the last completed day." }, 'Market open: provisional'));
    return chips.length ? h('div', { class: 'chips-row' }, chips) : null;
  }

  /* One panel of the page top. On wide screens the panels sit two by two with a heading, and the two panels of a row are the same height; on a phone they
     stack with no frame. A panel whose parts are all empty is not drawn. */
  function heroCard(cls, title, ...parts) {
    const kids = parts.filter(Boolean);
    return kids.length ? h('section', { class: `hcard ${cls}`, 'aria-label': title }, h('h3', { class: 'hhead' }, title), ...kids) : null;
  }
  const quarterDay = (iso) => new Date(Date.parse(iso + 'T00:00:00Z')).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });

  function detailView(s) {
    const bt = s.backtest || {};
    const r = s.risk;
    const hero = h('div', { class: 'hero' },
      h('div', { class: 'herotags chips-row' }, h('span', { class: 'tag' }, 'India'), s.exchange ? h('span', { class: 'tag' }, s.exchange) : null, s.sector ? h('span', { class: 'tag' }, s.sector) : null,
        qualityTag(s), flagTags(s)),
      heroCard('hverdict', 'Reading and key figures', verdictBlock(s), statsGrid(s)),
      heroCard('hprice', 'Where the price sits', rangesBlock(s), priceMap(s)),
      heroCard('hresults', 'Results at a glance', insightCards(s)),
      glanceChips(s));

    const panels = {
      overview: [
        h('p', { class: 'advisory wide' }, h('strong', null, 'Advisory: '), 'Not investment advice. Readings and levels come from fixed rules on past prices; the publisher is not a SEBI-registered adviser. ', h('a', { href: 'advisory.html', target: '_blank', rel: 'noopener' }, 'Full disclaimer')),
        alertsForStock(s),
        h('div', { class: 'grid wide', id: 'd-signals' }, h('section', { class: 'card' }, signalCard('Short-term view (weeks)', s.short)), h('section', { class: 'card' }, signalCard('Long-term view (months to years)', s.long))),
        dataNote(s),
        h('div', { class: 'wide' }, liveLine(s), qualityLine(s)),
        newsLine(s),
        outlookCard(s),
        provenanceCard(s)],
      technicals: [
        section('Buying and selling pressure', ...pressureBlock(s)),
        positionCalculator(s),
        section('Levels and risk', h('p', { class: 'small muted' }, 'The resistance, support and risk levels are listed at the top of the page. They come from fixed rules on past prices and are references, not promises or advice. Below are the volatility figures.'), kv([
          ['Yearly volatility', r ? percent(r.annual_vol, 0) : '–'], ['1-day loss (95% VaR)', r ? percent(r.var95) : '–'],
          ['Bad-day average loss', r ? percent(r.expected_shortfall95) : '–'], ['Worst fall (1 year)', r ? percent(r.max_drawdown, 0) : '–'], ['Beta', r ? number(r.beta) : '–']])),
        section('Patterns', (s.patterns || []).length ? (s.patterns).map((p) => h('div', { title: p.note, style: 'margin-bottom:6px' }, h('span', { class: `tag ${p.bias === 'bearish' ? 'warn' : ''}` }, `${p.name} (${p.bias})`), h('span', { class: 'muted small' }, p.note))) : h('p', { class: 'muted small' }, 'No notable pattern on the latest candles.'))],
      fundamentals: [
        wide(section('Fundamental quality and valuation', qualityBlock(s))),
        wide(section('Quarterly results and financial statements', statementsBlock(s))),
        wide(section('Fundamentals', fundamentalsBlock(s))),
        wide(section('Dividends', dividendBlock(s))),
        wide(section('Peers in the same sector', peersBlock(s))),
        section('Lists', listsBlock(s))],
      news: [
        newsIntelCard(s),
        s.news.fresh.length ? h('section', { class: 'card wide', id: 'd-latest-headlines' }, h('h3', null, 'Latest headlines'), newsList(s.news.fresh)) : null,
        wide(section('Upcoming events', stockEvents(s))),
        section('News', s.news.error && !s.news.items.length
          ? h('p', { class: 'muted small' }, 'Headlines are not looked up for this stock on every run. When one is published it appears in the alerts, and in Telegram if the stock is covered there.')
          : newsList(s.news.items))],
      backtest: [
        wide(section('How have these rules worked on this stock?', h('div', { class: 'grid' }, backtestBlock(bt.short, 'Short-term rule'), backtestBlock(bt.long, 'Long-term rule')),
          h('p', { class: 'muted small' }, 'Fixed rules tested on up to 5 years of this stock, trading at the next open with assumed costs. Past results do not guarantee future results.'))),
        backtestMethod(s)],
    };
    return h('div', { class: 'detail' },
      h('div', { class: 'dbar' },
        h('div', { class: 'dname' }, h('b', null, s.name), ' ', h('span', { class: 'muted small' }, s.symbol)),
        h('div', { class: 'dpx' }, h('span', { class: 'px' }, money(s.price, s.currency)), changeChip(s.change_pct)),
        h('button', { type: 'button', class: 'dclose', 'aria-label': 'Close', onclick: closeDetail }, '✕')),
      hero,
      h('div', { class: 'dtabs', role: 'tablist', 'aria-label': 'Sections' }, DETAIL_TABS.map(([id, label]) => h('button', {
        type: 'button', class: 'dtab', role: 'tab', 'data-tab': id, 'aria-selected': 'false',
        onclick: () => { activateDetailTab(id); const d = $('#detail'); const bar = d.querySelector('.dtabs'); if (bar && d.scrollTop > bar.offsetTop) d.scrollTo({ top: bar.offsetTop - 48 }); } }, label))),
      DETAIL_TABS.map(([id]) => h('div', { class: 'dbody tabpanel', 'data-tab': id, role: 'tabpanel', hidden: true }, panels[id])));
  }

  /* ---------- suggestions tab ---------- */
  function suggestions() {
    const p = S.profile;
    const maxVol = { low: 0.30, medium: 0.45, high: 9 }[p.risk];
    const picks = [];
    for (const s of S.data.stocks) {
      if (p.market !== 'ALL' && s.market !== p.market) continue;
      if (s.stale || s.new || s.bars < 260 || !isNum(s.short.score) || !isNum(s.long.score)) continue;
      const vol = s.risk && s.risk.annual_vol;
      if (!isNum(vol) || vol > maxVol) continue;
      const blend = p.horizon === 'short' ? 0.7 * s.short.score + 0.3 * s.long.score : p.horizon === 'both' ? 0.5 * s.short.score + 0.5 * s.long.score : 0.3 * s.short.score + 0.7 * s.long.score;
      if (blend < 15) continue;
      const f = s.fundamentals || {};
      const quality = IPO.qualityFromFundamentals(f, null);
      const q = isNum(quality.score) ? quality.score / 100 : null;       // null = fundamentals unavailable: left out, not scored as zero
      // Cautious yield: the lower of what was paid and what the recurring payments imply. Overdue payers count as zero.
      const div = s.dividend;
      const cautious = div && isNum(div.forward_yield) ? Math.min(s.dividend_yield || 0, div.forward_yield) : (s.dividend_yield || 0);
      const dividend = div && div.overdue ? 0 : Math.min(cautious / 0.06, 1);
      const growth = isNum(f.revenue_growth) ? clamp(f.revenue_growth / 0.3, -1, 1) : null;
      const momentumRaw = (s.indicators || {}).momentum126;
      const momentum = isNum(momentumRaw) ? clamp(momentumRaw / 0.3, -1, 1) : null;
      const calm = clamp(1 - vol / 0.5, 0, 1);
      // A missing figure is left out and the weights of the others are scaled up, so unavailable data neither helps nor hurts a stock.
      const mix = (parts) => { const have = parts.filter(([, x]) => x !== null); return have.reduce((a, [w, x]) => a + w * x, 0) / have.reduce((a, [w]) => a + w, 0); };
      const income = mix([[0.3, dividend], [0.3, blend / 100], [0.2, calm], [0.2, q]]);
      const growing = mix([[0.3, blend / 100], [0.25, momentum], [0.2, growth], [0.25, q]]);
      const score = p.goal === 'income' ? income : p.goal === 'growth' ? growing : (income + growing) / 2;
      picks.push({ s, score, blend, vol, quality, dividend: div && div.overdue ? 0 : cautious, growthRaw: f.revenue_growth });
    }
    return picks.sort((a, b) => b.score - a.score).slice(0, 10);
  }

  function suggestionCard(pick, rank) {
    const { s } = pick;
    const why = [S.profile.horizon === 'both' ? `Weeks view: ${labelText(s.short.label)}; months-to-years view: ${labelText(s.long.label)}` : `${S.profile.horizon === 'short' ? 'Short' : 'Long'}-term reading: ${labelText(s[S.profile.horizon].label)}`];
    if (pick.dividend >= 0.02) why.push(`Dividend yield ${percent(pick.dividend, 1)}${pick.s.dividend && pick.s.dividend.payments_per_year ? ' (' + pick.s.dividend.frequency.toLowerCase() + ')' : ''}`);
    if (pick.vol < 0.25) why.push(`Low volatility (${percent(pick.vol, 0)})`);
    if (isNum(pick.growthRaw) && pick.growthRaw > 0.1) why.push(`Revenue growth ${percent(pick.growthRaw, 0)}`);
    if (pick.quality.score !== null && pick.quality.score >= 30) why.push('Healthy fundamentals');
    if (!isNum(pick.quality.score)) why.push('Fundamentals unavailable, so they were left out of the ranking');
    if (s.pressure && s.pressure.label.startsWith('Buying')) why.push('Buying pressure');
    if (s.lists.includes('Strong delivery buying')) why.push('Strong delivery buying');
    const ni = s.news_intel;
    const risks = [`Moves about ${percent(pick.vol, 0)} a year`];
    if (s.stop) risks.push(`volatility risk level ${signed(s.stop.pct, 1)} below the price`);
    const shortTest = (s.backtest || {}).short;
    if (shortTest && !shortTest.beats_buy_hold_oos) risks.push('the short-term rule has lagged buy-and-hold recently');
    const card = h('div', { class: 'card', tabindex: '0', style: 'cursor:pointer' },
      h('div', { class: 'row', style: 'justify-content:space-between;align-items:center' },
        h('div', null, h('b', null, `${rank}. ${s.name}`), h('span', { class: 'muted small' }, ` ${s.symbol}`)), badges(s, S.profile.horizon)),
      h('div', null, why.map((w) => h('span', { class: 'tag' }, w))),
      h('p', { class: 'small muted', style: 'margin:6px 0 0' }, 'Main risks: ' + risks.join('; ') + '.'));
    card.addEventListener('click', () => openDetail(s.symbol, card));
    card.addEventListener('keydown', (e) => { if (e.key === 'Enter') openDetail(s.symbol, card); });
    return card;
  }

  function viewSuggest() {
    const p = S.profile;
    const results = h('div');
    const draw = () => {
      store.set('profile', S.profile);
      const picks = suggestions();
      results.replaceChildren(...(picks.length ? picks.map((pick, i) => suggestionCard(pick, i + 1))
        : [h('div', { class: 'empty' }, 'No stock passes your filters right now. Try a higher risk level or both markets. The app skips stocks with a weak signal or too little history.')]));
    };
    const form = h('div', { class: 'card' }, h('div', { class: 'row' },
      select('My goal', p.goal, [['income', 'Regular income (dividends)'], ['growth', 'Growth'], ['balanced', 'Balanced']], (v) => { p.goal = v; draw(); }),
      select('Time horizon', p.horizon, [['short', 'Short (weeks)'], ['long', 'Long (months to years)'], ['both', 'Both']], (v) => { p.horizon = v; draw(); }),
      select('Risk I can accept', p.risk, [['low', 'Low (steady stocks)'], ['medium', 'Medium'], ['high', 'High']], (v) => { p.risk = v; draw(); }),
      select('Market', p.market, [['ALL', 'Both'], ['IN', 'India']], (v) => { p.market = v; draw(); })),
      h('p', { class: 'muted small', style: 'margin-bottom:0' }, 'A ranked screen using your answers, signals, fundamentals and risk. It is not personal advice. Check the stock page and your own situation before acting.'));
    queueMicrotask(draw);
    return h('div', null, h('h2', null, 'Stock screens'), form, results);
  }

  /* ---------- IPO tab ---------- */
  function ipoChecker() {
    const sectors = [...new Set(S.data.stocks.map((s) => s.sector))].filter((n) => n !== 'Other' && n !== 'New listings').sort();
    const fields = {};
    const input = (key, label, hint, extra) => {
      fields[key] = h('input', Object.assign({ type: 'number', step: 'any', id: 'ipo-' + key, 'aria-label': label, 'aria-describedby': 'ipo-' + key + '-hint' }, extra || {}));
      return h('label', { class: 'field' }, label, fields[key], h('span', { id: 'ipo-' + key + '-hint', class: 'small' }, hint));
    };
    const result = h('div', { id: 'ipoResult', 'aria-live': 'polite' });
    const dateField = (key, label) => {
      fields[key] = h('input', { type: 'date', id: 'ipo-' + key, 'aria-label': label });
      return h('label', { class: 'field' }, label, fields[key]);
    };
    const sector = h('select', { 'aria-label': 'Sector for peer P/E' }, h('option', { value: '' }, 'Pick a sector'), sectors.map((n) => h('option', { value: n }, n)));
    const marketSel = h('select', { 'aria-label': 'Market for peer P/E' }, h('option', { value: 'IN' }, 'India'));
    const fillPeer = () => {
      const pes = S.data.stocks.filter((s) => s.sector === sector.value && s.market === marketSel.value).map((s) => (s.fundamentals || {}).pe);
      const m = IPO.median(pes);
      if (m === null) { toast('No peer P/E data for that sector'); return; }
      fields.peerPe.value = m.toFixed(1);
    };
    const read = (key) => { const v = parseFloat(fields[key].value); return Number.isFinite(v) ? v : null; };
    const run = (e) => {
      e.preventDefault();
      const draft = { name: S.ipoName, open: fields.open.value, close: fields.close.value, allotment: fields.allotment.value, listing: fields.listing.value,
        priceHigh: read('priceHigh'), lot: read('lot'), gmp: read('gmp') };
      const gmpPct = draft.gmp !== null && draft.priceHigh > 0 ? (draft.gmp / draft.priceHigh) * 100 : null;
      const input = { revenueGrowth: read('revenueGrowth'), profitMargin: read('profitMargin'), debtToEquity: read('debtToEquity'), roe: read('roe'),
        pe: read('pe'), peerPe: read('peerPe'), ofsShare: read('ofsShare'), qibSubscription: read('qibSubscription'), gmp: gmpPct };
      const v = IPO.ipoVerdict(input);
      const cls = v.label === 'Subscribe' ? 'buy' : v.label === 'Avoid' ? 'sell' : '';
      const names = { profitability: 'profit margin', growth: 'revenue growth', leverage: 'debt', returns: 'return on equity', valuation: 'valuation (P/E and peer P/E)', promoterExit: 'offer-for-sale share', demand: 'QIB subscription', grey: 'grey-market premium' };
      result.replaceChildren(h('div', { class: `card result ${cls}` },
        h('h3', null, `${S.ipoName ? S.ipoName + ': ' : ''}${labelText(v.label)}`, isNum(v.score) ? ` (score ${v.score > 0 ? '+' : ''}${v.score})` : ''),
        isNum(v.score) ? h('p', null, 'Listing-day and short-term view: ', h('b', null, labelText(v.label)), '. Long-term holding view: ', badge({ label: v.longTerm.label, score: v.longTerm.score }), '.') : h('p', null, 'Fill in at least profit margin, revenue growth, debt or return on equity, plus the valuation fields, to get a verdict.'),
        reasonsList(v.reasons),
        v.missing.length ? h('p', { class: 'muted small' }, 'Not used (no input): ' + v.missing.map((k) => names[k]).join(', ') + '.') : null,
        h('p', { class: 'muted small' }, 'Take the figures from the red herring prospectus (RHP) or the issue note. Peer P/E is the median of listed companies in the same sector. Subscribe means the numbers look healthy, not that the listing price will rise.')));
      result.append(ipoDetails(draft, v));
    };
    const name = h('input', { type: 'text', maxlength: '60', placeholder: 'Optional', 'aria-label': 'IPO name', oninput: (e) => { S.ipoName = e.target.value.trim(); } });
    name.value = S.ipoName;
    return h('form', { class: 'card', onsubmit: run },
      h('h2', null, 'IPO checker'),
      h('p', { class: 'muted small' }, 'Free sources do not publish an unlisted company\'s financials, so enter the figures from the IPO documents. The same rules score every IPO in the same way.'),
      h('div', { class: 'row', style: 'align-items:start' }, h('label', { class: 'field' }, 'IPO name', name),
        input('revenueGrowth', 'Revenue growth (%)', 'Last year over the year before'), input('profitMargin', 'Profit margin (%)', 'Profit after tax / revenue; negative if loss'),
        input('debtToEquity', 'Debt / equity (x)', 'For example 0.4'), input('roe', 'Return on equity (%)', 'Profit / shareholders\' funds'),
        input('pe', 'P/E at upper price band', 'Price / earnings per share'), input('peerPe', 'Peer P/E', 'Use the sector median below'),
        input('ofsShare', 'Offer for sale (% of issue)', 'Existing holders selling'), input('qibSubscription', 'QIB subscription (x)', 'Fill after the book closes')),
      h('h3', { style: 'margin-top:14px' }, 'Dates, price and grey-market premium'),
      h('p', { class: 'muted small' }, 'Optional. Take the dates, price band and lot size from the issue notice. Allotment and listing dates are estimated if left blank.'),
      h('div', { class: 'row', style: 'align-items:start' },
        dateField('open', 'Opens'), dateField('close', 'Closes'), dateField('allotment', 'Allotment (optional)'), dateField('listing', 'Listing (optional)'),
        input('priceHigh', 'Upper price band', 'Price per share'), input('lot', 'Lot size (shares)', 'Minimum shares per application'),
        input('gmp', 'Grey-market premium per share', 'Unofficial and can be wrong; negative if a discount')),
      h('div', { class: 'row', style: 'margin-top:10px' }, h('label', { class: 'field' }, 'Sector', sector), h('label', { class: 'field' }, 'Market', marketSel),
        h('button', { type: 'button', class: 'btn ghost', onclick: fillPeer }, 'Use sector median P/E'), h('button', { type: 'submit', class: 'btn' }, 'Check this IPO')),
      result);
  }

  const todayIso = () => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  };
  const gainClass = (v) => (isNum(v) ? (v > 0 ? 'pos' : v < 0 ? 'neg' : '') : '');
  const IPO_CURRENCY = '₹';
  const rupees = (v) => (isNum(v) ? `${v < 0 ? '-' : ''}${IPO_CURRENCY}${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}` : '–');
  const loadTracker = () => { const list = store.get('ipoTracker', []); return Array.isArray(list) ? list : []; };

  function ipoDetails(entry, verdict) {
    const t = IPO.timeline(entry, todayIso());
    const est = IPO.estimate(entry);
    const saveError = h('span', { class: 'small neg', role: 'alert' });
    const noDates = !entry.open && !entry.close;
    const timeline = t.valid
      ? h('div', { style: 'overflow-x:auto' }, h('p', null, h('span', { class: 'tag' }, t.status)),
        h('table', null, h('thead', null, h('tr', null, ['Opens', 'Closes', 'Allotment', 'Listing'].map((x) => h('th', null, x)))),
          h('tbody', null, h('tr', null, h('td', null, t.open), h('td', null, t.close),
            h('td', null, t.allotment + (t.allotmentEstimated ? ' (est.)' : '')), h('td', null, t.listing + (t.listingEstimated ? ' (est.)' : ''))))))
      : h('p', { class: 'muted small' }, noDates ? 'Add the open and close dates to see the allotment and listing dates.' : `Cannot work out the timeline: ${t.error}`);
    const profit = isNum(est.gainPerShare)
      ? kv([['Upper price band', rupees(entry.priceHigh)], ['Minimum application', isNum(est.applyAmount) ? `${rupees(est.applyAmount)} (${entry.lot} shares)` : 'Enter the lot size'],
        ['Grey-market premium', `${rupees(est.gainPerShare)} per share (${signed(est.gainPct, 1)})`], ['Estimated listing price', rupees(est.listingPrice)],
        ['Estimated profit or loss per share', rupees(est.gainPerShare)], ['Estimated profit or loss per lot', isNum(est.gainPerLot) ? rupees(est.gainPerLot) : 'Enter the lot size']])
      : h('p', { class: 'muted small' }, 'Enter the upper price band and the grey-market premium to estimate the listing price and profit or loss.');
    if (isNum(est.gainPerLot)) profit.querySelectorAll('div b')[5].className = gainClass(est.gainPerLot);
    if (isNum(est.gainPerShare)) profit.querySelectorAll('div b')[4].className = gainClass(est.gainPerShare);
    const save = h('button', { type: 'button', class: 'btn ghost', onclick: () => {
      if (!entry.name) { saveError.textContent = 'Enter the IPO name above to save it.'; return; }
      if (!t.valid) { saveError.textContent = 'Enter valid open and close dates to save it.'; return; }
      saveError.textContent = '';
      const list = loadTracker();
      list.push(Object.assign({ id: Date.now(), label: verdict.label, score: verdict.score }, entry));
      store.set('ipoTracker', list);
      drawTracker();
      toast('Saved to My IPO tracker');
    } }, 'Save to my IPO tracker');
    return h('div', { class: 'card' }, h('h3', null, 'Dates and estimated profit or loss'), timeline, profit,
      h('p', { class: 'muted small' }, 'Estimated listing price is the upper price band plus the grey-market premium. The premium is unofficial, changes daily and can be wrong. Profit only arises if shares are allotted, and it ignores brokerage, taxes and moves on listing day. Estimated allotment and listing dates follow the usual schedule (2 and 3 working days after close, holidays ignored): confirm them in the issue notice.'),
      h('div', { class: 'row' }, save, saveError));
  }

  function drawTracker() {
    const box = $('#ipoTracker');
    if (!box) return;
    const list = loadTracker();
    if (!list.length) { box.replaceChildren(h('div', { class: 'empty card' }, 'No IPOs saved yet. Check an IPO above and save it here to follow its dates and estimated profit.')); return; }
    const today = todayIso();
    const save = (next) => { store.set('ipoTracker', next); drawTracker(); };
    const rows = list.map((item) => ({ item, t: IPO.timeline(item, today), est: IPO.estimate(item) }))
      .sort((a, b) => String(a.item.close).localeCompare(String(b.item.close)));
    box.replaceChildren(h('div', { class: 'card', style: 'padding:0;overflow-x:auto' }, h('table', null,
      h('thead', null, h('tr', null, ['IPO', 'Status', 'Opens', 'Closes', 'Allotment', 'Listing', 'Price band', 'Lot', 'Premium', 'Est. listing price', 'Est. profit or loss per lot', ''].map((x, i) => h('th', { class: i >= 6 && i <= 10 ? 'num' : '' }, x)))),
      h('tbody', null, rows.map(({ item, t, est }) => {
        const gmp = h('input', { type: 'number', step: 'any', value: isNum(item.gmp) ? item.gmp : '', style: 'width:84px', 'aria-label': `Grey-market premium for ${item.name}`,
          onchange: (e) => { const v = parseFloat(e.target.value); save(loadTracker().map((x) => (x.id === item.id ? Object.assign({}, x, { gmp: Number.isFinite(v) ? v : null }) : x))); } });
        return h('tr', null,
          h('td', { class: 'name' }, h('b', null, item.name), item.label ? h('span', null, `Check: ${labelText(item.label)}${isNum(item.score) ? ' (' + (item.score > 0 ? '+' : '') + item.score + ')' : ''}`) : null),
          h('td', null, t.valid ? h('span', { class: 'tag' }, t.status) : h('span', { class: 'tag warn' }, 'Check dates')),
          h('td', null, item.open || '–'), h('td', null, item.close || '–'),
          h('td', null, t.valid ? t.allotment + (t.allotmentEstimated ? ' (est.)' : '') : '–'), h('td', null, t.valid ? t.listing + (t.listingEstimated ? ' (est.)' : '') : '–'),
          h('td', { class: 'num' }, rupees(item.priceHigh)), h('td', { class: 'num' }, isNum(item.lot) ? item.lot : '–'),
          h('td', { class: 'num' }, gmp), h('td', { class: 'num' }, rupees(est.listingPrice)),
          h('td', { class: `num ${gainClass(est.gainPerLot)}` }, isNum(est.gainPerLot) ? `${rupees(est.gainPerLot)} (${signed(est.gainPct, 1)})` : '–'),
          h('td', null, h('button', { type: 'button', class: 'chip', 'aria-label': `Remove ${item.name} from the tracker`, onclick: () => { if (confirm(`Remove ${item.name} from your tracker?`)) save(loadTracker().filter((x) => x.id !== item.id)); } }, 'Remove')));
      })))),
      h('p', { class: 'muted small' }, 'Update the grey-market premium here as it changes. Estimates only: the premium is unofficial, and profit applies only if shares are allotted.'));
  }

  const PHASE_ORDER = { open: 0, upcoming: 1, closed: 2, listed: 3 };

  /* The source's premium, plus a cross-check from recent news headlines when one quotes a figure. */
  function gmpCell(row, listed) {
    if (listed) return '–';
    const parts = [isNum(row.gmp) ? `${rupees(row.gmp)} (${signed(row.gmp_pct, 1)})` : '–'];
    const n = row.news_gmp;
    if (n && (isNum(n.rupees) || isNum(n.percent))) {
      const verdict = n.agrees === true ? 'news agrees' : n.agrees === false ? 'news differs' : 'news only';
      const label = `${verdict}: ${isNum(n.rupees) ? rupees(n.rupees) : signed(n.percent, 1)}`;
      parts.push(h('div', { class: `small ${n.agrees === false ? 'neg' : 'muted'}`, title: n.title },
        safeUrl(n.link) ? h('a', { href: n.link, target: '_blank', rel: 'noopener noreferrer' }, label) : label));
    }
    return parts;
  }

  function indiaIpoSection(ipos) {
    const source = ipos.india_source || {};
    const view = (S.ipoView = S.ipoView || { phase: 'active', board: 'ALL' });
    const today = todayIso();
    const rows = (ipos.india || []).map((row) => ({
      row, t: IPO.timeline(row, today),
      est: IPO.estimate({ priceHigh: row.price, lot: row.lot, gmp: row.gmp }),
      demand: IPO.demand({ gmpPct: row.gmp_pct, subscription: row.subscription }),
    })).filter((x) => x.t.valid);
    const box = h('div');
    const conflicts = rows.filter(({ row, t }) => t.phase !== 'listed' && row.news_gmp && row.news_gmp.agrees === false).length;

    const chip = (label, active, onClick) => h('button', { type: 'button', class: 'chip' + (active ? ' on' : ''), 'aria-pressed': active ? 'true' : 'false', onclick: onClick }, label);

    const tableRow = ({ row, t, est, demand }) => {
      const listed = isNum(row.listed_price);
      const actualGainPerShare = listed ? row.listed_price - row.price : null;
      const actualPerLot = listed ? actualGainPerShare * row.lot : null;
      const name = safeUrl(row.link) ? h('a', { href: row.link, target: '_blank', rel: 'noopener noreferrer' }, row.name) : row.name;
      const profitCell = listed
        ? h('td', { class: `num ${gainClass(actualPerLot)}` }, `${rupees(actualPerLot)} (${signed(row.listed_gain_pct, 1)})`, h('div', { class: 'muted small' }, 'actual, at listing'))
        : h('td', { class: `num ${gainClass(est.gainPerLot)}` }, isNum(est.gainPerLot) ? [`${rupees(est.gainPerLot)} (${signed(est.gainPct, 1)})`, h('div', { class: 'muted small' }, 'estimate')] : '–');
      return h('tr', null,
        h('td', { class: 'name' }, h('b', null, name), h('span', null, [row.exchange, row.board === 'SME' ? null : 'Mainboard'].filter(Boolean).join(' '),
          row.board === 'SME' ? h('span', { class: 'tag warn', title: 'SME IPOs are riskier: smaller, less liquid companies and larger minimum investments' }, 'SME') : null,
          row.anchor ? h('span', { class: 'tag', title: 'Anchor investors took part' }, 'Anchor') : null)),
        h('td', null, h('span', { class: 'tag' }, t.status)),
        h('td', null, t.open), h('td', null, t.close), h('td', null, t.allotment), h('td', null, t.listing),
        h('td', { class: 'num' }, rupees(row.price), h('div', { class: 'muted small' }, `${row.lot} sh = ${rupees(est.applyAmount)}`)),
        h('td', { class: 'num' }, gmpCell(row, listed)),
        h('td', { class: 'num' }, listed ? rupees(row.listed_price) : rupees(est.listingPrice), listed ? h('div', { class: 'muted small' }, 'actual') : null),
        profitCell,
        h('td', { class: 'num hide-sm' }, isNum(row.subscription) ? `${row.subscription.toFixed(1)}x` : '–'),
        h('td', { class: 'hide-sm' }, listed ? '–' : h('span', { class: `tag ${demand.score !== null && demand.score <= -20 ? 'warn' : ''}`, title: demand.reasons.map((r) => r.text).join('; ') }, demand.label)));
    };

    const draw = () => {
      const shown = rows
        .filter(({ row, t }) => (view.board === 'ALL' || row.board === view.board)
          && (view.phase === 'all' || (view.phase === 'active' ? t.phase !== 'listed' : t.phase === 'listed')))
        .sort((a, b) => (PHASE_ORDER[a.t.phase] - PHASE_ORDER[b.t.phase]) || a.t.close.localeCompare(b.t.close));
      const controls = h('div', { class: 'row', style: 'gap:6px;margin-bottom:8px' },
        [['active', 'Open and upcoming'], ['listed', 'Recently listed'], ['all', 'All']].map(([k, label]) => chip(label, view.phase === k, () => { view.phase = k; draw(); })),
        h('span', { class: 'muted' }, '|'),
        [['ALL', 'All boards'], ['Mainboard', 'Mainboard'], ['SME', 'SME']].map(([k, label]) => chip(label, view.board === k, () => { view.board = k; draw(); })));
      const table = shown.length ? h('div', { class: 'card', style: 'padding:0;overflow-x:auto' }, h('table', null,
        h('thead', null, h('tr', null, ['IPO', 'Status', 'Opens', 'Closes', 'Allotment', 'Listing', 'Price band (upper) and lot', 'GMP per share', 'Est. listing price', 'Est. profit or loss per lot', 'Subscribed', 'Demand']
          .map((x, i) => h('th', { class: (i >= 6 && i <= 10 ? 'num' : '') + (i >= 10 ? ' hide-sm' : '') }, x)))),
        h('tbody', null, shown.map(tableRow))))
        : h('div', { class: 'empty card' }, rows.length ? 'No IPOs match these filters.' : 'Indian IPO data could not be loaded this time.');
      box.replaceChildren(controls, table);
    };
    draw();

    const fetched = source.fetched_at ? Math.max(0, Math.round((Date.now() - Date.parse(source.fetched_at)) / 60000)) : null;
    return h('div', null,
      h('h2', null, 'India IPOs, dates and grey-market premium'),
      !ipos.india_ok && rows.length ? h('p', { class: 'tag warn' }, 'The source could not be refreshed. These figures may be out of date.') : null,
      conflicts ? h('p', { class: 'tag warn' }, `${conflicts} IPO${conflicts === 1 ? '' : 's'} below: the source and a recent news headline quote different premiums. Treat those estimates with extra caution.`) : null,
      box,
      h('p', { class: 'muted small' }, 'Source: ', safeUrl(source.url) ? h('a', { href: source.url, target: '_blank', rel: 'noopener noreferrer' }, source.name || 'IPO data site') : 'IPO data site',
        isNum(fetched) ? `, read ${ago(fetched)}` : '', '. Premiums are cross-checked against recent news headlines that quote a figure. Dates and price bands should be confirmed in the offer document and on the NSE or BSE site.'),
      h('details', { class: 'muted small' }, h('summary', null, 'About GMP and these estimates (unofficial, can be wrong)'), 'The grey-market premium (GMP) is an unofficial market rumour, not an exchange price. It can change daily or be wrong. Estimated profit is premium times lot size and applies only if shares are allotted; it ignores brokerage, taxes and moves on listing day. The demand label measures hype from the premium and subscription, not the quality of the business. SME IPOs are riskier, with larger minimum amounts and thin trading.'));
  }

  function viewIpo() {
    const ipos = S.data.ipos || { headlines: [] };
    const fresh = S.data.stocks.filter((s) => s.new).sort((a, b) => String(b.listed).localeCompare(String(a.listed)));
    const freshTable = fresh.length ? h('div', { class: 'card', style: 'padding:0;overflow-x:auto' }, h('table', null,
      h('thead', null, h('tr', null, h('th', null, 'Stock'), h('th', { class: 'num' }, 'Price'), h('th', null, 'Listed'), h('th', null, 'Signal'), h('th', null, 'Fundamentals check'))),
      h('tbody', null, fresh.map((s) => {
        const q = IPO.qualityFromFundamentals(s.fundamentals, null);
        const row = h('tr', { class: 'stock', tabindex: '0' }, h('td', { class: 'name' }, h('b', null, s.name), h('span', null, s.symbol)), h('td', { class: 'num' }, money(s.price, s.currency)),
          h('td', null, s.listed || '–'), h('td', null, badge(s.short)), h('td', null, isNum(q.score) ? badge({ label: q.longTerm.label === 'N/A' ? q.label : q.longTerm.label, score: q.score }) : h('span', { class: 'muted small' }, 'Not enough data yet')));
        row.addEventListener('click', () => openDetail(s.symbol, row));
        row.addEventListener('keydown', (e) => { if (e.key === 'Enter') openDetail(s.symbol, row); });
        return row;
      })))) : h('div', { class: 'empty card' }, 'No new listings found in the tracked window.');
    queueMicrotask(drawTracker);
    return h('div', null,
      indiaIpoSection(ipos),
      h('h2', null, 'Recently listed stocks (added automatically)'), h('p', { class: 'muted small' }, 'New listings found on the NSE list are added on their own. Signals need about 60 trading days of history, and fundamentals appear once the company reports.'), freshTable,
      h('h2', null, 'Check an IPO yourself (optional)'),
      h('p', { class: 'muted small' }, 'Everything above updates by itself. Use this only for an IPO that is not in the table above, or to score a company\'s financials: it is the one place you type figures.'),
      ipoChecker(), h('h3', null, 'My IPO tracker'), h('div', { id: 'ipoTracker' }));
  }

  /* ---------- events ---------- */
  const EVENT_LABELS = { earnings: 'Results', ex_dividend: 'Ex-dividend', dividend_payment: 'Dividend paid', split: 'Split', bonus: 'Bonus', corporate_action: 'Corporate action' };
  const EVENT_SUBLABELS = { earnings: 'Results expected', ex_dividend: 'Ex-dividend date', dividend_payment: 'Dividend payment date', split: 'Stock split', bonus: 'Bonus issue', corporate_action: 'Record or ex-date' };
  const BASIS_TAGS = { yahoo: 'YAHOO', estimate: 'ESTIMATED', news: 'NEWS', nse: 'OFFICIAL', official: 'OFFICIAL' };
  const EVENT_CATEGORIES = [
    { id: 'results', title: 'Results', blurb: 'Quarterly and annual results', types: ['earnings'] },
    { id: 'dividends', title: 'Dividend dates', blurb: 'Ex-dividend and payment dates', types: ['ex_dividend', 'dividend_payment'] },
    { id: 'actions', title: 'Splits, bonus and other actions', blurb: 'Reported by prominent news outlets', types: ['split', 'bonus', 'corporate_action'] },
    { id: 'announced', title: 'Announced in the news', blurb: 'Announced, but no date stated', types: [] },
  ];
  const CARD_LIMIT = 8;
  S.ev = { market: 'ALL', category: 'ALL', mine: false, q: '', all: {} };

  const categoryOf = (type) => (EVENT_CATEGORIES.find((c) => c.types.includes(type)) || EVENT_CATEGORIES[3]).id;
  const todayUtc = () => new Date().toISOString().slice(0, 10);
  const dayMs = (iso) => Date.parse(iso + 'T00:00:00Z');
  const daysUntil = (iso) => Math.round((dayMs(iso) - dayMs(todayUtc())) / 86400000);
  const prettyDate = (iso) => new Date(dayMs(iso)).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' });
  const monthShort = (iso) => new Date(dayMs(iso)).toLocaleDateString('en-GB', { month: 'short', timeZone: 'UTC' });
  const inDays = (n) => (n <= 0 ? 'today' : n === 1 ? 'tomorrow' : `in ${n} days`);
  const dayLabel = (iso) => { const n = daysUntil(iso); return n <= 0 ? `Today · ${prettyDate(iso)}` : n === 1 ? `Tomorrow · ${prettyDate(iso)}` : prettyDate(iso); };

  function eventFigure(e) {
    if (e.type === 'ex_dividend' && isNum(e.announced_amount)) return [money(e.announced_amount, e.currency), h('small', null, 'per share · announced')];
    if (e.type === 'ex_dividend' && isNum(e.amount)) return [h('span', { class: 'muted' }, money(e.amount, e.currency)), h('small', null, 'per share · last paid')];
    if (e.ratio) return [e.ratio, h('small', null, 'ratio')];
    return null;
  }

  function eventDetail(e) {
    const bits = [];
    if (e.type === 'ex_dividend' && isNum(e.amount) && !isNum(e.announced_amount)) bits.push('The announced amount may differ from the last payment');
    if (e.until) bits.push(`Falls between ${prettyDate(e.date)} and ${prettyDate(e.until)}`);
    return [e.detail, ...bits].filter(Boolean).join('. ');
  }

  function evidenceLine(e) {
    const ev = e.evidence;
    if (!ev || !ev.headline) return null;
    const link = safeUrl(ev.link);
    return h('div', { class: 'muted small' }, 'News: ', link ? h('a', { href: link, target: '_blank', rel: 'noopener noreferrer' }, ev.headline) : ev.headline,
      ` (${[ev.source, isNum(ev.age_min) ? ago(ev.age_min) : null].filter(Boolean).join(', ')})`);
  }

  function stockName(e, withStock) {
    return withStock ? [h('b', null, e.name), ' ', h('span', { class: 'muted small' }, e.symbol)] : null;
  }

  function viewStockButton(e, withStock) {
    if (!withStock || !S.data.stocks.some((s) => s.symbol === e.symbol)) return null;
    return h('button', { type: 'button', class: 'chip evopen', onclick: (ev) => openDetail(e.symbol, ev.currentTarget) }, `View ${e.name}`);
  }

  /* One event as a compact, expandable row: date badge, what and who, the key figure, and the sources underneath. */
  /* Whether an official source backs this date: CONFIRMED, CONFLICT (the exchange says another date) or UNVERIFIED. */
  function verifyTag(e) {
    if (e.verification === 'CONFIRMED') return h('span', { class: 'tag buy', title: e.verification_note || '' }, 'Confirmed by NSE');
    if (e.verification === 'CONFLICT') return h('span', { class: 'tag warn', title: e.verification_note || '' }, `NSE says ${prettyDate((e.official || {}).date)}`);
    return h('span', { class: 'tag', title: e.verification_note || '' }, 'Unverified');
  }

  function verifyLine(e) {
    if (!e.verification) return null;
    return h('div', { class: 'small verifyline' }, verifyTag(e), ' ', e.verification_note || '', ' ',
      e.official_url ? h('a', { href: e.official_url, target: '_blank', rel: 'noopener' }, 'Official source') : null,
      e.last_checked ? h('span', { class: 'muted' }, ` \u00B7 last checked ${prettyDate(e.last_checked)}`) : h('span', { class: 'muted' }, ' \u00B7 not checked against an official source'));
  }

  function officialNote() {
    const o = (S.data.events || {}).official;
    if (!o) return null;
    const when = o.fetched_at ? `last read ${o.fetched_at.slice(0, 16).replace('T', ' ')} UTC` : 'not read successfully yet';
    return h('p', { class: `small ${o.ok ? 'muted' : 'warnline'}`, role: o.ok ? null : 'status' },
      o.ok ? `Indian dates are checked against the NSE's own announcement feeds (${when}): ${o.confirmed} confirmed, ${o.conflicts} with a different official date, ${o.unverified} unverified.`
        : `The NSE announcement feed could not be read (${o.error || 'no answer'}), so no date is confirmed; ${when}. `);
  }

  function eventItem(e, withStock) {
    const n = daysUntil(e.date);
    const category = categoryOf(e.type);
    const sub = e.until ? `${EVENT_SUBLABELS[e.type]} · to ${prettyDate(e.until)}` : `${EVENT_SUBLABELS[e.type] || e.type} · ${inDays(n)}`;
    return h('details', { class: `ev cat-${category}` },
      h('summary', null,
        h('div', { class: 'evdate' }, h('b', null, String(new Date(dayMs(e.date)).getUTCDate())), h('span', null, monthShort(e.date))),
        h('div', { class: 'evmain' }, h('div', { class: 'evtitle' }, withStock ? stockName(e, true) : EVENT_LABELS[e.type] || e.type), h('div', { class: 'muted small' }, sub)),
        h('div', { class: 'evfig' }, eventFigure(e))),
      h('div', { class: 'evbody' },
        h('div', null, (e.bases || []).map((b) => [src(BASIS_TAGS[b] || 'YAHOO'), ' ']), e.agree ? src('AGREED') : null,
          e.conflict ? h('span', { class: 'tag warn' }, 'differs from another source') : null),
        h('div', { class: 'muted small' }, eventDetail(e), ' ', h('span', null, `Source: ${e.source}.`)),
        verifyLine(e), evidenceLine(e), viewStockButton(e, withStock)));
  }

  function announcementItem(a, withStock) {
    const fig = isNum(a.amount) ? [money(a.amount, a.currency), h('small', null, 'per share')] : a.ratio ? [a.ratio, h('small', null, 'ratio')] : null;
    return h('details', { class: 'ev cat-announced' },
      h('summary', null,
        h('div', { class: 'evdate' }, h('b', null, '?'), h('span', null, 'no date')),
        h('div', { class: 'evmain' }, h('div', { class: 'evtitle' }, withStock ? stockName(a, true) : a.title), h('div', { class: 'muted small' }, a.title)),
        h('div', { class: 'evfig' }, fig)),
      h('div', { class: 'evbody' }, h('div', null, src('NEWS')), h('div', { class: 'small verifyline' }, h('span', { class: 'tag' }, 'Unverified'), ' No date stated. ', a.official_url ? h('a', { href: a.official_url, target: '_blank', rel: 'noopener' }, 'Official source') : null), evidenceLine(a), viewStockButton(a, withStock)));
  }

  function stockEvents(s) {
    const mine = ((S.data.events || {}).items || []).filter((e) => e.symbol === s.symbol && daysUntil(e.until || e.date) >= 0);
    const notes = ((S.data.events || {}).announcements || []).filter((a) => a.symbol === s.symbol);
    const splits = s.splits || [];
    return [
      mine.length || notes.length ? h('div', { class: 'evlist' }, mine.map((e) => eventItem(e, false)), notes.map((a) => announcementItem(a, false)))
        : h('p', { class: 'muted small' }, 'No upcoming results, dividend or corporate-action dates were found for this stock.'),
      splits.length ? h('p', { class: 'small' }, h('b', null, 'Recent splits: '), splits.map((x) => `${x.ratio} on ${x.date}`).join(', ')) : null,
      h('p', { class: 'muted small', style: 'margin-bottom:0' }, 'Dates come from Yahoo Finance, from headlines of prominent news outlets, or are estimated from past payments, and can change. The exchanges\' own corporate-action lists cannot be read for free, so check the exchange notice before acting on any date.')];
  }

  function estimateNote() {
    const c = (S.data.events || {}).estimate_check;
    const n = (S.data.events || {}).news_check;
    if (!c && !n) return null;
    return h('p', { class: 'muted small' },
      c ? `How good are the estimates? Where Yahoo has a real ex-dividend date (${c.n} stocks), the same method gave a date within ${c.median_abs_days} day${c.median_abs_days === 1 ? '' : 's'} at the median, and ${c.within_7_days_pct}% were within a week. Some were weeks off, so treat "estimated" as a rough guide. ` : null,
      n ? `Do Yahoo and the news agree? For ${n.n} stock${n.n === 1 ? '' : 's'} with both, ${n.agree_pct}% gave the same ex-dividend date (or a date range that contains it).` : null);
  }

  function viewEvents() {
    const data = S.data.events || {};
    const dated = (data.items || []).filter((e) => daysUntil(e.until || e.date) >= 0);
    const notes = data.announcements || [];
    const f = S.ev;
    const root = h('div', null);

    const passes = (e) => (f.market === 'ALL' || e.market === f.market) && (!f.mine || S.watch.has(e.symbol))
      && (!f.q || `${e.name} ${e.symbol}`.toLowerCase().includes(f.q.toLowerCase()));

    function draw() {
      const rows = (cat) => (cat.id === 'announced' ? notes : dated.filter((e) => cat.types.includes(e.type))).filter(passes);
      const counts = Object.fromEntries(EVENT_CATEGORIES.map((c) => [c.id, rows(c).length]));
      const total = EVENT_CATEGORIES.reduce((sum, c) => sum + counts[c.id], 0);

      const chips = h('div', { class: 'catchips', role: 'group', 'aria-label': 'Event categories' },
        [{ id: 'ALL', title: 'All events' }, ...EVENT_CATEGORIES].map((c) => h('button', {
          type: 'button', class: `chip catchip cat-${c.id}`, 'aria-pressed': String(f.category === c.id),
          onclick: () => { f.category = c.id; draw(); } }, c.title, ' ', h('span', { class: 'n' }, String(c.id === 'ALL' ? total : counts[c.id])))));

      const cards = EVENT_CATEGORIES.filter((c) => f.category === 'ALL' || f.category === c.id).map((c) => {
        const list = rows(c);
        if (!list.length) return f.category === c.id ? h('div', { class: 'empty' }, 'Nothing in this category matches the filters.') : null;
        const open = f.all[c.id];
        const shown = open ? list : list.slice(0, CARD_LIMIT);
        const first = list[0];
        const groups = [];
        shown.forEach((e) => {
          const key = c.id === 'announced' ? 'Reported recently' : e.date;
          const last = groups[groups.length - 1];
          if (last && last.key === key) last.items.push(e); else groups.push({ key, items: [e] });
        });
        return h('section', { class: `card evcard cat-${c.id}`, 'aria-label': c.title },
          h('header', { class: 'evhead' }, h('h3', null, c.title), h('span', { class: 'count' }, String(list.length)), h('span', { class: 'muted small' }, c.blurb),
            c.id !== 'announced' && first ? h('div', { class: 'muted small evnext' }, `Next: ${first.name} · ${dayLabel(first.date)}`) : null),
          groups.map((g) => [h('div', { class: 'evgroup' }, c.id === 'announced' ? g.key : dayLabel(g.key)),
            g.items.map((e) => (c.id === 'announced' ? announcementItem(e, true) : eventItem(e, true)))]),
          list.length > CARD_LIMIT ? h('button', { type: 'button', class: 'btn ghost evmore', onclick: () => { f.all[c.id] = !open; draw(); } }, open ? 'Show fewer' : `Show all ${list.length}`) : null);
      });

      const empty = !total ? h('div', { class: 'empty' }, f.mine ? 'None of the stocks on your watchlist has an upcoming event in the data. Turn off "My watchlist only" to see all.' : 'No upcoming events match these filters.') : null;
      const controls = h('div', { class: 'filterbar' }, h('div', { class: 'row' },
        h('label', { class: 'field' }, h('span', null, 'Search'), h('input', { type: 'search', placeholder: 'Name or symbol', value: f.q, 'aria-label': 'Search events',
          oninput: (ev) => { f.q = ev.target.value; clearTimeout(draw.timer); draw.timer = setTimeout(() => { draw(); const box = root.querySelector('input[type=search]'); if (box) { box.focus(); box.setSelectionRange(f.q.length, f.q.length); } }, 250); } })),
        h('label', { class: 'field' }, h('span', null, 'Market'), h('select', { onchange: (ev) => { f.market = ev.target.value; draw(); } },
          [['ALL', 'All markets'], ['IN', 'India']].map(([v, text]) => h('option', { value: v, selected: v === f.market }, text)))),
        h('label', { class: 'field' }, h('span', null, 'My watchlist only'), h('input', { type: 'checkbox', checked: f.mine, onchange: (ev) => { f.mine = ev.target.checked; draw(); } })),
        null));

      root.replaceChildren(...[h('h2', null, 'Upcoming events'), officialNote(), controls, chips, empty, h('div', { class: 'evcards' }, cards), estimateNote(),
        h('p', { class: 'muted small' }, 'Results, ex-dividend and payment dates for the stocks in this app, from Yahoo Finance and from headlines of prominent news outlets (CNBC TV18, Economic Times, Mint and similar), plus dividend dates estimated from each company\'s own payment pattern. Tap an event for its sources. Every date shows whether two agree, and news items show their headline. Dates can change, so check the exchange notice before acting. The NSE and BSE do not allow free scripted access to their own corporate-action lists, so splits and bonus issues appear only when a prominent outlet has reported them.')]
        .flat(Infinity).filter(Boolean));
      decorateHelp(root);
    }
    draw();
    return root;
  }

  /* ---------- market tab ---------- */
  const SRC_TEXT = {
    DELAYED: 'Free market data, up to about 15 minutes late.',
    DERIVED: 'Worked out by this app from the stocks in its own list, not from the whole exchange.',
    EXTERNAL: 'Headlines from outside sources. They are not checked or endorsed by this app.',
    YAHOO: 'A date taken from Yahoo Finance. The company confirms its dates by notice to the exchange, so check the official notice before relying on it.',
    OFFICIAL: 'Taken from, or checked against, the announcements that companies make to the National Stock Exchange, read from its public announcement feeds.',
    NEWS: 'Reported in a headline from a prominent news outlet (shown below). Official sources could not be read, so check the exchange notice before relying on it.',
    AGREED: 'Two independent sources give this date: for example Yahoo and a news headline, or an estimate and a news headline.',
    ESTIMATED: 'Worked out by this app from how often the company has paid in the past. The company may announce a different date.',
  };
  const src = (kind) => h('span', { class: 'src', title: SRC_TEXT[kind] }, kind);
  const moveClass = (v) => (isNum(v) ? (v >= 0 ? 'up' : 'down') : '');

  function miniChart(values) {
    const v = (values || []).filter(isNum);
    if (v.length < 3) return null;
    const lo = Math.min(...v), hi = Math.max(...v), span = hi - lo || 1;
    const pts = v.map((x, i) => `${(i / (v.length - 1) * 100).toFixed(1)},${(26 - (x - lo) / span * 24).toFixed(1)}`).join(' ');
    return svg('svg', { class: 'mini', viewBox: '0 0 100 28', preserveAspectRatio: 'none', role: 'img', 'aria-label': 'Last 30 sessions' },
      svg('polyline', { points: pts, fill: 'none', stroke: 'currentColor', 'stroke-width': '1.6', 'vector-effect': 'non-scaling-stroke' }));
  }

  function conditionsCard(market, c) {
    const name = (MARKET_NAMES[market] || market).replace(' (NSE)', '');
    const r = c && c.regime;
    if (!r) return h('div', { class: 'card' }, h('h3', null, `${name} market conditions`), h('p', { class: 'muted small' }, 'Not available right now: the index history could not be loaded.'));
    const pos = clamp((r.score + 7) / 14 * 100, 0, 100);
    const tone = r.score >= 2 ? 'up' : r.score <= -2 ? 'down' : '';
    return h('div', { class: 'card' },
      h('div', { class: 'row', style: 'justify-content:space-between;gap:6px' }, h('h3', { style: 'margin:0' }, `${name} market conditions`), src('DERIVED')),
      h('div', { class: `regime ${tone}` }, r.label),
      h('div', { class: 'meter', role: 'img', 'aria-label': `Conditions score ${r.score} on a scale from minus 7 to plus 7` }, h('i', { style: `left:${pos}%` })),
      h('div', { class: 'muted small' }, `Score ${r.score > 0 ? '+' : ''}${r.score} of 7 · ${c.name || 'Index'} as of ${r.as_of}`),
      h('ul', { class: 'clean checks' }, r.checks.map((k) => h('li', null,
        h('span', { class: `chk ${k.score > 0 ? 'pos' : k.score < 0 ? 'neg' : ''}` }, k.score > 0 ? '+1' : k.score < 0 ? '−1' : '0'),
        h('span', null, h('b', null, k.label), h('div', { class: 'muted small' }, k.detail))))));
  }

  function breadthCard(market, c) {
    const b = c && c.breadth;
    const name = (MARKET_NAMES[market] || market).replace(' (NSE)', '');
    if (!b) return null;
    return h('div', { class: 'card' },
      h('div', { class: 'row', style: 'justify-content:space-between;gap:6px' }, h('h3', { style: 'margin:0' }, `${name} breadth`), src('DERIVED')),
      h('div', { class: 'row', style: 'gap:6px;margin:6px 0' },
        h('span', { class: 'tag buy' }, `${b.advancing} advancing`), h('span', { class: 'tag sell' }, `${b.declining} declining`), h('span', { class: 'tag' }, `${b.unchanged} unchanged`)),
      kv([['Above 20-day average', isNum(b.above20_pct) ? `${b.above20_pct.toFixed(0)}%` : '–'],
        ['Above 50-day average', isNum(b.above50_pct) ? `${b.above50_pct.toFixed(0)}%` : '–'],
        ['Above 200-day average', isNum(b.above200_pct) ? `${b.above200_pct.toFixed(0)}%` : '–'],
        ['New 20-day highs / lows', `${b.new_highs} / ${b.new_lows}`]]),
      h('p', { class: 'muted small', style: 'margin-bottom:0' }, `Counted over the ${b.n} stocks in this app's list that traded on ${b.as_of}. It is not the whole exchange.`));
  }

  function sectorCard(market, c) {
    const rows = (c && c.sectors) || [];
    if (!rows.length) return null;
    const name = (MARKET_NAMES[market] || market).replace(' (NSE)', '');
    const cell = (v) => h('td', { class: `num ${moveClass(v)}` }, signed(v, 1));
    return h('div', { class: 'card', style: 'padding:0;overflow-x:auto' },
      h('div', { class: 'row', style: 'justify-content:space-between;gap:6px;padding:10px 12px 0' }, h('h3', { style: 'margin:0' }, `${name} sectors`), src('DERIVED')),
      h('table', null, h('thead', null, h('tr', null, h('th', null, 'Sector'), h('th', { class: 'num' }, '1 day'), h('th', { class: 'num' }, '5 days'), h('th', { class: 'num' }, '20 days'), h('th', { class: 'num' }, 'Stocks'))),
        h('tbody', null, rows.map((s) => h('tr', null, h('td', null, s.sector), cell(s.d1), cell(s.d5), cell(s.d20), h('td', { class: 'num muted' }, String(s.n)))))),
      h('p', { class: 'muted small', style: 'padding:0 12px 8px;margin:6px 0 0' }, 'Average move of the stocks in each sector, every stock counted the same.'));
  }

  function accuracyCard(accuracy, live) {
    const rows = ['IN'].map((k) => (accuracy || {})[k]).filter(Boolean);
    if (!rows.length) return null;
    const pct = (v, d = 3) => (isNum(v) ? `${v.toFixed(d)}%` : '–');
    return h('div', null, h('h2', null, 'Price accuracy ', src('DERIVED')),
      h('div', { class: 'grid' }, live ? h('div', { class: 'card' },
        h('h3', { style: 'margin:0 0 4px' }, 'India live prices: NSE live snapshot'),
        h('div', { class: `regime ${live.mismatch ? 'down' : 'up'}` }, `${live.match} of ${live.compared} match`),
        kv([['Stocks compared (biggest movers)', String(live.compared)], ['Match within 1%', String(live.match)], ['Differ 1% to 3%', String(live.minor)],
          ['Differ more than 3%', String(live.mismatch)], ['Median difference', pct(live.median_diff_pct)], ['Largest difference', pct(live.max_diff_pct, 2)],
          ['Snapshot time', live.as_of ? String(live.as_of).slice(0, 16).replace('T', ' ') + ' IST' : '–']]),
        h('p', { class: 'muted small', style: 'margin-bottom:0' }, 'The NSE lists only its biggest movers, so most stocks have no live check. A mover more than 3% away from the NSE price gets no alert.')) : null, rows.map((s) => h('div', { class: 'card' },
        h('h3', { style: 'margin:0 0 4px' }, `India: ${s.source}`),
        h('div', { class: `regime ${s.mismatch ? 'down' : 'up'}` }, isNum(s.agreement_pct) ? `${s.agreement_pct.toFixed(1)}% match` : 'Not checked'),
        kv([['Stocks checked', `${s.verified} of ${s.stocks}`], ['Match within 0.5%', String(s.match)], ['Differ 0.5% to 2%', String(s.minor)],
          ['Differ more than 2%', String(s.mismatch)], ['Feed a session behind', String(s.behind || 0)], ['Median difference', pct(s.median_diff_pct)], ['Largest difference', pct(s.max_diff_pct, 2)],
          ['Latest session compared', s.as_of || '–'], ['Not covered', String(s.unverified)]]),
        s.worst && s.worst.length ? h('p', { class: 'muted small', style: 'margin-bottom:0' }, 'Largest differences: ', s.worst.map((w) => `${w.symbol} ${w.max_diff_pct}%`).join(', ')) : null))),
      h('p', { class: 'muted small' }, 'The Yahoo closing prices on the last completed sessions are compared with the source named above. Live prices during the session are Yahoo, checked against the NSE live snapshot for the biggest movers only.'));
  }

  function liveLine(s) {
    const l = s.live_check;
    if (!l) return null;
    const when = l.as_of ? ` (snapshot ${String(l.as_of).slice(11, 16)} IST)` : '';
    if (l.status === 'match') return h('div', { class: 'muted small' }, h('span', { class: 'tag buy' }, 'Live price checked'), ` against the NSE live snapshot: ${l.diff_pct > 0 ? '+' : ''}${l.diff_pct}%${when}`);
    if (l.status === 'minor') return h('div', { class: 'muted small' }, h('span', { class: 'tag' }, 'Live price differs a little'), ` from the NSE live snapshot by ${l.diff_pct}%${when}. Read a moment apart on a moving price.`);
    return h('div', { class: 'muted small' }, h('span', { class: 'tag warn' }, 'Live price disagrees'), ` with the NSE live snapshot by ${l.diff_pct}%${when}. New alerts for this stock are paused.`);
  }

  function qualityLine(s) {
    const q = s.quality;
    if (!q) return h('div', { class: 'muted small' }, 'Prices not cross-checked: no second source covers this stock.');
    const detail = `largest difference ${q.max_diff_pct}% over ${q.n} session${q.n === 1 ? '' : 's'}`;
    if (q.status === 'match') return h('div', { class: 'muted small' }, h('span', { class: 'tag buy' }, 'Cross-checked'), ` against ${q.source}: ${detail}`);
    if (q.status === 'minor') return h('div', { class: 'muted small' }, h('span', { class: 'tag' }, 'Small difference'), ` against ${q.source}: ${detail}`);
    if (q.status === 'behind') return h('div', { class: 'muted small' }, h('span', { class: 'tag warn' }, 'Price is a session behind'), ` ${q.source} already has the session of ${q.official_last}; the price feed ends on ${q.yahoo_last}. New alerts and tracked readings for this stock are paused until the feed catches up.`);
    return h('div', { class: 'muted small' }, h('span', { class: 'tag warn' }, 'Prices disagree'), ` with ${q.source}: ${detail}. New alerts for this stock are paused.`);
  }

  function statusCard(status) {
    if (!status || !status.checks) return null;
    const word = { ok: 'OK', warn: 'Check', info: 'Info' };
    const good = status.overall === 'ok';
    return h('details', { class: 'card status' },
      h('summary', null, h('b', null, 'Data status: '), good ? 'all checks passed' : 'some checks need attention'),
      h('ul', { class: 'clean' }, status.checks.map((c) => h('li', null, h('span', { class: `state ${c.state}` }, word[c.state] || c.state), h('b', null, c.name), ' ', h('span', { class: 'muted small' }, c.detail)))),
      h('p', { class: 'muted small', style: 'margin-bottom:0' }, `Updated ${S.data.generated_at ? new Date(S.data.generated_at).toLocaleString() : ''}. These checks run every time the data is refreshed.`));
  }

  function viewMarket() {
    const m = S.data.market || { watch: [], news: [] };
    const conditions = S.data.conditions || {};
    const markets = ['IN'].filter((k) => conditions[k]);
    const cards = m.watch.map((w) => h('div', { class: 'card' }, h('div', { class: 'muted small' }, w.name),
      h('div', { style: 'font-size:20px;font-weight:700' }, number(w.price, w.price > 1000 ? 0 : 2)),
      h('div', { class: moveClass(w.change_pct) }, `${signed(w.change_pct)} today`),
      h('div', { class: 'muted small' }, `${signed(w.month_pct, 1)} in a month`),
      miniChart(w.spark),
      w.regime ? h('span', { class: `tag ${w.regime === 'Downtrend' || w.regime === 'Fearful' ? 'warn' : ''}` }, w.regime) : null));
    return h('div', null,
      h('h2', null, 'Market conditions'),
      markets.length ? h('div', { class: 'grid' }, markets.map((k) => conditionsCard(k, conditions[k]))) : null,
      markets.length ? h('p', { class: 'muted small' }, 'Seven simple checks on the main index, each worth +1, 0 or −1. They describe how the market is behaving now. They are not a forecast and not a call on any stock.') : null,
      h('h2', null, 'Indexes and global cues ', src('DELAYED')),
      h('div', { class: 'grid' }, cards.length ? cards : h('div', { class: 'empty' }, 'Market data unavailable.')),
      h('p', { class: 'muted small' }, 'Uptrend means the index is above its 50 and 200-day averages. A fearful VIX (above 25) means large swings: use smaller positions.'),
      markets.some((k) => conditions[k].breadth) ? [h('h2', null, 'Breadth and sectors'),
        h('div', { class: 'grid' }, markets.map((k) => [breadthCard(k, conditions[k]), sectorCard(k, conditions[k])]))] : null,
      (S.data.alerts || []).length ? [h('h2', null, 'Recent alerts'), h('div', { class: 'card' }, h('ul', { class: 'clean' },
        [...S.data.alerts].reverse().map((a) => h('li', null, h('span', { style: 'white-space:pre-line' }, a.text),
          h('div', { class: 'muted small' }, ago(Math.max(0, Math.round((Date.now() / 1000 - a.ts) / 60))), ' ',
            a.symbol && (S.data.stocks.some((s) => s.symbol === a.symbol) || S.others.some((s) => s.symbol === a.symbol)) ? h('button', { type: 'button', class: 'chip', onclick: (e) => openDetail(a.symbol, e.currentTarget) }, 'View analysis') : null)))))] : null,
      h('h2', null, 'World and market news ', src('EXTERNAL')), h('div', { class: 'card' }, newsList(m.news, true)),
      accuracyCard(S.data.accuracy, S.data.live_check),
      dataHealthCard(),
      statusCard(S.data.status),
      h('p', { class: 'muted small' }, (S.data.exchange_data || {}).note || ''));
  }

  /* ---------- track record tab ---------- */
  const SIDE_TEXT = { buy: 'bullish', sell: 'bearish', hold: 'mixed' };
  const TERMS = [
    ['Success', 'The price reached the reference level before the volatility risk level or the time limit. Shown as Reference reached in the tables.'],
    ['Failure', 'The price reached the volatility risk level first. Shown as Risk level reached in the tables.'],
    ['Expired', 'Neither level was reached within 20 trading days (weeks view) or 120 (months-to-years view).'],
    ['Avg move', 'Average price move in the direction of the reading, after a 0.1% cost.'],
    ['vs index', 'Average return minus what the market index did over the same days.'],
  ];

  function statRow(label, g, min) {
    const range = (ci) => (ci ? ` (${ci[0].toFixed(0)}-${ci[1].toFixed(0)}%)` : '');
    const unsure = !g.reliable;
    return h('tr', { class: unsure ? 'unsure' : null },
      h('td', null, label, unsure ? h('span', { class: 'tag warn', title: `Fewer than ${min} resolved readings: too few to trust` }, 'few readings') : null),
      h('td', { class: 'num' }, String(g.n)),
      h('td', { class: 'num' }, isNum(g.target_pct) ? `${g.target_pct.toFixed(0)}%${range(g.target_ci)}` : '–'),
      h('td', { class: 'num' }, isNum(g.stop_pct) ? `${g.stop_pct.toFixed(0)}%` : '–'),
      h('td', { class: 'num' }, isNum(g.expired_pct) ? `${g.expired_pct.toFixed(0)}%` : '–'),
      h('td', { class: `num ${isNum(g.avg_return) ? (g.avg_return >= 0 ? 'up' : 'down') : ''}` }, signed(g.avg_return)),
      h('td', { class: `num ${isNum(g.avg_excess) ? (g.avg_excess >= 0 ? 'up' : 'down') : ''}` }, signed(g.avg_excess)));
  }

  function statTable(title, groups, min) {
    const entries = Object.entries(groups || {}).filter(([, g]) => g.n > 0);
    if (!entries.length) return null;
    return [h('h3', null, title), h('div', { class: 'card', style: 'padding:0;overflow-x:auto' }, h('table', null,
      h('thead', null, h('tr', null, ['Group', 'Readings', 'Reference reached', 'Risk level reached', 'Expired', 'Avg move', 'vs index'].map((x, i) => h('th', { class: i ? 'num' : null }, x)))),
      h('tbody', null, entries.map(([label, g]) => statRow(label, g, min)))))];
  }

  /* One stacked bar: success (reference level reached first), failure (risk level reached first), expired. */
  function outcomeBar(g, tall) {
    const parts = [['ok', g.target_pct], ['bad', g.stop_pct], ['na', g.expired_pct]];
    return h('div', { class: `outbar${tall ? ' tall' : ''}`, role: 'img', 'aria-label': `${Math.round(g.target_pct || 0)} percent reached the reference level, ${Math.round(g.stop_pct || 0)} percent reached the risk level, ${Math.round(g.expired_pct || 0)} percent expired` },
      parts.map(([k, v]) => (isNum(v) && v > 0 ? h('i', { class: k, style: `flex:${v}` }) : null)));
  }

  const pct0 = (v) => (isNum(v) ? `${v.toFixed(0)}%` : '\u2013');

  function outcomeLegend(g) {
    return h('div', { class: 'outlegend' },
      h('span', null, h('i', { class: 'dot ok' }), `Success ${pct0(g.target_pct)}`), h('span', null, h('i', { class: 'dot bad' }), `Failure ${pct0(g.stop_pct)}`),
      h('span', null, h('i', { class: 'dot na' }), `Expired ${pct0(g.expired_pct)}`));
  }

  /* The headline: what share of settled readings succeeded, or how far off a trustworthy figure still is. */
  function scoreboard(t, min) {
    const o = t.overall || { n: 0 };
    if (!o.n) {
      const done = t.resolved || 0;
      return h('section', { class: 'card score' },
        h('div', { class: 'scoretitle' }, 'Too early for a success rate'),
        h('div', { class: 'big' }, String(done), h('span', { class: 'bigof' }, ` of ${min} readings settled`)),
        h('div', { class: 'outbar tall', role: 'img', 'aria-label': `${done} of ${min} readings settled` }, h('i', { class: 'ok', style: `flex:${Math.max(done, 0.001)}` }), h('i', { class: 'blank', style: `flex:${Math.max(min - done, 0)}` })),
        h('p', { class: 'small', style: 'margin:8px 0 0' }, `${t.open || 0} readings are open. One settles when its price reaches the reference level (success), reaches the risk level (failure) or runs out of time. The success rate appears once ${min} have settled; before that, any figure would be too unreliable to trust.`));
    }
    const move = isNum(o.avg_return) ? h('span', { class: o.avg_return >= 0 ? 'up' : 'down' }, `${signed(o.avg_return)} average move`) : null;
    const excess = isNum(o.avg_excess) ? h('span', { class: o.avg_excess >= 0 ? 'up' : 'down' }, `${signed(o.avg_excess)} against the index`) : null;
    return h('section', { class: 'card score' },
      h('div', { class: 'scoretitle' }, 'Success rate of settled readings', o.reliable ? null : h('span', { class: 'tag warn' }, 'early figure')),
      h('div', { class: 'big' }, pct0(o.target_pct), h('span', { class: 'bigof' }, ` of ${o.n} reached the reference level first`)),
      outcomeBar(o, true), outcomeLegend(o),
      h('div', { class: 'moves small' }, move, excess),
      o.reliable ? null : h('p', { class: 'muted small', style: 'margin:6px 0 0' }, `Only ${o.n} readings have settled. With fewer than ${min} the rate can swing a lot, so treat it as a first look.`));
  }

  function groupCards(t) {
    const entries = Object.entries(t.by_group || {}).filter(([, g]) => g.n > 0);
    if (!entries.length) return null;
    return [h('h3', null, 'By reading type'), h('div', { class: 'tgroups' }, entries.map(([label, g]) => h('div', { class: 'card tgroup' },
      h('div', { class: 'small muted' }, label), h('div', { class: 'gbig' }, pct0(g.target_pct), g.reliable ? null : h('span', { class: 'tag warn' }, 'few')),
      outcomeBar(g, false), h('div', { class: 'small muted' }, `${g.n} settled`, isNum(g.avg_return) ? ` \u00B7 ${signed(g.avg_return)} average move` : ''))))];
  }

  function viewTrack() {
    const t = S.data.track_record;
    if (!t) {
      return h('div', null, h('h2', null, 'Track record'),
        h('div', { class: 'empty' }, 'No track record yet. Every bullish or bearish alert is recorded with its reference level and volatility risk level, and checked against later prices. Results appear here once readings have resolved.'));
    }
    const min = t.min_sample || 30;
    const o = t.overall || { n: 0 };
    const notes = (t.suggestions || []).map((s) => h('li', null, s.text, ' ', h('span', { class: 'muted small' }, s.evidence ? `(${s.evidence})` : '')));
    const comps = (t.components || []).filter((c) => c.comparable);
    const compRows = comps.map((c) => h('tr', null,
      h('td', null, `${c.horizon === 'short' ? 'Weeks view' : 'Months-to-years view'}: ${c.component}`),
      h('td', { class: 'num' }, `${c.supporting.n}`), h('td', { class: 'num' }, signed(c.supporting.avg_return)),
      h('td', { class: 'num' }, `${c.against.n}`), h('td', { class: 'num' }, signed(c.against.avg_return))));
    const recent = (t.recent || []).map((r) => h('tr', null,
      h('td', { class: 'name' }, h('b', null, r.name || r.symbol), h('span', null, `${r.symbol}, ${r.horizon === 'short' ? 'weeks view' : 'months-to-years view'}, ${SIDE_TEXT[r.side] || r.side}`)),
      h('td', null, h('span', { class: `tag ${r.outcome === 'target' ? 'buy' : r.outcome === 'stop' ? 'sell' : ''}` }, r.outcome === 'target' ? 'Success' : r.outcome === 'stop' ? 'Failure' : 'Expired')),
      h('td', { class: `num ${r.return_pct >= 0 ? 'up' : 'down'}` }, signed(r.return_pct)),
      h('td', { class: 'num' }, `${shortDay(r.date)} to ${shortDay(r.resolved_date)}`)));
    const open = (t.open_calls || []).map((c) => h('tr', null,
      h('td', { class: 'name' }, h('b', null, c.name || c.symbol), h('span', null, `${c.symbol}, ${c.horizon === 'short' ? 'weeks view' : 'months-to-years view'}, ${SIDE_TEXT[c.side] || c.side}, since ${shortDay(c.date)}`)),
      h('td', { class: 'num' }, money(c.price, c.currency)), h('td', { class: 'num' }, money(c.target, c.currency)),
      h('td', { class: 'num' }, money(c.stop, c.currency))));
    const table = (heads, rows) => h('div', { class: 'card', style: 'padding:0;overflow-x:auto' }, h('table', null,
      h('thead', null, h('tr', null, heads.map((x, i) => h('th', { class: i ? 'num' : null }, x)))), h('tbody', null, rows)));
    const detail = [statTable('By indicator alignment', t.by_score_band, min), statTable('By market', t.by_market, min),
      compRows.length ? [h('h3', null, 'Which indicators lined up with the outcome'), table(['Indicator', 'Readings it supported', 'Avg move', 'Readings it opposed', 'Avg move'], compRows)] : null,
      h('h3', null, 'Ideas to review'), h('div', { class: 'card' }, notes.length ? h('ul', { class: 'clean' }, notes) : h('span', { class: 'muted' }, 'Nothing to suggest yet.'),
        h('p', { class: 'muted small' }, 'These are observations for you to judge. The app never changes its own rules.')),
      h('h3', null, 'What the words mean'), h('dl', { class: 'terms' }, TERMS.map(([k, v]) => [h('dt', null, h('b', null, k)), h('dd', null, v)]))];
    return h('div', null,
      h('h2', null, 'Track record'),
      learningCard(),
      scoreboard(t, min),
      h('p', { class: 'muted small' }, `${t.calls_total} readings recorded under the current rules: ${t.resolved} settled, ${t.open} open.${t.void ? ` ${t.void} more were set aside as not entered (the reference price never traded on the day of the alert), so they are neither successes nor failures.` : ''}${t.older_model_calls ? ` ${t.older_model_calls} more from earlier versions of the rules are kept in the record but not counted here.` : ''} A past record, not a forecast.`),
      groupCards(t),
      recent.length ? [h('h3', null, 'Latest results'), table(['Reading', 'Result', 'Move', 'Dates'], recent)] : null,
      open.length ? h('details', { class: 'card opencalls', open: !o.n }, h('summary', null, `Open readings (${t.open}${t.open > open.length ? `, latest ${open.length} listed` : ''})`),
        h('div', { style: 'overflow-x:auto' }, h('table', null, h('thead', null, h('tr', null, ['Reading', 'Price', 'Reference level', 'Risk level'].map((x, i) => h('th', { class: i ? 'num' : null }, x)))), h('tbody', null, open)))) : null,
      h('details', { class: 'card moredetail' }, h('summary', null, 'More detail'), detail),
      t.data_url ? h('p', { class: 'muted small' }, 'Every reading and outcome is stored as plain files for anyone to check: ', h('a', { href: t.data_url, target: '_blank', rel: 'noopener' }, 'the data branch on GitHub'), '.') : null);
  }

  /* ---------- shell ---------- */
  function render() {
    for (const b of document.querySelectorAll('.tabs button, .bottomnav button')) {
      if (b.dataset.tab === S.tab) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
    }
    for (const current of document.querySelectorAll('.bottomnav [aria-current="page"], .tabs [aria-current="page"]')) {          // a bar that scrolls keeps the open tab in view
      if (current.scrollIntoView) { try { current.scrollIntoView({ inline: 'center', block: 'nearest' }); } catch (e) { /* older browser */ } }
    }
    const view = $('#view');
    if (!S.data) { view.replaceChildren(h('div', { class: 'empty' }, S.error || 'Loading...')); return; }
    const builders = { signals: viewSignals, suggest: viewSuggest, news: viewNews, announcements: viewAnnouncements, alerts: viewAlerts, rules: viewRules, ipo: viewIpo, market: viewMarket, events: viewEvents, track: viewTrack };
    view.replaceChildren((builders[S.tab] || viewSignals)());
    decorateHelp(view);
  }

  /* Settings live on the device. A code moves them to another one by hand: no account, no server. */
  function backupCard() {
    const area = h('textarea', { rows: '3', placeholder: 'Paste a settings code here', 'aria-label': 'Settings code', spellcheck: 'false' });
    const status = h('p', { class: 'muted small', role: 'status' });
    const code = () => Rules.packSettings({ watch: [...S.watch], lists: S.lists, prefs: AL.prefs, rules: AL.rules });
    const importCode = () => {
      const got = Rules.unpackSettings(area.value);
      if (!got) { status.textContent = 'That is not a settings code. Copy the whole text, starting with SS1:'; return; }
      if (!confirm(`Replace this device's settings with the code's: ${got.watch.length} stocks on the watchlist, ${Object.keys(got.lists).length} lists, ${got.rules.length} rules?`)) return;
      S.watch = new Set(got.watch); saveWatch();
      S.lists = got.lists; store.set('lists', S.lists);
      AL.prefs = got.prefs; savePrefs();
      AL.rules = got.rules; AL.rules.forEach((r) => { if (!r.id) r.id = newId(); }); saveRules();
      AL.matched = {}; store.set('ruleMatched', AL.matched);          // rules start again from what matches now, without announcing it
      toast('Settings imported.'); render(); checkAlerts();
    };
    return h('details', { class: 'card al-types' }, h('summary', null, h('span', null, 'Move settings to another device')),
      h('p', { class: 'muted small' }, 'Your watchlist, lists, alert switches and rules live only on this device. To use them on another one, copy the code here and paste it there. No account is needed.'),
      h('div', { class: 'al-actions' },
        h('button', { type: 'button', class: 'btn ghost', onclick: async () => { try { await navigator.clipboard.writeText(code()); status.textContent = 'Code copied.'; } catch (e) { area.value = code(); area.select(); status.textContent = 'Select the text and copy it.'; } } }, 'Copy code'),
        h('button', { type: 'button', class: 'btn ghost', onclick: () => window.open(`https://t.me/share/url?url=${encodeURIComponent(location.origin + location.pathname)}&text=${encodeURIComponent(code())}`, '_blank', 'noopener') }, 'Send to my Telegram')),
      area, h('div', { class: 'al-actions' }, h('button', { type: 'button', class: 'btn', onclick: importCode }, 'Import')), status);
  }

  /* ---------- the Alerts tab ---------- */
  const AL_UI = { draft: null, open: new Set() };
  const FIELD_LIST = Rules.fields();
  const FIELD_BY_KEY = Object.fromEntries(FIELD_LIST.map((f) => [f.key, f]));
  const blankCond = (key) => {
    const f = FIELD_BY_KEY[key];
    return f.type === 'num' ? { field: key, op: key === 'rsi' ? '<' : '>', value: key === 'rsi' ? 30 : 0 } : { field: key, op: 'is', value: f.options[0][0] };
  };
  const sectorNames = () => [...new Set(S.data.stocks.map((s) => s.sector).filter((x) => x && x !== 'Other'))].sort();
  const scopeValue = (sc) => (sc.kind === 'LIST' ? 'L:' + sc.value : sc.kind === 'SECTOR' ? 'S:' + sc.value : sc.kind);
  const scopeFrom = (v) => (v.startsWith('L:') ? { kind: 'LIST', value: v.slice(2) } : v.startsWith('S:') ? { kind: 'SECTOR', value: v.slice(2) } : { kind: v });

  // How many stocks a rule matches now, and how many it could not be decided for. Rules on indicators need the indicator file of the other stocks.
  function countFor(rule) {
    if (Rules.needsDeep(rule) && S.extra !== 'ready' && S.extra !== 'failed' && S.others.length) { loadExtra().then(() => { if (S.tab === 'alerts') updateAlertCounts(); }); return null; }
    return Rules.run(rule, allStocks(), ruleContext());
  }
  function countText(rule) {
    const r = countFor(rule);
    if (!r) return 'Counting...';
    const left = [r.noData ? `${r.noData} could not be checked for lack of data` : '', r.notApplicable ? `${r.notApplicable} banks and lenders skipped: this figure does not apply to them` : ''].filter(Boolean);
    return `${r.matches.length} stocks match now` + (left.length ? ` (${left.join('; ')})` : '');
  }
  function updateAlertCounts() {
    for (const el of document.querySelectorAll('[data-rule-count]')) {
      const rule = el.dataset.ruleCount === 'draft' ? Rules.clean(AL_UI.draft) : AL.rules.find((x) => x.id === el.dataset.ruleCount);
      if (rule) el.textContent = countText(rule);
    }
  }

  function ruleForm() {
    const d = AL_UI.draft;
    const box = h('div', { class: 'card al-form' });
    const draw = () => {
      const preview = h('p', { class: 'al-count', 'data-rule-count': 'draft' });
      const refresh = () => { const rule = Rules.clean(d); preview.textContent = rule ? countText(rule) : 'Fill in every condition with a number or choice.'; };
      const fieldSelect = (c, i) => h('select', { 'aria-label': 'Field', onchange: (e) => { d.conds[i] = blankCond(e.target.value); draw(); } },
        [...new Set(FIELD_LIST.map((f) => f.group))].map((g) => h('optgroup', { label: g }, FIELD_LIST.filter((f) => f.group === g).map((f) => h('option', { value: f.key, selected: f.key === c.field }, f.label)))));
      const valueInput = (c) => {
        const f = FIELD_BY_KEY[c.field];
        if (f.type === 'num') return h('input', { type: 'number', step: 'any', value: String(c.value), 'aria-label': 'Value', oninput: (e) => { c.value = e.target.value === '' ? '' : Number(e.target.value); refresh(); } });
        return h('select', { 'aria-label': 'Value', onchange: (e) => { c.value = e.target.value; refresh(); } }, f.options.map(([k, label]) => h('option', { value: k, selected: k === c.value }, label)));
      };
      const opSelect = (c) => {
        const f = FIELD_BY_KEY[c.field];
        return h('select', { 'aria-label': 'Condition', onchange: (e) => { c.op = e.target.value; refresh(); } }, (f.type === 'num' ? Rules.NUMBER_OPS : Rules.ENUM_OPS).map(([k, label]) => h('option', { value: k, selected: k === c.op }, label)));
      };
      box.replaceChildren(
        h('h3', null, d.id ? 'Edit rule' : 'New rule'),
        h('div', { class: 'al-grid' },
          h('label', { class: 'field' }, h('span', null, 'Name'), h('input', { type: 'text', maxlength: '40', value: d.name, oninput: (e) => { d.name = e.target.value; } })),
          h('label', { class: 'field' }, h('span', null, 'Stocks to check'), h('select', { onchange: (e) => { d.scope = scopeFrom(e.target.value); refresh(); } },
            h('option', { value: 'ALL', selected: d.scope.kind === 'ALL' }, 'The whole market list'), h('option', { value: 'WATCH', selected: d.scope.kind === 'WATCH' }, 'My watchlist'),
            Object.keys(S.lists).map((n) => h('option', { value: 'L:' + n, selected: scopeValue(d.scope) === 'L:' + n }, 'My list: ' + n)),
            sectorNames().map((n) => h('option', { value: 'S:' + n, selected: scopeValue(d.scope) === 'S:' + n }, 'Sector: ' + n)))),
          h('label', { class: 'field' }, h('span', null, 'Alert when'), h('select', { onchange: (e) => { d.mode = e.target.value; refresh(); } },
            h('option', { value: 'all', selected: d.mode === 'all' }, 'ALL conditions are true'), h('option', { value: 'any', selected: d.mode === 'any' }, 'ANY condition is true')))),
        ...d.conds.map((c, i) => h('div', { class: 'al-cond' }, fieldSelect(c, i), h('div', { class: 'al-condrow' }, opSelect(c), valueInput(c),
          d.conds.length > 1 ? h('button', { type: 'button', class: 'linkbtn danger', 'aria-label': 'Remove condition', onclick: () => { d.conds.splice(i, 1); draw(); } }, 'Remove') : null))),
        h('div', { class: 'al-actions' },
          d.conds.length < Rules.MAX_CONDITIONS ? h('button', { type: 'button', class: 'linkbtn', onclick: () => { d.conds.push(blankCond('change_pct')); draw(); } }, '+ Add condition') : null),
        preview,
        h('div', { class: 'al-buttons' },
          h('button', { type: 'button', class: 'btn', onclick: () => {
            const rule = Rules.clean(d);
            if (!rule) { toast('Fill in every condition with a number or choice first.'); return; }
            if (d.id) { const i = AL.rules.findIndex((x) => x.id === d.id); rule.id = d.id; AL.rules[i] = rule; }
            else if (AL.rules.length >= Rules.MAX_RULES) { toast(`You can keep up to ${Rules.MAX_RULES} rules.`); return; }
            else { rule.id = newId(); AL.rules.push(rule); }
            delete AL.matched[rule.id];                          // a changed rule starts again from what matches now, without announcing it
            saveRules(); store.set('ruleMatched', AL.matched); AL_UI.draft = null; checkAlerts(); render();
          } }, 'Save rule'),
          h('button', { type: 'button', class: 'btn ghost', onclick: () => { AL_UI.draft = null; render(); } }, 'Cancel')));
      refresh();
    };
    draw();
    return box;
  }

  const switchEl = (checked, label, onchange) => h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked, onchange }), h('span', { class: 'track', 'aria-hidden': 'true' }), h('span', { class: 'swtext' }, label));
  const alSection = (title, hint) => h('div', { class: 'al-sec' }, h('h3', null, title), hint ? h('p', { class: 'muted small' }, hint) : null);

  /* ---------- the Rules tab: each rule and the stocks that fall under it ---------- */
  const RULE_PRESETS = [
    { name: 'Oversold in an uptrend', mode: 'all', scope: { kind: 'ALL' }, conds: [{ field: 'rsi', op: '<', value: 30 }, { field: 'vs_sma200', op: '>', value: 0 }] },
    { name: 'Quality at a fair price', mode: 'all', scope: { kind: 'ALL' }, conds: [{ field: 'roe', op: '>', value: 15 }, { field: 'pe', op: '<', value: 25 }, { field: 'debt_equity', op: '<', value: 1 }] },
    { name: 'Steady growers', mode: 'all', scope: { kind: 'ALL' }, conds: [{ field: 'rev_cagr3', op: '>', value: 10 }, { field: 'profit_cagr3', op: '>', value: 10 }, { field: 'profit_up_years', op: '>', value: 2 }] },
    { name: 'Strong and near a 52-week high', mode: 'all', scope: { kind: 'ALL' }, conds: [{ field: 'from_high', op: '<', value: 5 }, { field: 'rs126', op: '>', value: 0 }] },
    { name: 'Dividend payers', mode: 'all', scope: { kind: 'ALL' }, conds: [{ field: 'dividend_yield', op: '>', value: 3 }, { field: 'roe', op: '>', value: 10 }] },
    { name: 'Heavy volume and rising', mode: 'all', scope: { kind: 'ALL' }, conds: [{ field: 'volume_ratio', op: '>', value: 2 }, { field: 'change_pct', op: '>', value: 3 }] },
  ];
  const RULES_UI = { sel: null, q: '', shown: 50, sort: null };
  const rulesLoading = (rule) => Rules.needsDeep(rule) && S.extra !== 'ready' && S.extra !== 'failed' && S.others.length;

  /* How a figure of a rule's field is written in the table. */
  function fieldText(f, v) {
    if (f.type === 'enum') return (f.options.find(([k]) => k === v) || [])[1] || String(v);
    if (/\(%\)|%\)/.test(f.label)) return `${v.toFixed(1)}%`;
    if (/Rs crore/.test(f.label)) return Math.round(v).toLocaleString('en-IN');
    if (/points/.test(f.label)) return signed(v, 1, '');
    return Math.abs(v) >= 100 ? Math.round(v).toLocaleString('en-IN') : v.toFixed(Math.abs(v) >= 10 ? 1 : 2);
  }
  const shortFieldLabel = (f) => f.label.replace(/\s*\(.*?\)\s*/g, ' ').replace(/,.*$/, '').replace(/, latest year/, '').trim();

  function viewRules() {
    const ctx = ruleContext();
    if (RULES_UI.sel && !AL.rules.some((r) => r.id === RULES_UI.sel)) RULES_UI.sel = null;
    if (!RULES_UI.sel && AL.rules.length) RULES_UI.sel = AL.rules[0].id;
    const rule = AL.rules.find((r) => r.id === RULES_UI.sel) || null;
    const listNote = S.catalog === 'ready' ? `${(S.others.length + S.data.stocks.length).toLocaleString()} stocks` : S.catalog === 'failed' ? 'the main list only (the full list could not be loaded)' : 'the whole list (still loading)';

    const addPreset = (p) => {
      if (AL.rules.length >= Rules.MAX_RULES) { toast(`You can keep up to ${Rules.MAX_RULES} rules.`); return; }
      const made = Rules.clean({ ...p, id: newId() });
      if (!made) return;
      AL.rules.push(made); saveRules(); RULES_UI.sel = made.id; RULES_UI.shown = 50; RULES_UI.sort = null; checkAlerts(); render();
    };
    const newRule = () => { AL_UI.draft = { name: 'My rule', mode: 'all', scope: { kind: 'ALL' }, conds: [blankCond('change_pct')] }; render(); };

    // the picker: one chip per rule with its count, and a chip to add one
    const counts = new Map();
    for (const r of AL.rules) { const res = rulesLoading(r) ? null : Rules.run(r, allStocks(), ctx); counts.set(r.id, res); }
    const picker = h('div', { class: 'catchips rulepick', role: 'tablist', 'aria-label': 'Your rules' },
      AL.rules.map((r) => h('button', { type: 'button', class: 'chip' + (r.id === RULES_UI.sel ? ' on' : ''), role: 'tab', 'aria-selected': String(r.id === RULES_UI.sel),
        onclick: () => { RULES_UI.sel = r.id; RULES_UI.shown = 50; RULES_UI.sort = null; RULES_UI.q = ''; render(); } },
        r.name, ' ', h('span', { class: 'n' }, counts.get(r.id) ? String(counts.get(r.id).matches.length) : '…'))),
      h('button', { type: 'button', class: 'chip', onclick: newRule }, '+ New rule'));

    const parts = [h('h2', null, 'Rules'),
      h('p', { class: 'muted' }, `A rule is a set of conditions. Each one shows which stocks fall under it right now, checked against ${listNote}.`)];

    if (!AL.rules.length && !AL_UI.draft) {
      parts.push(h('div', { class: 'card al-rule' }, h('strong', null, 'No rules yet'), h('p', { class: 'al-desc' }, 'Start from an example, or build your own. Examples are screens on reported figures, not recommendations.'),
        h('div', { class: 'presets' }, RULE_PRESETS.map((p) => h('div', { class: 'preset' }, h('strong', null, p.name), h('p', { class: 'small muted' }, Rules.describe(Rules.clean(p))),
          h('button', { type: 'button', class: 'btn ghost', onclick: () => addPreset(p) }, 'Add'))))),
        h('button', { type: 'button', class: 'btn', onclick: newRule }, '+ Build my own'));
      return h('div', { class: 'al' }, ...parts);
    }
    parts.push(picker);
    if (AL_UI.draft) parts.push(ruleForm());

    if (rule && !AL_UI.draft) {
      const res = counts.get(rule.id);
      const fields = [...new Set(rule.conds.map((c) => c.field))].map((k) => FIELD_BY_KEY[k]).slice(0, 3);
      const byKey = new Map(allStocks().map((s) => [s.symbol, s]));
      const q = normText(RULES_UI.q);
      let rows = res ? res.matches.map((sym) => byKey.get(sym)).filter(Boolean) : [];
      if (q) rows = rows.filter((s) => `${normText(s.name)} ${normText(s.symbol)}`.includes(q));
      const sortKey = RULES_UI.sort || { key: fields[0] ? fields[0].key : 'name', dir: fields[0] && rule.conds.find((c) => c.field === fields[0].key).op === '<' ? 1 : -1 };
      const value = (s, key) => (key === 'name' ? s.name.toLowerCase() : key === 'price' ? s.price : key === 'chg' ? s.change_pct : (FIELD_BY_KEY[key].get(s, ctx)));
      rows = rows.slice().sort((a, b) => {
        const x = value(a, sortKey.key), y = value(b, sortKey.key);
        if (x == null && y == null) return 0; if (x == null) return 1; if (y == null) return -1;
        return (x < y ? -1 : x > y ? 1 : 0) * sortKey.dir;
      });
      const head = (key, label, num) => h('th', { class: num ? 'num' : '', 'aria-sort': sortKey.key === key ? (sortKey.dir === 1 ? 'ascending' : 'descending') : 'none' },
        h('button', { type: 'button', class: 'sorth' + (sortKey.key === key ? ' on' : ''), onclick: () => { RULES_UI.sort = { key, dir: sortKey.key === key ? -sortKey.dir : (key === 'name' ? 1 : -1) }; render(); } }, label, sortKey.key === key ? (sortKey.dir === 1 ? ' ▲' : ' ▼') : ''));
      const cell = (s, f) => { const v = f.get(s, ctx); return h('td', { class: 'num' }, v == null ? h('span', { class: 'na' }, 'n/a') : fieldText(f, v)); };
      const visible = rows.slice(0, RULES_UI.shown);
      const left = [res && res.noData ? `${res.noData} could not be checked for lack of data` : '', res && res.notApplicable ? `${res.notApplicable} banks and lenders skipped: this figure does not apply to them` : ''].filter(Boolean);

      parts.push(h('div', { class: 'card al-rule' + (rule.on ? '' : ' off') },
        h('div', { class: 'al-top' }, h('strong', null, rule.name), switchEl(rule.on, rule.on ? 'Alerts on' : 'Alerts off', (e) => { rule.on = e.target.checked; saveRules(); if (rule.on) delete AL.matched[rule.id]; checkAlerts(); render(); })),
        h('p', { class: 'al-desc' }, Rules.describe(rule)),
        h('p', { class: 'al-count' }, res ? `${res.matches.length} stocks fall under this rule now` + (left.length ? ` (${left.join('; ')})` : '') : 'Counting…'),
        h('div', { class: 'al-actions' },
          h('button', { type: 'button', class: 'linkbtn', onclick: () => { AL_UI.draft = JSON.parse(JSON.stringify(rule)); render(); } }, 'Edit'),
          h('button', { type: 'button', class: 'linkbtn danger', onclick: () => {
            if (!confirm(`Delete the rule "${rule.name}"?`)) return;
            AL.rules = AL.rules.filter((x) => x.id !== rule.id); delete AL.matched[rule.id]; saveRules(); store.set('ruleMatched', AL.matched); RULES_UI.sel = null; render();
          } }, 'Delete'))));

      if (res && rule.conds.some((c) => (FIELD_BY_KEY[c.field] || {}).deep) && S.extra === 'failed') parts.push(h('p', { class: 'al-note' }, 'The detailed figures could not be loaded, so stocks that need them are counted as "could not be checked".'));
      if (!res) {
        loadExtra().then(() => { if (S.tab === 'rules') render(); });
        parts.push(h('p', { class: 'muted small' }, 'Loading the figures for the whole list…'));
      } else if (!res.matches.length) {
        parts.push(h('div', { class: 'empty' }, 'No stock falls under this rule right now. It would alert you when one starts to.'));
      } else {
        parts.push(h('div', { class: 'row rulesearch' }, h('label', { class: 'field' }, h('span', null, 'Find in these stocks'),
          h('input', { type: 'search', value: RULES_UI.q, placeholder: 'Name or symbol', oninput: (e) => { RULES_UI.q = e.target.value; RULES_UI.shown = 50; clearTimeout(RULES_UI.t); RULES_UI.t = setTimeout(() => { render(); const el = $('.rulesearch input'); if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); } }, 250); } })),
          h('span', { class: 'muted small' }, `${rows.length} shown`)));
        parts.push(h('div', { class: 'peerwrap' }, h('table', { class: 'peertable ruletable' },
          h('thead', null, h('tr', null, head('name', 'Stock', false), head('price', 'Price', true), head('chg', 'Today', true), fields.map((f) => head(f.key, shortFieldLabel(f), true)), h('th', { class: 'hide-sm' }, 'Reading'))),
          h('tbody', null, visible.map((s) => h('tr', { class: 'clickrow', onclick: (e) => openDetail(s.symbol, e.currentTarget) },
            h('td', null, h('button', { type: 'button', class: 'linkbtn', onclick: (e) => { e.stopPropagation(); openDetail(s.symbol, e.currentTarget); } }, s.name), h('div', { class: 'muted small' }, s.symbol.replace(/\.NS$/, ''))),
            h('td', { class: 'num' }, money(s.price, s.currency)), h('td', { class: 'num ' + (s.change_pct > 0 ? 'up' : s.change_pct < 0 ? 'down' : '') }, signed(s.change_pct, 2)),
            fields.map((f) => cell(s, f)), h('td', { class: 'hide-sm' }, s.short && s.short.label ? badges(s, S.filters.horizon) : h('span', { class: 'muted small' }, 'not analysed'))))))));
        if (rows.length > visible.length) parts.push(h('button', { type: 'button', class: 'btn ghost', onclick: () => { RULES_UI.shown += 50; render(); } }, `Show 50 more (${rows.length - visible.length} left)`));
      }
      parts.push(h('p', { class: 'muted small' }, 'These are the stocks whose reported figures fit the conditions today. That is not a recommendation to buy or sell. Rule figures that need detailed data cover only the stocks analysed in depth.'));
    }
    return h('div', { class: 'al' }, ...parts);
  }

  function viewAlerts() {
    const typeGroups = [...new Set(Rules.TYPES.map((t) => t.group))];
    const onCount = Rules.TYPES.filter((t) => AL.prefs[t.key]).length;
    const setAll = (on) => { Rules.TYPES.forEach((t) => { AL.prefs[t.key] = on; }); savePrefs(); render(); };
    const known = (symbol) => S.data.stocks.some((s) => s.symbol === symbol) || S.others.some((s) => s.symbol === symbol);

    const log = AL.log.slice(0, 30).map((e) => {
      const t = istParts(e.ts);
      const kind = e.kind === 'rule' ? 'Rule' : (Rules.TYPES.find((x) => x.key === e.type) || {}).label || 'Alert';
      return h('li', null,
        h('div', { class: 'al-logtop' }, known(e.symbol) ? h('button', { type: 'button', class: 'linkbtn', onclick: (ev) => openDetail(e.symbol, ev.currentTarget) }, e.name || e.symbol) : h('strong', null, e.name || e.symbol),
          h('span', { class: 'muted small' }, `${t.day} ${t.time}`)),
        h('div', { class: 'small' }, e.text), h('div', { class: 'muted small' }, kind));
    });
    const listNote = S.catalog === 'ready' ? `${(S.others.length + S.data.stocks.length).toLocaleString()} stocks` : S.catalog === 'failed' ? 'the main list only (the full list could not be loaded)' : 'the whole list (still loading)';

    return (queueMicrotask(updateAlertCounts), h('div', { class: 'al' },
      h('h2', null, 'Alerts'),
      h('p', { class: 'muted' }, 'Get told when something happens to a stock you follow, or when a stock starts to match a rule of your own.'),
      h('details', { class: 'al-how' }, h('summary', null, 'How alerts work'),
        h('p', { class: 'muted small' }, 'Alerts are checked on this device each time the data refreshes (every 5 to 10 minutes) while the app is open. Your watchlist, switches and rules stay on this device and are never sent anywhere. For alerts when the app is closed, join the Telegram channel.'),
        h('p', { class: 'muted small' }, S.notify ? 'Phone popups are on. Use the Alerts button at the top to turn them off.' : 'Phone popups are off, so alerts show here and as a message in the app. Use the Alerts button at the top to allow popups.')),

      alSection('My rules'),
      h('div', { class: 'card al-rule' }, h('div', { class: 'al-top' }, h('strong', null, AL.rules.length ? `${AL.rules.length} rule${AL.rules.length === 1 ? '' : 's'}, ${AL.rules.filter((r) => r.on).length} sending alerts` : 'No rules yet'),
        h('button', { type: 'button', class: 'btn ghost', onclick: () => { S.tab = 'rules'; render(); } }, 'Open Rules')),
        h('p', { class: 'muted small' }, `A rule alerts when a stock newly starts to match it. Build rules, switch their alerts on or off and see which stocks fall under each one in the Rules tab.${listNote ? ` Checked against ${listNote}.` : ''}`)),

      alSection('Watchlist alerts'),
      h('details', { class: 'card al-types', open: S.watch.size > 0 && onCount < Rules.TYPES.length },
        h('summary', null, h('span', null, S.watch.size ? `${S.watch.size} stocks on your watchlist` : 'Your watchlist is empty'), h('span', { class: 'muted small' }, `${onCount} of ${Rules.TYPES.length} on`)),
        h('p', { class: 'muted small' }, S.watch.size ? 'Choose what to be told about. Tap the star next to a stock to add or remove it.' : 'Tap the star next to a stock to add it. These alerts only cover stocks on your watchlist.'),
        typeGroups.map((g) => h('div', { class: 'al-group' }, h('strong', null, g),
          Rules.TYPES.filter((t) => t.group === g).map((t) => switchEl(AL.prefs[t.key], t.label, (e) => { AL.prefs[t.key] = e.target.checked; savePrefs(); })))),
        h('div', { class: 'al-actions' }, h('button', { type: 'button', class: 'linkbtn', onclick: () => setAll(true) }, 'Turn all on'), h('button', { type: 'button', class: 'linkbtn', onclick: () => setAll(false) }, 'Turn all off'))),

      alSection('Settings'),
      backupCard(),

      alSection('Triggered alerts'),
      log.length ? [h('ul', { class: 'alertlog' }, log), h('div', { class: 'al-actions' }, h('button', { type: 'button', class: 'linkbtn danger', onclick: () => { AL.log = []; store.set('alertLog', []); render(); } }, 'Clear list'))]
        : h('p', { class: 'muted small' }, 'Nothing yet. Alerts will appear here as they happen.')));
  }

  function setupUpdateNotice() {
    if (!window.Updater || !(location.protocol === 'https:' || location.hostname === 'localhost')) return;
    try {         // an optional extra: whatever goes wrong here must never stop the app from starting
      window.Updater.watch({ serviceWorker: navigator.serviceWorker, document, bar: $('#update'), reload: $('#update-reload'), dismiss: $('#update-dismiss'),
        reloadPage: () => location.reload(), every: (fn, ms) => setInterval(fn, ms) });
    } catch (err) { /* no update notice */ }
  }

  /* Theme: follows the device until a person picks Light or Dark; the choice is kept on this device. */
  function setupTheme() {
    const button = $('#theme');
    const order = [null, 'light', 'dark'];
    const names = { null: 'follows the device', light: 'light', dark: 'dark' };
    const draw = (inner) => `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${inner}</svg>`;
    const ICONS = { system: draw('<circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor"/>'), light: draw('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'), dark: draw('<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5z"/>') };
    const apply = (value) => {
      if (value) document.documentElement.setAttribute('data-theme', value); else document.documentElement.removeAttribute('data-theme');
      button.setAttribute('aria-label', `Theme: ${names[value]}. Tap to change.`);
      button.title = `Theme: ${names[value]}`;
      button.innerHTML = ICONS[value || 'system'];
    };
    let current = store.get('theme', null);
    if (current !== 'light' && current !== 'dark') current = null;
    apply(current);
    button.addEventListener('click', () => {
      current = order[(order.indexOf(current) + 1) % order.length];
      store.set('theme', current); apply(current);
      toast(`Theme: ${names[current]}`);
    });
  }

  function setupNotifications() {
    const btn = $('#notify');
    const paint = () => { btn.setAttribute('aria-pressed', S.notify ? 'true' : 'false'); btn.textContent = S.notify ? 'Alerts on' : 'Alerts off'; };
    btn.addEventListener('click', async () => {
      if (S.notify) { S.notify = false; store.set('notify', false); paint(); return; }
      if ('Notification' in window && Notification.permission !== 'granted') {
        try { await Notification.requestPermission(); } catch (e) { /* ignore */ }
      }
      S.notify = true; store.set('notify', true); paint();
      toast('Alerts on for stocks in My watchlist while this page is open. For alerts when the app is closed, join the Telegram channel (link at the top of the page).');
    });
    paint();
  }

  function init() {
    for (const b of document.querySelectorAll('.tabs button, .bottomnav button')) b.addEventListener('click', () => { S.tab = b.dataset.tab; render(); $('#view').focus({ preventScroll: true }); });
    $('#refresh').addEventListener('click', () => load(true));
    const dlg = $('#detail');
    dlg.addEventListener('click', (e) => { if (e.target === dlg) closeDetail(); });
    dlg.addEventListener('close', () => { clearHash(); if (lastFocus && document.contains(lastFocus)) lastFocus.focus({ preventScroll: true }); });
    window.addEventListener('hashchange', openFromHash);
    setupNotifications();
    setupTheme();
    setupUpdateNotice();
    load(false);
    setInterval(() => { if (!document.hidden) load(false); }, REFRESH_MS);
    setInterval(updateHeader, 60 * 1000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) load(false); });
    if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === 'localhost')) {
      navigator.serviceWorker.register('sw.js').catch(() => { /* offline support is optional */ });
    }
  }

  init();
})();
