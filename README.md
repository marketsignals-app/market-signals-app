# Stock Signals

A free, installable web app that shows Buy / Hold / Sell signals for Indian (NSE) stocks,
with news, buying and selling pressure, dividends, risk, IPOs and a backtest for every stock.
It runs on GitHub only: GitHub Actions refreshes the data every 15 minutes, GitHub Pages hosts the site.

It is not investment advice. Signals come from fixed rules on free, delayed data and can be wrong.

## What updates by itself

| Feature | Source | Notes |
|---|---|---|
| Prices, signals, patterns, risk, backtest | Yahoo Finance (free), cross-checked against the NSE end-of-day file | Prices can be up to 15 minutes late. The cross-check covers completed sessions; see Price accuracy below |
| News | Google News | Shown as published, with source and age. No good-or-bad tone is worked out from the words. The stock comes first: a headline is attached to a stock only if it is clearly about the company: the full name, a ticker that is not an ordinary word, or a single name word together with business wording (shares, results, Q2, dividend). Stories about people or sports that share a name, rating headlines that name a bank only as the one giving the rating, lists and roundups, and headlines about more than one listed company are ignored. A headline is "fresh", and can be sent as an alert, for 6 hours |
| Buying / selling pressure | Volume (Chaikin Money Flow, up-volume share) | A proxy. The exchange order book is not published for free |
| NSE delivery % and bulk/block deals | NSE end-of-day files | India only, updated after each trading day |
| Upcoming events | Yahoo Finance calendar, plus estimates from each stock's own dividend history | Results dates, ex-dividend dates and dividend payment dates. Each is labelled "unconfirmed" (Yahoo's figure) or "estimated". Recent splits come from price history |
| Dividends | Actual payments from Yahoo | Frequency, amount, 12-month and recurring yield, specials, overdue payments |
| Fundamentals and peers | Yahoo quoteSummary | Refreshed once a day. Shows "unavailable" when missing |
| New listings | NSE equity list | Added to the "New listings" list on their own. Signals start after about 60 trading days |
| India IPOs | Investorgain's public IPO table (robots.txt allows it), read at most once an hour | Open, close, allotment and listing dates, price band, lot size, subscription, grey-market premium (GMP), estimated listing price and profit or loss per lot. Past IPOs show the actual listing price and gain |
| GMP cross-check | Google News headlines that name the IPO and quote a premium | Flags "news agrees" or "news differs". GMP is an unofficial rumour and can be wrong |
| Market conditions, breadth, sectors | Computed from the index (Nifty 50), its volatility index and the stocks in this app's list | Seven simple checks worth +1, 0 or -1 each, advancers and decliners, share of stocks above their 20/50/200-day averages, sector moves over 1, 5 and 20 days. Breadth and sectors cover this app's list, not the whole exchange |
| Lists | Computed daily | Government-backed, high dividend, low debt, low volatility, momentum, oversold, near 52-week high, near 52-week low, delivery buying, sectors |

## What is not automatic

* An unlisted company's financials are not published as data anywhere free, so scoring an IPO on profit,
  debt and valuation uses the optional "Check an IPO yourself" tool on the IPOs tab, where you type the
  figures. Everything else about Indian IPOs fills in on its own.
* The NSE blocks scripted access to its IPO data, and IPO Watch loads its table from a path its
  robots.txt disallows. This project does not try to get around either, so Investorgain is the only
  source for Indian IPO dates and GMP. If its page layout changes, the parser returns nothing instead of
  guessing and the app keeps showing the last good data with a warning.
* The US market: US stocks, the S&P 500 list, the US IPO calendar and the US close brief were removed. Global indexes (S&P 500, Nasdaq, US VIX, 10-year yield) are still shown as market context.
* Alerts when the app is closed need the optional Telegram setup (see Alerts below).

## Set it up (about 10 minutes)

1. Create a free GitHub account if you do not have one, then create a new **public** repository
   (public repositories get unlimited free Actions minutes; the site and its data will be public).
2. Upload everything in this folder to the repository's `main` branch.
3. In the repository: **Settings > Pages > Build and deployment > Source: GitHub Actions**.
4. Open the **Actions** tab, choose **Update signals**, and press **Run workflow**. The first run takes a few minutes.
5. Your site is at `https://<owner>.github.io/<repository-name>/`. This project's site is
   `https://marketsignals-app.github.io/market-signals-app/`.
   On your phone open it in Chrome or Safari and choose **Add to Home screen** to install it like an app.

The data is refreshed on a fixed beat by the **Refresh loop** workflow: every 10 minutes while the markets are open
(weekdays 03:00-20:59 UTC) and every hour otherwise. GitHub's own cron is best-effort and may never start a run, so the
loop starts "Update signals" itself and starts a fresh copy of itself before GitHub's 6-hour job limit. Start it once
with **Actions > Refresh loop > Run workflow** (pushing the file also starts it). To stop it, set the repository variable
`REFRESH_LOOP` to `off` (Settings > Secrets and variables > Actions > Variables) and cancel the running loop. A cron
line in each workflow is a backup that restarts the loop or asks for a refresh once an hour. The loop keeps one runner busy
most of the time, which public repositories get free; if you would rather not use it, set `REFRESH_LOOP` to `off` and
refresh by hand with **Actions > Update signals > Run workflow**. When the data is more than 45 minutes old on a market
day, the site shows a banner saying so.

## Alerts

`config/alerts.json` controls what is watched:

```json
{"symbols": ["*"], "news": true}
```

* `symbols`: `["*"]` watches every stock. Or list the ones you want, for example `["TCS.NS", "SBIN.NS", "AAPL"]`.
* `news`: `true` includes fresh headlines about the stock in the alerts, `false` leaves them out. Headlines are shown as
  published, with their source and a link to the article. The app never judges one as good or bad news.

An alert is raised when a watched stock's short- or long-term signal moves between buy, hold and sell, and when a
headline from the last 6 hours that is clearly about the company appears (at most one per stock and 6 per run). To stop a score that hovers at a threshold from sending a message
every run, a stock only moves into Buy or Sell at a score of +/-25 and only drops back once it falls through
+/-10. The move is measured from the side last announced, so a slow drift is still reported once it is clear.
The first run only records the current state and raises nothing. A busy run is sent as up to 3 messages, and anything
beyond them is counted, with all alerts listed on the Market tab.

### What an alert looks like

Each Telegram message is a short list of bulleted cards, readings first and headlines second. A reading card says what
changed, gives a resistance or support reference and a volatility risk level, lists the indicator readings behind it,
and links to the full analysis. A headline card shows the headline as published, its source and age, and links to the
article and to the stock's analysis:

```
📊 Market Signals · Mon 16 Nov, 09:38 IST
1 reading change · 1 headline

━━ READINGS ━━

🔴 Coal India (COALINDIA.NS)
Aligned bearish · Weeks view
• Change: Mixed → Aligned bearish (alignment -27)
• Price: ₹398.80
• Support reference: ₹364.95 (-8.5%, volatility-based, 2x the risk distance)
• Volatility risk level: ₹415.73 (+4.2%)
• Indicator readings:
   – Trend: price below 20-day average, 20-day below 50-day
   – Volume pressure: selling pressure over 20 days
• Open analysis: https://marketsignals-app.github.io/market-signals-app/#stock=COALINDIA.NS&section=signals

━━ NEWS ━━

📰 Berkshire Hathaway (BRK-B)
• Headline: Berkshire's Rails and Renewables Offset a Costlier GEICO as Buybacks Outrun Forecasts
• Source: ad-hoc-news.de · 64 min ago
• Read article: https://news.google.com/...
• Open analysis: https://marketsignals-app.github.io/market-signals-app/#stock=BRK-B&section=news

ℹ️ Levels are indicative, from fixed chart rules. Not advice.
Educational information only, not investment advice. We are not a SEBI-registered adviser or research analyst.
```

