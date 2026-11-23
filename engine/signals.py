"""Rule-based Buy/Hold/Sell scores.

Each component scores between -1 (bearish) and +1 (bullish). The final score is the
weighted average of the components that have data, scaled to -100..+100.
The rules are fixed. Nothing is fitted to the history, so the backtest is honest.
"""
from . import indicators as ta

SHORT_WEIGHTS = {"trend": 30, "macd": 25, "rsi": 20, "volume": 5, "pressure": 15}
LONG_WEIGHTS = {"trend200": 35, "cross": 25, "momentum": 20, "position": 10, "volatility": 10}

BUY, SELL = 20, -20
STRONG = 50


# Components change smoothly with the price, never in hard steps: a stock sitting on its 200-day average must score
# close to zero, not flip between two readings 70 points apart every time the price ticks across the line.
TREND_LONG_SCALE = 0.05    # 5% above or below the 200-day average (or 50 vs 200) counts as the full +1 or -1
TREND_SHORT_SCALE = 0.02   # 2% for the 20-day average and for 20 vs 50
MACD_SCALE = 0.004         # a MACD histogram of 0.4% of the price counts as the full +-1
LEVEL_BAND = 0.005         # within 0.5% of an average the wording says "about level with"
CROSS_WINDOW = 20          # a 50/200-day crossover counts as a recent event for this many sessions
FULL_COVERAGE = 0.99       # the share of the rule's weight that had data, at or above which confidence is "full"
REDUCED_COVERAGE = 0.75   # below this the reading rests on too little of its rule: "limited"


def _side(gap):
    return "about level with" if abs(gap) < LEVEL_BAND else "above" if gap > 0 else "below"


def _relation(subject, gap, other):
    return f"{subject} {_side(gap)} {other}"