Alert links are built from the repository's owner and name on every run, so they follow the repository if it is
moved or renamed. Nothing in the code holds the address.

* **Volatility risk level:** 2 x the 14-day average true range from the price (below it for a bullish reading, above
  it for a bearish one). This distance is called R.
* **Short-term target:** the nearest resistance (buy) or support (sell) if it is 1 to 4 R away, otherwise 2 R.
* **Long-term target:** the 52-week high (buy) or low (sell) if it is at least 1 R away, otherwise 3 R.
* **Indicator readings:** the reasons on the stock's page that support the new signal. For a signal that has faded to hold, the
  reasons that weakened the old one, and no reference level is given.
* **News is separate from readings.** It never changes a reading and is never graded as good or bad. A headline is
  attached to a stock only when it is clearly about that stock (see the News row in the table above), and a headline about
  more than one company in the list is attached to none of them. The stock comes first and its news follows, never the
  other way round.

The reference levels come from fixed rules, are not forecasts, and prices can gap past the volatility risk level. Tapping the
link opens that stock's page on the site, with the alert at the top followed by the full analysis (signals,
chart, levels, risk, fundamentals, dividends, news and backtest). The Market tab lists recent alerts with a
"View analysis" button for each.

* **In the app:** the Alerts button turns on notifications for the stocks you starred, while the app is open.
  Recent alerts are listed on the Market tab.
* **Telegram channel (alerts on your phone with the app closed):** the site links to the channel
  (`https://t.me/marketsignalsapp`) from its header and footer. To make the refresh job post there:
  1. In Telegram, message `@BotFather`, send `/newbot` and follow the steps. Keep the token private.
  2. Add the bot to the channel as an **administrator** who can post messages.
  3. Find the channel's chat ID: post once in the channel, then open
     `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser (with your token) and note the number after
     `"chat":{"id":` (it starts with `-100`). For a public channel you can also use `@marketsignalsapp`.
  4. In the repository: **Settings > Secrets and variables > Actions > New repository secret**. Add
     `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
  5. Check it: **Actions > Update signals > Run workflow**, tick **Send a test message to Telegram first**, then run.

Delivery depends on the 15-minute schedule, and GitHub may delay scheduled runs. Anyone can join the public
channel and get the same alerts. Without Telegram nothing is sent outside the app: a web page cannot push
notifications to a closed browser without a push service or a server that stores each person's browser
address, and this project uses neither.

### Target-hit replies

Each bullish or bearish alert is recorded (price, reference level, volatility risk level). When a later price reaches
either level, the bot replies under the original Telegram message ("REFERENCE LEVEL REACHED" or "VOLATILITY RISK LEVEL REACHED") with a link to
the analysis. A call that simply runs out of time is recorded but not announced. If the original message was
deleted, the reply is still sent on its own. Each outcome is announced once.

## Alerts tab (personal, on the device)

The Alerts tab holds each person's own alerts. Nothing is sent to a server: the watchlist, switches and rules live in the browser (`localStorage`) and are checked in `site/rules.js` each time the data refreshes, while the app is open.

- **Watchlist alerts:** switches for a reading turning bullish or bearish, fresh news, ex-dividend and results dates coming up, split/bonus/rights/buyback, mergers, exchange restrictions, circuits, gaps/surges/crashes and 52-week highs and lows. They only cover stocks on My watchlist. The first check records what already exists, so nothing floods in.
- **My rules:** up to 20 rules of up to 6 conditions (AND or OR) over the whole market list (`index.json`) or the watchlist, a list or a sector. A rule alerts when a stock newly starts to match it. A live count shows how many stocks match, and how many could not be checked for lack of a value. Fields cover price and volume, value (P/E, P/B, PEG, EV/EBITDA, price to free cash flow, earnings yield, P/E against the sector median), quality (ROE, ROA, margins, an approximate ROCE), growth (3-year revenue, profit and EPS rates, operating profit change, years profit rose), cash and debt (cash flow over profit, free cash flow, debt to equity, debt over EBITDA, current ratio), technicals (RSI, averages, 50 against 200-day, MACD, ADX, pressure, six-month return against the index) and risk (beta, worst fall).
  - **Where the figures come from:** Yahoo fundamentals and the annual statements, worked out in `engine/ratios.py` (tested in `tests/test_ratios.py`). A rate needs both ends of the period and a positive start; a ratio needs a positive denominator; figures are combined only within one fiscal year. Yahoo supplies four annual figures, so 3 years is the longest growth period. Checked by hand against the reported figures for TCS (revenue growth, relative strength, beta).
  - **Banks and lenders** are flagged and skipped for debt, cash flow, margins, current ratio and EBITDA figures, which do not mean the same for them; the count says how many were skipped.
  - **Coverage:** these figures exist only for stocks analysed in depth. Any other stock is counted as "could not be checked", never guessed. Not available from free sources, so not offered: ROIC, interest coverage, cash conversion cycle, working capital efficiency, Piotroski score, share dilution, historical P/E comparison, promoter holding and pledge, governance and capital allocation scores.
- **Settings:** "Move settings to another device" makes a short text code (`SS1:...`) holding the watchlist, own lists, switches and rules. Copy it, or send it to your own Telegram (for example Saved Messages), and paste it into the app on the other device. There is no login, no account and no server; the code is built and read in the browser (`packSettings` and `unpackSettings` in `site/rules.js`, tested in `tests/rules.test.js`).
- **Contrast:** every text and background pair in both themes meets WCAG AA (4.5 to 1 for text), and form fields and switches use a stronger border colour (`--control-line`, at least 3 to 1) so they can be seen. Checked from the colour tokens and again on the rendered pages of all nine tabs in both themes; the page also had no sideways scroll and no cut-off controls at 320, 375, 414, 600, 768, 1024, 1440 and 1920 px. The stock popup (all five tabs), its help notes and the pop-up messages were checked at the same eight widths: each fits the screen, closes, and the messages sit above the phone's bottom bar.
- **"A new version is ready" bar:** when a new release of the app has been installed in the background, a slim teal bar at the very top says so and offers Reload (or a cross to dismiss until the next release). It is not shown on a first visit. The app also asks for a newer version when it returns to the foreground and every half hour, so an installed copy that stays open notices a release. The logic is in `site/updater.js` (tested in `tests/updater.test.js` with a fake service worker). It relies on `CACHE` in `site/sw.js` changing with every release, so raise that number whenever a file in `site/` changes.
- **Theme:** the sun/moon button in the header cycles Device setting, Light and Dark; the choice is kept on this device and applied before the page paints, so there is no flash.
- **Triggered:** the last 200 alerts, with the popup shown when "Alerts" at the top is on.
- Alerts do not arrive when the app is closed. Closed-app delivery stays with the Telegram channel, which cannot filter per person.
- Tests: `tests/rules.test.js` (run by `update.yml` with the IPO tests).

## Track record

Every call and its outcome is stored in plain files on a separate **`data`** branch of this repository (created on
the first run; your code on `main` is never touched). `calls-YYYY-MM.jsonl` holds calls and `outcomes-YYYY-MM.jsonl`
holds how they ended; lines are only ever added, and git history shows when each was written. The **Track record**
tab shows hit rates with confidence ranges, average return against the market index, results by score band, which
signal components were stronger on winners, and suggested improvements.

* It only **measures**. Suggestions are for you to read; nothing changes the signal rules automatically.
* Figures under 30 resolved calls are labelled unreliable. Past results do not predict future ones.
* Fills are assumed at the next bar's open; a bar that touches both stop and target counts as a stop.
* The repository must allow the workflow to write: **Settings > Actions > General > Workflow permissions > Read and write**.
  If the ledger cannot be saved, calls wait in the site's state and are saved on the next run.
* The data branch is public if the repository is public.

## Stock page: ranges and result cards

The top of a stock's page is three panels. **Reading and key figures** (the two views, how many checks point which way, market cap, P/E, dividend yield, ROE, beta, volatility) and **Where the price sits** (day range, 52-week range and three small tiles for resistance, support and the risk level) are side by side and always the same height, with less than about 25 px of unused space under either. **Results at a glance** runs across the full width. On a phone the panels stack with no frames and no headings, so the tab bar is on the first screen (about 680 px from the top at 375 px wide). The page top, its popups and its colours were checked at 320, 375, 414, 600, 700, 768, 1024, 1280, 1440, 1920 and 2560 px.

At the top of a stock's page: a **day range** bar (the newest candle: the day so far while the market is open, else the last session) and a **52-week range** bar, each with a marker at the price. Below them, up to five **result cards**: revenue, operating profit and net profit (change on the quarter before, and on a year earlier), the six-month return against the index, and the P/E against its sector's median. They come from the reported quarterly figures and the engine's own numbers; a card with no figure is not shown, and the colour only says up or down, never good or bad. The sector median needs at least four stocks with a positive P/E in the main list, so other stocks have no P/E card.

**Peer ratio table** (Fundamentals tab): this stock and its seven largest same-sector peers from the list, with market cap (Rs crore), P/E, P/B, ROE, an approximate ROCE, EV/EBITDA and debt to equity, and a **sector median** row over every stock of the sector in the list (at least three figures needed). The figures are the same ones the alert rules use. Banks and lenders show n/a for debt, EBITDA and ROCE, and a column that is n/a for every row is left out. Nothing is ranked or coloured as better or worse.

## Layout: glance first

Modelled on what Groww, Angel One, Upstox and INDmoney do on a phone:

* **Bottom navigation** on phones (Readings, Screens, IPOs, Market, Events, Record); the top tab row is used on larger screens.
* **Stock page**: a sticky bar with the price and day change, then a glance block: both readings with their bars, an
  overall line ("Both views aligned bullish", "The two views differ" and so on) with a bar showing how many of the fixed
  technical checks point up, down or neither, the 52-week range with a marker, key figures, and chips for the next event
  and fresh headlines. Below it are tabs: Overview, Technicals, Fundamentals, News & events, Backtest. Alert links open the
  right tab.
* **Price map**: resistance, support and the volatility risk level sit in one small table with the price and each level's
  distance from it, and the 52-week range bar is under it. There is no price chart; a static line added nothing the table
  does not say. The whole top of the page (readings, levels, key figures) fits in about one phone screen.
* **Track record**: one headline first. Until 30 readings have settled it says "Too early for a success rate" with a
  progress bar (the rate would be unreliable). After that it shows the success rate (the price reached the reference
  level before the risk level or the time limit), failure and expired shares in one bar, the average move, and a card
  per reading type. Open readings, alignment and market splits, and the glossary sit below or under "More detail".
* **Readings**: each market has a stacked bar (bullish, mixed, bearish) and the index's trend and day move.
* The labels stay neutral ("aligned bullish", "mixed", "aligned bearish") rather than buy, hold or sell, because the
  readings describe conditions and are not advice.

## Method checks (what was verified, and how)

These were checked on 2026-11-16 against independent calculations and sources. The numbers are in the tests, so they can be
repeated.

* **Missing volume is not zero.** Yahoo sometimes gives no volume for a day. That stays missing; a real zero stays zero. Any
  volume indicator (VWAP, Chaikin money flow, up-volume share, average volume, the volume spike rule) that would need a
  missing day gives no value, so a gap can never create a pressure reading. Each reading now carries a coverage figure (the
  share of its rule's weight that had data), a confidence of full, reduced or limited, and the parts that were missing.
* **Unfinished daily candles.** While a market is open Yahoo's newest daily bar is the day so far: the close is the live
  price, the range is the range so far and the volume is only what has traded. (Seen on 16 Nov 2026 at 10:34 UTC with Xetra and
  London open: SAP.DE's bar had volume 155,629 against 1.41 million the day before.) So the price shown stays live, but every
  indicator, level, backtest and track-record check uses completed candles, and the unfinished candle gets a separate
  "provisional" reading (volume left out) that is recalculated after the close. Yahoo's trading-period times in the chart
  metadata decide when a bar is still running, with 30 minutes of grace after the close.
* **Indicators.** SMA 20, 50, 200, EMA 12 and 26, RSI 14 (Wilder), MACD 12/26/9, ATR 14 (Wilder), 30-day annualised volatility,
  VWAP 20, Chaikin money flow 20, up-volume share, 126-day momentum and 252-session highs and lows were compared with pandas and
  numpy on the same 700-bar series: the largest relative difference was 9e-13 (EMA 26), most were below 1e-13. Nothing was
  rewritten. Fibonacci levels and support/resistance have worked examples in the tests.
* **Golden and death crosses are events.** "50-day crossed above the 200-day 9 sessions ago (golden cross)" appears only when
  the crossover happened in the last 20 sessions. A 50-day average that simply sits above the 200-day is described as
  "bullish alignment, no recent crossover". The score still follows the alignment.
* **Thresholds are unchanged** (Buy at +20, Strong Buy at +50, and the same on the sell side): there are no settled results yet
  to justify changing them, and they are never tuned to flatter the history.
* **Backtests** have a second set of figures: CAGR, Sortino, expectancy, gross against net return (cost drag), and buy-and-hold
  CAGR. Costs are now separate for entry and exit and include assumed taxes, fees and slippage (`engine/costs.py`,
  overridable in `config/costs.json`); an open position at the end is valued as if sold. The simulation was re-implemented
  independently and matched the engine to the last digit on 16 of 16 stock and rule pairs. The rule beat buy-and-hold over the
  whole period in only 3 of those 16, and the "recent 40%" is not an independent out-of-sample test (same history, same rules).
  Limits: prices exclude dividends, the stock list is today's (survivorship bias), no tax on gains.
* **Track record** counts only calls made under the current rule version (now v3). Older calls stay in the ledger unchanged and
  keep being resolved, but are not mixed into the success rate.

## Every-stock coverage, briefs and index alerts

* **Full analysis (readings, backtests):** the 200 Nifty 200 stocks (plus Groww) in `config/universe.json`. Refresh the list with
  `python tools/update_universe.py`; existing entries are never changed.
  **The list also updates itself:** once a day from 10:00 IST (`engine/universe_sync.py`) the app reads the NSE's Nifty 200 list and adds any
  stock it does not yet analyse (no cap), kept in the saved state, so `config/universe.json` is not rewritten. Nothing is ever removed.
  A failed or refused download is retried after an hour, never worked around.
* **Every other listed stock:** all ~2,170 other NSE equity-series stocks (`engine/wide.py`) get live quotes in
  batches of 100, factual **mover** alerts (a move of 8% or more, a volume surge of 3x average on a 2%+ move, a new 52-week high
  or low; liquid stocks). **Penny and small stocks are included** with higher bars (12%, or 5x volume on a 5%+ move, no 52-week alerts), an
  average-turnover floor so a handful of trades cannot raise an alert, a "small stock" label, and at most 3 of a run's mover alerts; their own headlines looked up **stock by stock** in a rotating slice of 50 per run (stocks that just moved
  first), so the list is covered every few hours. Deals and official event dates cover every NSE stock.
* **Every listed stock is in the table** (`engine/catalog.py`). The dashboard loads only `data.json` (the curated list) and a small `index.json`
  (one row per other stock: price, move, size, 52-week range and, once analysed, the two readings), and shows 150 rows at a time (sorting and
  filters cover every stock). A stock's full analysis is a separate file in `detail/NN.json` (64 shards), fetched only when the stock is opened.
  Each run analyses up to 60 stocks (never analysed first, most traded first, then the stalest), so the whole list is covered within hours of
  the first run and each stock is refreshed about once a day, which is how often completed daily candles change. Until a stock is analysed its
  row says "quote only" and opening it shows the quote. The previous shards are read back from the published site on every run.
  **Fast start:** `data.json` holds only a slim record for each main-list stock (readings, key figures, table columns); its older headlines, backtest
  detail, provisional reading and levels are in `detail/NN.json` with the rest and load when the stock is opened. That cut the first download from
  about 980 KB to about 230 KB compressed. The two files are requested at the same time. If a stock's full record cannot be loaded, its page shows the
  quote and says so.
  Nothing is left half-done for these stocks: the table says while the full list is loading, when it could not load (with a "Try again" button) and how
  many stocks are analysed so far; the Reading filter says how many rows it hides because they have no reading yet; an empty result offers "Clear
  filters"; a quote-only stock can be starred and opened on the NSE or Yahoo pages; "Near 52-week high/low" include every stock from its quote alone, and
  analysed stocks also join the other screens (Oversold, Low debt and so on); alert cards in Telegram link to the analysis of any listed stock. The NSE
  publishes no sector, so these stocks have no sector chip or peer group.
* **52-week lows** are their own alert category ("52-WEEK LOWS" in Telegram, at most 5 per run), separate from movers.
* **IPO watch:** every stock listed within the last 90 days has its listing-day high and low taken from its first daily candle. While its market is
  open, a price above that high sends an "IPO breakout" alert and a price below that low an "IPO breakdown" alert (once per stock per day, at most 5
  per run). They are statements of where the price is, not forecasts. The pre-open brief ends with a "Stock watch" line listing these stocks, their
  last price and listing-day range. IPO and grey-market pages (IPO GMP, price band, subscription status) never count as news for a listed stock, and a
  group company ("NTPC Green") is not matched to its parent ("NTPC").
* **Index alerts:** moves past 1, 2 and 3 percent, 52-week highs and lows, and volatility indexes past a level, for the main NSE indexes (while
  the market is open) and the global ones (once per session).
* **Briefs:** India pre-open (09:08 to 09:40 IST), post-close (16:00 to 19:30) and institutional flows (18:30 to 22:00), each sent once per day from the exchange's own figures. Not sent when the data is not there.
* **Short alert wording:** indicator lines are abbreviated (P>20D, 50D<200D, RSI 61 normal) with a key; the site keeps the full wording.
* **Survivorship bias:** still not resolved and never claimed to be. Free data has no delisted prices or point-in-time index membership. If
  you have such files, `tools/survivorship_probe.py` tests them with the same rules, apart from the published figures.

## Scheduled Telegram feeds

The combined digest is replaced by separate feeds, each on its own clock (`engine/feeds.py`, items in `engine/feed_items.py`, layout in `engine/digest_feeds.py`,
the run in `engine/feed_run.py`). Times are IST, weekdays. The app's own alert log is unchanged: it still records every event as it happens.

| Feed | Cadence | Window | Sent when |
|---|---|---|---|
| Indexes | 60 min | 09:15 to 15:30 | every slot while India is open (a table) |
| Commodities and currency | 2.5 hours | 09:00 to 23:30 | every slot, each figure with its data date and a STALE mark when older than 2 days |
| Sector growth | 90 min | 09:15 to 15:30 | every slot: strongest and weakest sectors of our list, with the stock count behind each |
| Movers | 30 min | market hours | only if new |
| Bullish and bearish readings | 15 min | market hours | only if new; a reading that reversed while waiting is dropped |
| Volatility breaches | at once | market hours | each breach is sent on its own at the next run (up to 5 per run; any more wait for a 15-minute batch): a stock of the main list whose move today is at least 2x its own 14-day average daily range (ATR), again at 3x; it replies under the stock's reading alert when that was announced within 45 days; stocks with untrusted data are skipped |
| Circuit hits | 15 min | market hours | only if new: stocks at their upper or lower circuit (NSE price-band feed, limit worked out from the previous close). Defaults: band of 5% or more and turnover of at least 1 crore today (`config/alerts.json` "circuits": `min_band`, `min_turnover_crore`) |
| Corporate actions | 15 min | 08:00 to 22:00 | only if new: mergers, demergers, schemes of arrangement, open offers, bonus, splits, buybacks, rights, record dates, trading suspensions and delistings, from official NSE and BSE announcements and the NSE corporate-actions list |
| Share actions coming up | daily 08:40 | | bonus, split, buyback, rights, merger, demerger and scheme with an ex or record date in the next 7 days |
| Surveillance and F&O ban | 60 min | 08:30 to 21:30 | only if new: additions to the NSE ASM and GSM lists and entries into the F&O ban (exits and removals are on the website) |
| Gaps at the open | 15 min | 09:20 to 10:05 | only if new: a main-list stock that opened 3% or more away from its previous close (needs Yahoo's open price) |
| IPO breakouts | 30 min | market hours | only if new (price crossing the listing-day high or low) |
| Block deals | 15 min | market hours | only if new |
| Bulk deals | daily | from 18:00 (retried for 4 hours until the NSE publishes them) | the day's largest, with the client as the NSE publishes it |
| Important filings | 15 min | 08:00 to 22:00 | official NSE and BSE filings with a rule-based impact of 70 or more, once each |
| Company headlines, Latest important news | off | | switched off on 24 Nov 2026: media headlines matched some stocks wrongly (name collisions). Telegram carries official NSE and BSE announcements instead; the site's News tab still lists media headlines. A feed can be switched back on with `"enabled": true` in `config/alerts.json` |
| Upcoming IPOs | daily 09:00 | | open now, closing today, opening within 7 days, listing within 3 days |
| Today's events | daily 08:30 | | confirmed results, ex-dates and the like |
| Weekly summary | Sunday 18:00 | | track record, learning outlook (still "no better than the base rate"), data health |

Alerts that carry numbers are short lists, not tables (a table wraps on a small phone): each stock is a numbered heading with a few bullets of figures (for example "Move: +2.2% · Price: 401.70"), then its own hashtags; the source and a one-line key follow each section. Indexes, commodities and sectors are one numbered line per row. Text alerts (filings, corporate actions, headlines) keep a numbered heading with sub-points. News links show as "Read article".

Movers are shown in two sections, rising and falling, and tagged `#Surge` at +10% or more and `#Crash` at -10% or less.

**Announcements tab (website).** A separate tab lists all of these events for the last 7 days, newest first, with filters by group and type, a search box and a main-list-only switch:
mergers and schemes, share actions, trading restrictions (suspension, delisting, F&O ban, ASM, GSM), circuits, gaps, surges and crashes. It reads its own file, `announcements.json`
(built by `engine/actions.py` and `engine/actions_run.py`), so `data.json` does not grow. Each row shows the source and time, and links to the official filing where there is one. The tab
lists the state of every source. What kind of announcement it is gets decided by the exchange's category, then by fixed phrases, so an unusual wording can be missed; circuits come from one NSE source.
The first run after this was added records what is already published and alerts nothing.

Sent at once, outside the schedule: urgent index and volatility alerts (an Indian index move of 2% or more, India VIX past 20 or 25; global indexes are no longer alerted), the existing pre-open and post-close
briefs, replies when a tracked call reaches its target or stop, and a change of the market-conditions label.

How the timing works: each feed's window is cut into slots from its start (a 40-minute feed that starts at 09:00 has slots at 09:00, 09:40, 10:20 and so on). The first run inside a
slot sends the feed once; a missed slot is not replayed after the next one begins. Runs happen about every 10 minutes and GitHub's scheduler is best-effort, so a feed arrives within
about 10 to 20 minutes of its slot, not on the exact minute. Which slot was last sent is kept in the sent-alert memory on the `data` branch, so a failed run cannot send a slot twice, and
a feed whose Telegram send failed keeps its items and is tried again. On the first run with this scheme nothing is sent: every feed starts with its next slot.

Message styles, so a message reads quickly: **A** a numbered heading with indented sub-points (readings, filings, volatility alert, IPOs, events, weekly summary); **B** one numbered
line per item with the figures inline (headlines, indexes, commodities, sectors); **C** a heading with bullets of figures (movers, circuits, deals, gaps, breaches, IPOs, target and stop replies). Every entry carries hashtags (the stock symbol such as
`#AXISBANK` or `#M_M`, the kind of alert, the sector) for searching in Telegram. Every snapshot names its source and time.

Change a cadence or window without code in `config/alerts.json`, for example `{"feeds": {"movers": {"every": 20}, "sectors": {"enabled": false}}}`. Set `"scheduled_feeds": false`
there to return to the single digest per run.

Operator messages (optional): add the secret `TELEGRAM_ADMIN_CHAT_ID` (a private chat with the bot) to get a message when a data source is degraded or stocks are paused, and when
a run fails (the failed run publishes nothing and the site stays on the last good build). These never go to the public channel.

## Alerts: fairness and block deals

See `docs/alerts-audit-2026-11-17.md`. A stock gets at most 2 headline alerts a day, repeated stories are skipped, and the stocks alerted
least go first, so heavily covered names cannot fill the channel. Block deals are announced from the NSE's live feed for any NSE stock,
tracked or not, as soon as they appear. Only the 122 tracked stocks (plus new listings) get readings and headlines.

## Verification tools and follow-up audit

Details and evidence: `docs/audit-followup-2026-11-16.md`.

* `python tools/verify_market_data.py --volume` checks the deployed prices (and NSE volumes) against the NSE end-of-day file, same session only. Not-yet-published references give UNVERIFIED, never a pass or a fail.
* `python tools/check_production.py --cache signals-v43` reads what the deployed site published (data freshness, the NSE feed
  as the Actions run saw it, stale handling, the service-worker cache name) and prints PASS, FAIL or UNVERIFIED for each. It cannot read
  the Actions logs, which need a login, so "error logged" stays UNVERIFIED unless you read the run log yourself.
* `python tools/strategy_report.py` measures the two rules against buy-and-hold (drawdown, downside deviation, Sharpe, Sortino,
  Calmar, exposure, holding period, bull/bear/sideways) for NSE stocks, with dividends included.
* Survivorship bias is not removed and is never claimed to be.
* Event dates: Indian dates are checked against the NSE's own announcement feeds (confirmed, different official date, or
  unverified with a link and the last check time).

## Events tab

The **Events** tab lists what is coming up for the stocks in this app: when results are expected, the ex-dividend date (buy
before it to receive the dividend), the dividend payment date, and splits or bonus issues when a prominent outlet has
reported them. The layout follows what established platforms do (Yahoo Finance's category tabs, Groww's
event cards):

* **One card per category**: Results, Dividend dates, Splits, bonus and other actions, and Announced in the news (no date
  stated). Each card shows its count and what is next, groups events by day, and shows the first 8 with "Show all".
* **Category chips with counts** at the top (a swipeable row on phones), plus search, market and "My watchlist only".
* Each event is a row with a date badge, what it is, and the key figure on the right (dividend per share, split ratio).
  Tap a row to open it: its sources (YAHOO, NEWS, ESTIMATED, AGREED), the news headline as evidence, and a button to the
  stock's page.
* It is built for phones first: one column, rows that are one large tap target, chips that scroll sideways, and two
  columns of cards only on wide screens.

Each stock's page also has an "Upcoming events" section and lists any splits of the last three years.

* **Where the dates come from.** Results, ex-dividend and payment dates come from Yahoo Finance (taken from the same request
  that fetches fundamentals, so no extra calls). They can be estimates, mostly for Indian companies, so they are labelled
  **unconfirmed**: the company confirms its dates by notice to the exchange. When Yahoo has no future ex-dividend date, one
  is **estimated**: the same week a year after an earlier payment, or the usual gap between payments for a newer payer.
* **How good the estimates are.** Wherever Yahoo does give a real date, the estimate is worked out as if it were unknown and
  compared with it. The tab shows the result (at the first live run: median error 1 day, 70% within a week, on 10 stocks).
  Some estimates are weeks off, so they are a rough guide.
* **When no official source can be read: the company's announcements as reported by prominent outlets.** The NSE and
  BSE do not allow free scripted access to their corporate-action lists, and this project does not try to get around
  that. Instead, news headlines about each stock are searched once a day (a batch per run, gently) for the company's own
  announcements: an ex-dividend or record date, a payment date, a results or board-meeting date, a stock split or bonus
  issue with its ratio, or an announced dividend amount. This is deliberately strict and shows its evidence:
  * only headlines from a list of prominent outlets are used (CNBC TV18, The Economic Times, Business Standard, Mint,
    Moneycontrol, Financial Express, NDTV Profit, Reuters, Bloomberg, Yahoo Finance and similar);
  * the headline must be clearly about that one company, must use a precise phrase ("stock split", "ex-dividend",
    "record date", "bonus issue", "results on"; the words "split" and "bonus" alone are not enough), and must state a
    date, ratio or amount itself. Nothing is guessed from tone;
  * a "this week" range from a roundup of record dates ("Nov 16-20: Cochin Shipyard, PFC...") counts too, when the
    outlet names the company;
  * each event shows its headline, source and link. Where Yahoo and a headline give the same date (or Yahoo's date falls
    inside a roundup's range) the event is marked **agreed**. A headline with no date is listed separately as
    "announced, date not stated".
* **Checked against CNBC TV18.** On 16 Nov 2026 the app's dates were compared with CNBC TV18's "Record Dates This Week"
  article. Of its 10 named stocks only 2 are in this app's stock list (EAAA Alternatives and PFC), and both dates matched.
  The article also showed that Yahoo's dividend amount is not the announced one (PFC: Rs 4.10 announced), so the app says
  "latest regular payment" and shows the announced amount only when a headline states it. The app lists only the stocks
  in `config/universe.json`.
* **Limits.** Headlines state few dates, so most stocks have no news-based event, and the page says how often news and
  Yahoo agree. Past splits come from price history.
* Only dates from today onwards are shown, within 120 days (estimates within 75).

## Price accuracy

Yahoo is the main price source, so the build checks it against an independent one on every run: the **NSE's official
end-of-day file** (the exchange's own closing price). The closing prices of the last completed sessions are compared date by date. Within 0.5% is a match, 0.5% to 2% a
small difference, and more than 2% a disagreement. A stock whose prices disagree gets a warning on its page and **no new
alerts** until the sources agree again. The Market tab shows the result for each source: stocks checked, how many match,
median and largest difference, and the latest session compared.

* This verifies completed sessions. The live price during the session comes from Yahoo alone: the NSE blocks scripted
  access to live prices, and no other free source offers them.
* A price feed that ends a session before the NSE file (the file has a newer date than Yahoo's series) is marked **behind**: it gets no new
  alerts and no tracked readings until it catches up. A clock check does the same when the feed lacks the session that must be complete by now
  (Yahoo's daily series was seen to miss the just-finished session from midnight IST until about 08:30 IST). The NSE file history is
  topped up with the newest sessions on every run (it was once frozen on the day it first filled, which hid this).

## Feature map and data provenance

| Capability | Where | Status |
|---|---|---|
| Daily OHLCV | Yahoo daily bars (5 years) feed every indicator, backtest and level; cross-checked against the NSE end-of-day file | Yes. The bars are used, not republished |
| Historical financial statements | `engine/statements.py`: quarterly (8) and yearly (6) revenue, operating income, EBITDA, net income, diluted EPS, plus yearly equity, debt and cash flow, from Yahoo's fundamentals time series | Yes, shown on the Fundamentals tab of a stock |
| Automatic quarterly results ingestion | The same module reads statements a few stocks per run: never read -> now; newest quarter older than 100 days (results due) -> every 2 days; otherwise weekly. A failed read keeps the earlier figures | Yes (curated stocks every run, the others as they are analysed) |
| Technical indicators | `engine/signals.py`; checked against independent code and TA-Lib | Yes |
| Fundamental quality and valuation score | Fixed bands on profit margin, revenue growth, debt, return on equity and P/E against the sector median (`site/ipo.js`), on every stock's Fundamentals tab | Yes, worded as "Stronger / Mixed / Weaker fundamentals" |
| Breakout and momentum scanners | Lists "Breakouts" (closed above the 20-day high), "Momentum leaders", "Near 52-week high/low", "Oversold", pattern and technical filters | Yes |
| Combined ranking engine | Stock screens: goal, horizon (short, long or both), risk, market -> ranked stocks from readings, fundamentals, dividends, volatility | Yes |
| Dashboard, alerts, historical performance | Signals, Market (alerts, data status, price accuracy), Track record, evidence strip | Yes |

**Horizon:** Short-term (weeks view), Long-term (months-to-years view) or Both. With Both the table shows both readings; a stock counts as
bullish or bearish only when the two views agree, anything else is mixed, and the score is the average. The screens blend 50/50.

**Source, timestamp and freshness on every figure.** Each full stock record carries `provenance` (`engine/provenance.py`): per group of figures
(price, indicators, closing-price cross-check, live cross-check, fundamentals, statements, dividends, headlines) the source, the data date, the
time it was read, its age and a state: current, ageing, not current, verified, disputed, not cross-checked or unknown. The stock page shows it as
"Data sources and freshness". `provenance_ok` is false when the price or indicators are not current (the series lacks the session that must be
complete by now, or the NSE file or live snapshot disputes it); the table then says "data not current" and no alert or tracked reading is made on that
stock. Fundamentals carry the period they describe (`most_recent_quarter`) as well as when they were read.

## News intelligence and sentiment

The **News** tab (and the News card on every stock) reads official announcements and headlines, de-duplicates them, scores them, and compares them with the
price, volume and sector. The reliable parts are the headlines, their sources and times, official filings and the event type (from the exchange's own category). The tone score
and the market tone are **experimental** (a word list, not validated) and are shown on the website only, marked as such: they are not part of any reading, any Telegram alert or the
track record. A reading comes from price and volume rules alone.

| Source | What it gives | Notes |
|---|---|---|
| NSE corporate announcements (`engine/news_sources.py`) | Official filings with the exchange's own category, for the whole market | One request per run for two days. The NSE RSS file was empty when tested, so the same announcements come from the NSE API |
| BSE corporate announcements | Official filings from BSE's public RSS file | Mapped to the NSE symbol by company name; BSE-only companies are not tracked. `api.bseindia.com` refuses scripts (403) and is not used |
| Business Standard, Mint, The Economic Times, Moneycontrol, The Hindu BusinessLine | Headlines and links from their public RSS feeds | Headlines only, attributed to the outlet, linked to the original |
| Google News per company | Headlines about each tracked company | Already used for alerts |
| NewsData.io (optional) | Business news for India | Off unless the secret `NEWSDATA_API_KEY` exists. Free plan: 200 credits a day, 12 hours delayed, "for testing & personal projects"; its terms limit use to "personal or internal business purposes" and require "Powered by NewsData.io API" attribution. Using it on a public site may exceed that licence, so decide before adding the key. Untested without a key |
| Hypeless | Not found as a news provider, so not integrated | |

How a story is scored (`engine/news_intel.py`, rules, no language model): the exchange's category or a keyword classifier gives the **event type** (results,
order win, regulatory action, management change and so on); a financial word list with negation gives the **sentiment** from -100 to +100; the **source
credibility** comes from a tier table (the exchange 95, established outlets 82, recognised 66, unknown 45, minus 25 for rumour wording, plus 8 when a second
source confirms it); the **impact** (0 to 100) is the event's materiality times credibility, relevance and recency (half-life 36 hours). **Duplicates**: near-identical
headlines (word overlap of 55% or more) and the same official filing posted on both exchanges count as one story; the other sources are listed and the repeat count is shown.
Per stock: overall sentiment (impact-weighted), impact, fundamental impact, interpretation (Bullish, Bearish, Neutral or Mixed; held at Neutral when the average credibility
is low), short and long-term implications, key risks, the market reaction (price move, volume against its 20-day average, the sector's move) and how it compares with the reading.

Each provider runs in isolation: one being down never stops the others, a refusal (401, 403, 429) pauses only that provider, and the last 96 hours of mapped items
are kept in `state.json`, so recent stories survive an outage. Every story keeps its headline, source, timestamp and a link to the original.

**Optional language-model scoring.** GitHub Pages only serves static files, so a model cannot run on the site. A separate scheduled job
(`.github/workflows/news-ai.yml`, `engine/news_ai.py`, `engine/ai_sentiment.py`) asks a hosted model (GitHub Models, the free rate-limited tier, with the job's own
`GITHUB_TOKEN` and the permission `models: read`; model name in the repository variable `NEWS_AI_MODEL`, default `openai/gpt-4o-mini`) about new headlines only, in batches of 25, and
stores each answer under a hash of the headline on the `data` branch. The 10-minute build reads those scores in **shadow mode** (`ai_sentiment.AI_WEIGHT = 0`): the model's score is shown beside the rule-based one ("AI view +55") and
compared with it (direction agreement and mean difference, on the News tab), but it changes no sentiment, reading or alert. It may be given a weight only after a labelled test shows it helps;
agreement between the two is not accuracy. Each run writes `news-ai/status.json` (what was read, how many scored, the stop reason), which the News tab shows, so the reason for "no AI scores" is
visible without opening the job log. If the model is unavailable, over its limit or answers badly, the rule-based score stands alone. Headlines are untrusted input (the prompt treats them as data and only numbers and labels
from fixed sets are accepted), nothing but the headline text is sent, and no key is stored. The endpoint, limits and permission could not be exercised from the development machine:
check the first run's log. Turn it off with the repository variable `NEWS_AI` = `off`.

## News tone and the data learning loop

**Rough news tone (experimental, website only).** `engine/sentiment.py` scores a headline from -1 to +1 with a financial word list (negation, phrases with the longest
phrase winning, intensity words). It feeds the rough-tone figures on the News tab, the stock page and the readings table, each labelled experimental. It was part of the short-term
reading (5 points) until 23 Nov 2026 and was removed because it had never been tested against labelled headlines; an example the Telegram digest exposed was "retreat sharply from record
highs" scoring positive (fixed, but the list is still a list). A word list reads words, not meaning. Telegram carries no tone at all and no media headlines (those feeds are off); filings show their importance, not a tone. Headlines are shown exactly as
published. A trained or pretrained model would need a labelled test set first (see the Learning section).

**Data learning loop** (`engine/data_learning.py`, state kept in `state.json`). Every run records which stocks had data incidents (a series missing the
newest session, a feed behind the NSE file, a price the NSE file or live snapshot disputes, a stale input, a carried record) and whether each source
worked (Yahoo charts, the NSE end-of-day file, the NSE live snapshot, Yahoo fundamentals, headline search, the learned table, block deals, official
events). A stock with incidents in 3 of its last 6 runs is paused (no alerts, no tracked readings) until it has been clean for 3 runs; each source's
reliability over its last 24 runs is shown, and the hours of the Indian day in which many stocks lag are learned. The Market tab shows it as "Data health".
It never changes a reading, a score or a threshold.

## Learning from the past: the outlook

A weekly job (`.github/workflows/learn.yml`, `engine/learn.py`, `engine/learning.py`) reads five years of prices for the tracked NSE stocks and learns,
for each combination of **current factors** (trend against the 50 and 200-day averages, RSI zone, MACD direction, position in the 52-week range,
volatility), how often the price was higher 5, 20 and 60 trading days later in **past** situations with the same factors. Each stock page shows its
factors and that frequency with a range ("Outlook from the past"). The table is published on the `data` branch and read by the 10-minute build.

What keeps it honest:
* A combination seen fewer than 150 times falls back to a coarser one, down to the all-situations share.
* The range resamples whole trading dates, because stocks move together on a day.
* It is tested on later data: built on the earlier 60% of dates, scored (Brier error against always saying the all-situations share) on the later 40%.
  It is called an edge only if it did better by at least 1% of the error with the whole range above zero.
* Each week's forecasts are logged on the `data` branch (append-only) and scored when their date passes; the Track record tab shows the live error
  and how often each probability band came true.
* Nothing learned here changes a reading, a threshold or an alert, and nothing is tuned to beat buy-and-hold.

**Result on 200 NSE stocks, 2021-11 to 2026-11:** none of the three horizons beat the all-situations share on later data (skill -0.3%, -0.7%,
-1.2%). The price factors in this app do not predict direction better than the base rate, so the outlook is context, not a forecast, and the page says
so. Limits: past fundamentals are not available point in time (only price and volume factors are learned), prices exclude costs and dividends, the
stock list is today's (survivorship bias), and the 2021 to 2026 period was a rising market (59% of 60-day windows ended higher).

## Second sources for prices and indicators

| What | First source | Second source | Result when last tested |
|---|---|---|---|
| Completed-session close (EOD analysis) | Yahoo daily bars | NSE UDiFF end-of-day file (about 16:30 IST), with the full bhavcopy as fallback (about 23:55 IST, also carries delivery data) | Closes and volumes identical to Yahoo on 75 stock-sessions; the two NSE files agree on 13,782 rows |
| Live price (biggest movers) | Yahoo | NSE live snapshot (`engine/nse_live.py`): the NSE's own gainers and losers lists, about 150 stocks per run, two requests | 30 stocks on 2026-11-20 about 14:50 IST: median difference 0.05%, largest 0.48% |
| Technical indicators | `engine/signals.py` | `tools/verify_indicators.py` (independent code) and `tools/verify_talib.py` (TA-Lib) | SMA, RSI, MACD, ATR agree with TA-Lib to about 1e-13 on 15 stocks |
| Fundamentals and dividends | Yahoo | none: NSE and BSE data APIs refuse scripts and no free official source was found for Indian fundamentals | Shown as Yahoo reports them, never described as verified |

A live price more than 3% away from the NSE snapshot gets no mover alert and no new alert on that stock; 1% to 3% is shown as a small difference.
The snapshot lists only the biggest movers, so most stocks have no live check and show none. `engine/nse_live.py` pauses itself after a refusal
(HTTP 401 or 403) and never works around it. Libraries such as pandas, NumPy, VectorBT and Backtesting.py are not used by the app (it runs on
the Python standard library); TA-Lib is a development check only.

## Market tab and data status

The Market tab shows market conditions for India (seven plain checks on the main index: price against
its 20 and 50-day averages, the 50 against the 200-day average, the 20-day move, trend strength (ADX), breadth and the
volatility index), index cards with a 30-day line, breadth, sector moves, alerts and world headlines. These describe how
the market is behaving now. They are not forecasts and not calls on any stock. Each block carries a small source tag:
**DELAYED** (free data, up to about 15 minutes late), **DERIVED** (worked out by this app from its own stock list) or
**EXTERNAL** (headlines from outside sources, not checked).

At the bottom is a **Data status** panel. Every refresh checks that prices, news, index data, market conditions, NSE
delivery data, India IPOs and the track record loaded, and says which did not. The index and volatility symbols used for
market conditions are set under `regime` in `config/universe.json`.

## Change the stock list

Edit `config/universe.json`. Each stock is `[symbol, name, market, sector, tags]`. Indian symbols end in
`.NS`. Use the tag `psu` for government-backed companies. Keep the name close to how news writes it, because
headlines must name the company to count.

## Run and test locally

```bash
python -m unittest discover -s tests -t .
node --test tests/ipo.test.js
python -m engine.build --out site --limit 14
python -m http.server 8765 --directory site
```

Then open http://127.0.0.1:8765/. Python 3.10+ and Node 18+ are the only requirements; there are no packages to install.

## How the signals work

* **Short-term (weeks):** trend (20/50-day averages), MACD, RSI, volume and volume pressure. News is not part of it.
* **Smooth scoring:** every part of a score changes gradually with the price (for example 5% above or below the 200-day
  average counts as the full +1 or -1). A stock sitting on an average therefore scores near zero and its reading cannot flip
  between two extremes when the price ticks across the line.
* **Long-term (months to years):** price against the 200-day average, golden/death cross, 6-month return, 52-week position and volatility.
* **Evidence beside every reading** (`engine/evidence.py`): a reading is how indicators line up today, not a recommendation, so the page shows what the same fixed rule did
  in the past test. A strip above the table gives, per market and view, on how many stocks the rule beat buy-and-hold (currently 14% of 200 NSE stocks for the weeks
  view and 20% for the months-to-years view, with median returns) and the live track-record count; a ▽ in the table marks a stock where the rule lagged holding; the
  stock page and Telegram reading alerts carry that stock's own result. Stocks with small turnover are tagged "Thinly traded" and ones with under a year of prices are
  tagged too. The test uses today's stock list, so it is not free of survivorship bias.
* **Checked against the live channel:** the mover, IPO-level, 52-week and index numbers in sampled Telegram messages were compared with Yahoo's day range and prices
  (33 of 33 price cards inside the day's range, index levels and percentages equal). The sample found and fixed: IPO breakouts repeated all day (now only the crossing of the
  listing-day high or low), 52-week alerts for stocks listed under a year ago, auto-generated "Investor Analysis | StockIQ" pages and look-alike companies
  (NLC India Renewables, Raymond James) shown as news.
* **Three small files instead of one big one:** `data.json` (the main list, slim records), `index.json` (one compact row per other stock) and
  `index_extra.json` (their indicator values, patterns, pressure and fundamentals), which the page fetches only when a technical filter, the technical panel
  or a column view other than Overview is used. Export CSV waits for it so the export is complete. A stock the quote request did not return in a run keeps its
  previous row, so a Yahoo outage never empties the table.
* **Release checks:** `docs/release-checklist.md` lists every check to do before a push, and `python tools/qa_sweep.py <build folder>` runs the data and file
  ones (unique symbols, readings equal in every file, plausible ratios, dividend sums, size budgets) and exits 1 on a failure.
* **Which stocks are covered:** every stock on the NSE main board (EQ series, plus the BE and BZ series, many of them penny stocks, shown with their series), the
  NSE SME platform (Emerge), as long as Yahoo has a quote for it (about 2,400 in all). Companies listed only on the BSE are not covered: the BSE
  publishes no list the app can read, so there is nothing to build the list from. A search that finds nothing says so.
* **The chip counts match the table:** a count on a category or sector chip is the number of stocks you would see if you picked it, with the market, Reading,
  technical filters and search that are on already applied. A "Filters on:" row above the table lists every filter that is on (market, Reading, search,
  each technical filter), each with a ✕ to remove it. Filters are remembered in the browser, so one set last time still applies when you come back.
* **Layout of the Signals page:** on a screen 1100 px wide or more, the categories (lists and screens) are a column on the left of the table and the sectors
  a column on the right, both staying in view as you scroll. On a phone or small
  window they are the two horizontal strips above the table, as before.
* **Technical filters** (a panel under the list chips on the Signals page, working on every listed stock that has been analysed): RSI (oversold, neutral,
  overbought), price above or below the 20, 50 and 200-day averages, MACD above or below its signal line, 6-month return, position in the 52-week range
  (top 10%, middle, bottom 10%), buying or selling pressure, daily swing (ATR as a percent of price) and any pattern on the latest candles (any bullish, any
  bearish, or one of 26 named ones). Every filter that is set must be true, they combine with the lists, sectors, Reading filter and search, and the header
  says how many stocks are hidden because they have no technical data yet. Each is a plain statement about the indicator values, not a recommendation.
* **Search is a "like" match, not an exact one:** case, punctuation and word order do not matter ("bajaj auto", "auto bajaj", "bajaj-auto"), a word can be
  typed in part ("hdfc ba"), "&" and "and" are the same ("m&m"), and each word matches the start of a name or symbol word, or sits inside the name
  (3 letters or more). A symbol is only matched from its start, so "tcs" finds TCS and nothing that merely contains those letters. With the default order,
  the best matches come first (the symbol or whole name, then names that start with it). If nothing matches, close matches are shown (one or two letters
  wrong: "relaince" finds Reliance) and the page says so.
* **Sorting:** click any table header on the Signals page to sort by that column (numbers largest first, text A to Z); click again to reverse. Rows with no value always go last.
* **Fundamentals** (from Yahoo Finance, last twelve months, shown as reported, never estimated, no rating made from them): market cap, enterprise value,
  P/E, forward P/E, PEG, P/B, P/S, EV/EBITDA, EV/revenue, revenue, EBITDA and its margin, operating, gross and profit margins, EPS, revenue and earnings
  growth, ROE, ROA, debt/equity, total debt, cash, current ratio, free and operating cash flow, book value per share, dividend yield and payout ratio.
  Main-list stocks get them from one request each, once a day. Every other listed stock gets P/E, forward P/E, P/B, EPS, book value and dividend yield
  from the bulk quote at no extra cost, and the rest (EBITDA, margins, cash flow and so on) as it is analysed in turn; an older record is analysed again
  when the fields were added. The Valuation table view shows them, and every column sorts.
* **Chart patterns** (shown on the stock page, not part of the score): fixed rules on the latest completed candles. Candle shapes: doji, hammer,
  shooting star, bullish/bearish engulfing, morning/evening star, three white soldiers/black crows, bullish/bearish harami, inside day.
  Price structure: golden/death cross (last 10 days), MACD cross (last 3 days), 20-day breakout/breakdown, within 3% of the 52-week high or low,
  gap up/down (opened 1% or more past the previous day's range), tight range (20 days inside a range under 10% wide), four days of higher or lower
  highs and lows. Volume: a surge of 2x the 20-day average on a 2%+ move (skipped when volume is not reported). Each is a description of what the
  candles did, tagged bullish, bearish or neutral by its rule, not a forecast. Many stocks have no pattern on a given day, and the page says so.
* Each score runs from -100 to +100: +20 or more is Buy, -20 or less is Sell, and +/-50 is Strong.
* **Backtest:** the same fixed rules are run on up to 5 years of each stock, trading at the next open with a 0.1% cost per trade, and compared with buy-and-hold. The most recent 40% is reported separately. In strong bull markets the rules often lag buy-and-hold, and the app says so.
* **Volatility risk level:** 2 x the 14-day average true range below the price. Prices can gap past it.

Never invest money you cannot afford to lose.

### Stale prices and the track record
A call is only recorded when its reference price traded on the day of the alert. Two guards: a price series that ends before the day of its own last trade is fetched again and, if it still lags, no call is recorded at that price (`series_lag`); and any call whose price never traded on its alert day is settled as "void" (not entered), not as a failure. The v3 results (9 of 20 stops and 1 target on stale prices) are kept in the record but not counted.