def clamp(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


def label(score):
    if score is None:
        return "N/A"
    if score >= STRONG:
        return "Strong Buy"
    if score >= BUY:
        return "Buy"
    if score <= -STRONG:
        return "Strong Sell"
    if score <= SELL:
        return "Sell"
    return "Hold"


def build_indicators(bars):
    close, high, low, volume = bars["c"], bars["h"], bars["l"], bars["v"]
    macd_line, macd_signal, macd_hist = ta.macd(close)
    n = len(close)
    momentum = [None] * n
    for i in range(126, n):
        momentum[i] = close[i] / close[i - 126] - 1
    hi252 = [None] * n
    lo252 = [None] * n
    for i in range(251, n):
        hi252[i] = max(high[i - 251:i + 1])
        lo252[i] = min(low[i - 251:i + 1])
    return {
        "sma20": ta.sma(close, 20),
        "sma50": ta.sma(close, 50),
        "sma200": ta.sma(close, 200),
        "rsi": ta.rsi(close, 14),
        "macd": macd_line,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,
        "atr": ta.atr(high, low, close, 14),
        "vol30": ta.rolling_vol(close, 30),
        "vwap20": ta.rolling_vwap(high, low, close, volume, 20),
        "avg_volume20": ta.sma_complete(volume, 20),
        "cmf20": ta.chaikin_money_flow(high, low, close, volume, 20),
        "upvol20": ta.up_volume_share(close, volume, 20),
        "momentum126": momentum,
        "hi252": hi252,
        "lo252": lo252,
        "bars": bars,
    }


def _combine_detail(components, weights, min_weight_share=0.5, optional=()):
    """components: {name: (value, text) or None}.

    Returns {"score", "reasons", "coverage", "missing"}. coverage is the share of the rule's total weight that had data;
    missing lists the components that could not be worked out. score is None when too little had data."""
    used = {k: v for k, v in components.items() if v is not None}
    missing = [k for k in weights if k not in used and k not in optional]
    total = sum(weights[k] for k in used)
    base = sum(w for k, w in weights.items() if k not in optional)           # an optional part (news) neither counts toward coverage nor lowers it when absent
    coverage = sum(weights[k] for k in used if k not in optional) / base
    if coverage < min_weight_share:
        return {"score": None, "reasons": [], "coverage": round(coverage, 2), "missing": missing}
    score = sum(weights[k] * used[k][0] for k in used) / total * 100
    reasons = []
    for k, (value, text) in used.items():
        tone = "pos" if value > 0.15 else "neg" if value < -0.15 else "neutral"
        # key and value let the track record measure which components actually help
        reasons.append({"text": text, "tone": tone, "key": k, "value": round(value, 2)})
    return {"score": round(score), "reasons": reasons, "coverage": round(coverage, 2), "missing": missing}


def _combine(components, weights, min_weight_share=0.5):
    """components: {name: (value, text) or None}. Returns (score, reasons) or (None, [])."""
    detail = _combine_detail(components, weights, min_weight_share)
    return detail["score"], detail["reasons"]


def confidence(coverage):
    """How complete the data behind a reading was: full, reduced or limited."""
    if coverage is None:
        return None
    return "full" if coverage >= FULL_COVERAGE else "reduced" if coverage >= REDUCED_COVERAGE else "limited"


def recent_cross(ind, i, window=CROSS_WINDOW):
    """The latest 50/200-day crossover in the last `window` sessions: ("golden" | "death", sessions_ago) or None.

    A crossover is an event: the 50-day average moved from one side of the 200-day average to the other. A stock whose
    50-day average simply sits above the 200-day has bullish alignment but no recent golden cross."""
    s50, s200 = ind["sma50"], ind["sma200"]
    for j in range(i, max(0, i - window), -1):
        now, before = (s50[j], s200[j]), (s50[j - 1], s200[j - 1])
        if None in now or None in before:
            continue
        gap_now, gap_before = now[0] - now[1], before[0] - before[1]
        if gap_before <= 0 < gap_now:
            return "golden", i - j
        if gap_before >= 0 > gap_now:
            return "death", i - j
    return None


def buy_sell_pressure(ind, i):
    """Volume-based buying or selling pressure. Returns None when volume data is missing."""
    cmf, share = ind["cmf20"][i], ind["upvol20"][i]
    if cmf is None or share is None:
        return None
    value = (clamp(cmf / 0.25) + clamp((share - 0.5) / 0.2)) / 2
    name = "Buying pressure" if value > 0.15 else "Selling pressure" if value < -0.15 else "Balanced"
    return {"value": value, "label": name, "money_flow": cmf, "up_volume_share": share}


def short_detail(ind, i):
    """Swing view (days to weeks): price, volume and indicators, plus news tone when given (news = (value from -1 to +1, text) from engine/sentiment.py)."""
    bars = ind["bars"]
    close, volume = bars["c"], bars["v"]
    c = {}

    sma20, sma50 = ind["sma20"][i], ind["sma50"][i]
    if sma20 is not None and sma50 is not None:
        gap_price, gap_average = close[i] / sma20 - 1, sma20 / sma50 - 1
        value = 0.5 * clamp(gap_price / TREND_SHORT_SCALE) + 0.5 * clamp(gap_average / TREND_SHORT_SCALE)
        parts = [_relation("price", gap_price, "20-day average"), _relation("20-day", gap_average, "50-day")]
        c["trend"] = (value, "Trend: " + ", ".join(parts))

    hist, prev_hist = ind["macd_hist"][i], ind["macd_hist"][i - 1] if i > 0 else None
    if hist is not None and prev_hist is not None:
        rising = hist > prev_hist
        value = clamp(hist / (MACD_SCALE * close[i]) + (0.25 if rising else -0.25))
        if hist > 0:
            text = "MACD positive and " + ("rising" if rising else "fading")
        else:
            text = "MACD negative and " + ("recovering" if rising else "falling")
        c["macd"] = (value, "Momentum: " + text)

    rsi = ind["rsi"][i]
    if rsi is not None:
        if rsi >= 70:
            value, text = 0.5 - (rsi - 70) / 20, f"RSI {rsi:.0f} is overbought, pullback risk"
        elif rsi <= 30:
            value, text = -0.5 + (30 - rsi) / 20, f"RSI {rsi:.0f} is oversold, bounce possible"
        else:
            value, text = (rsi - 50) / 40, f"RSI {rsi:.0f} is in the normal range"
        value = clamp(value)
        c["rsi"] = (value, text)

    avg_volume = ind["avg_volume20"][i]
    if avg_volume and i > 0 and volume[i] is not None:
        spike = volume[i] > 1.5 * avg_volume
        if spike and close[i] > close[i - 1]:
            c["volume"] = (1.0, "Volume spike on a rising day")
        elif spike and close[i] < close[i - 1]:
            c["volume"] = (-1.0, "Volume spike on a falling day")
        else:
            c["volume"] = (0.0, "Volume is normal")

    pressure = buy_sell_pressure(ind, i)
    if pressure is not None:
        c["pressure"] = (pressure["value"], f"Volume pressure: {pressure['label'].lower()} over 20 days")

    return _combine_detail(c, SHORT_WEIGHTS, min_weight_share=0.75)


def short_score(ind, i):
    detail = short_detail(ind, i)
    return detail["score"], detail["reasons"]


def long_detail(ind, i):
    """Investor view (months to years)."""
    close = ind["bars"]["c"]
    c = {}

    sma50, sma200 = ind["sma50"][i], ind["sma200"][i]
    if sma200 is not None:
        gap = close[i] / sma200 - 1
        c["trend200"] = (clamp(gap / TREND_LONG_SCALE), "Price is " + _side(gap) + " the 200-day average")
        if sma50 is not None:
            spread = sma50 / sma200 - 1
            event = recent_cross(ind, i)
            if event:
                kind, ago = event
                when = "today" if ago == 0 else f"{ago} session{'s' if ago != 1 else ''} ago"
                text = f"50-day crossed {'above' if kind == 'golden' else 'below'} the 200-day {when} ({kind} cross)"
            elif abs(spread) < LEVEL_BAND:
                text = "50-day is about level with the 200-day"
            else:
                text = "50-day is " + ("above" if spread > 0 else "below") + " the 200-day (" + ("bullish" if spread > 0 else "bearish") + " alignment, no recent crossover)"
            # The score follows the alignment (where the averages are now), not the event.
            c["cross"] = (clamp(spread / TREND_LONG_SCALE), text)

    mom = ind["momentum126"][i]
    if mom is not None:
        c["momentum"] = (clamp(mom / 0.3), f"6-month return is {mom * 100:+.1f}%")

    hi, lo = ind["hi252"][i], ind["lo252"][i]
    if hi is not None and hi > lo:
        position = (close[i] - lo) / (hi - lo)
        c["position"] = (clamp(2 * position - 1), f"Trading at {position * 100:.0f}% of its 52-week range")

    vol = ind["vol30"][i]
    if vol is not None:
        c["volatility"] = (0.5 * clamp((0.30 - vol) / 0.20), f"Volatility {vol * 100:.0f}% a year")

    return _combine_detail(c, LONG_WEIGHTS)


def long_score(ind, i):
    detail = long_detail(ind, i)
    return detail["score"], detail["reasons"]


def invalidation(ind, i, horizon, score):
    """Plain statements of what would weaken or reverse a reading, from the current levels. [] without a reading."""
    if score is None:
        return []
    price = ind["bars"]["c"][i]
    average = ind["sma20"][i] if horizon == "short" else ind["sma200"][i]
    name = "20-day" if horizon == "short" else "200-day"
    bull, bear = score >= BUY, score <= SELL
    out = []
    if average:
        if bull:
            out.append(f"a close below the {name} average ({average:,.2f})")
        elif bear:
            out.append(f"a close above the {name} average ({average:,.2f})")
        else:
            out.append(f"a clear move beyond the {name} average ({average:,.2f}) in either direction")
    if horizon == "short":
        out.append("the MACD histogram turning negative" if bull else "the MACD histogram turning positive" if bear else "the MACD histogram settling on one side of zero")
    else:
        out.append("the 50-day average falling below the 200-day" if bull else "the 50-day average rising above the 200-day" if bear else "the 50-day and 200-day averages separating")
    atr = ind["atr"][i]
    if bull and atr and price - 2 * atr > 0:
        out.append(f"price reaching the volatility risk level ({price - 2 * atr:,.2f})")
    return out


def stop_loss(price, atr_value, multiple=2.0):
    """Protective stop below price. Returns None without ATR data."""
    if not atr_value:
        return None
    stop = price - multiple * atr_value
    if stop <= 0:
        return None
    return {"price": stop, "pct": (stop / price - 1) * 100, "multiple": multiple}


STOP_ATR = 2.0
SHORT_REACH = (1.0, 4.0)      # a chart level counts as a short-term target if it is 1 to 4 R away
SHORT_FALLBACK_R = 2.0
LONG_FALLBACK_R = 3.0


def target_levels(price, atr_value, zones, high52, low52, side):
    """Indicative stop and targets for a buy or sell signal, or None when they cannot be worked out.

    R is the distance to the stop: 2 x the average true range. For a buy the stop is below the price and the
    targets above it, for a sell the other way round.
    Short-term target: the nearest resistance (buy) or support (sell) if it is 1 to 4 R away, otherwise 2 R.
    Long-term target: the 52-week high (buy) or low (sell) if it is at least 1 R away, otherwise 3 R.
    These are reference levels from fixed rules, not a forecast.
    """
    if side not in ("buy", "sell") or not price or price <= 0 or not atr_value or atr_value <= 0:
        return None
    sign = 1 if side == "buy" else -1
    risk = STOP_ATR * atr_value
    stop = price - sign * risk
    if stop <= 0:
        return None

    def reach(level):
        return sign * (level - price)

    def number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def entry(level, basis):
        return {"price": level, "pct": (level / price - 1) * 100, "basis": basis}

    zone_key = "resistance" if side == "buy" else "support"
    levels = [z["level"] for z in ((zones or {}).get(zone_key) or []) if isinstance(z, dict) and number(z.get("level")) and reach(z["level"]) > 0]
    nearest = min(levels, key=reach) if levels else None
    if nearest is not None and SHORT_REACH[0] * risk <= reach(nearest) <= SHORT_REACH[1] * risk:
        short = entry(nearest, zone_key)
    else:
        short = entry(price + sign * SHORT_FALLBACK_R * risk, "volatility")

    extreme = high52 if side == "buy" else low52
    if number(extreme) and reach(extreme) >= risk:
        long = entry(extreme, "52-week high" if side == "buy" else "52-week low")
    else:
        long = entry(price + sign * LONG_FALLBACK_R * risk, "volatility")
    return {"stop": {"price": stop, "pct": (stop / price - 1) * 100}, "short": short, "long": long}
