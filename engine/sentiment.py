"""News tone: a small, additional parameter in a short-term reading. It is never the source of truth.

A plain word list for financial headlines (no outside service, nothing is sent anywhere) scores each headline from -1 to +1, with negation handled
("denies fraud" is not negative), a phrase list ahead of the single words ("record profit" before "profit"), and an intensity word ("sharply",
"slumps"). A stock's tone is the recency-weighted average over its recent headlines that are clearly about the company (half-life 24 hours,
nothing older than 72), duplicates counted once, then pulled toward zero when there are few headlines: a single headline cannot move the tone far.

What this is and is not:
  * A word list reads words, not meaning. Sarcasm, context and headlines that report a fall as bad news for someone else are misread. Accuracy was not
    measured against labelled data, which does not exist for this feed; treat the tone as a rough signal.
  * It carries a small weight in the short-term score (signals.NEWS_WEIGHT, 5 of 105) and none in the long-term score. Backtests cannot include it (there
    is no historical news), so they use the price and volume rule alone.
  * Every reading's news part is recorded with each tracked call, so the Track record tab can show, once there are enough settled calls, whether
    readings the news supported did better than readings it opposed.
"""
import math
import re

HALF_LIFE_HOURS = 24.0
MAX_AGE_HOURS = 72
SHRINK = 2.0              # tone is multiplied by n / (n + SHRINK)
MIN_ITEMS = 1

# Phrases first (matched as whole text), then words. Values are -2..+2; two means a strong word.
PHRASES = {
    "record profit": 2, "record revenue": 2, "record high": 1.5, "all-time high": 1.5, "beats estimates": 2, "beat estimates": 2, "tops estimates": 2,
    "ahead of estimates": 1.5, "better than expected": 1.5, "raises guidance": 2, "raises outlook": 1.5, "order win": 1.5, "wins order": 1.5, "bags order": 1.5,
    "secures order": 1.5, "dividend hike": 1.5, "special dividend": 1, "share buyback": 1, "buyback": 1, "stake sale": -0.5, "rating upgrade": 2,
    "target raised": 1.5, "price target raised": 1.5, "strong results": 1.5, "strong growth": 1.5, "profit jumps": 2, "profit rises": 1.5, "profit surges": 2,
    # a record or high that the price is falling away from is not good news
    "from record high": -0.5, "from record highs": -0.5, "off record high": -0.5, "off record highs": -0.5, "below record high": -0.5, "from all-time high": -0.5,
    "from all-time highs": -0.5, "off all-time high": -0.5, "below all-time high": -0.5,
    "misses estimates": -2, "miss estimates": -2, "below estimates": -1.5, "worse than expected": -1.5, "cuts guidance": -2, "cuts outlook": -1.5,
    "profit falls": -1.5, "profit drops": -1.5, "profit plunges": -2, "net loss": -1.5, "rating downgrade": -2, "target cut": -1.5, "price target cut": -1.5,
    "show cause notice": -1.5, "raid": -1.5, "tax raid": -2, "stake sold": -0.5, "promoter pledge": -1, "debt default": -2, "going concern": -2,
    "under investigation": -1.5, "sebi order": -1.5, "sebi notice": -1.5, "fraud": -2, "accounting irregularities": -2,
}
POSITIVE = {
    "surge": 1.5, "surges": 1.5, "soar": 2, "soars": 2, "rally": 1.5, "rallies": 1.5, "jump": 1.5, "jumps": 1.5, "gain": 1, "gains": 1, "rise": 1, "rises": 1,
    "climb": 1, "climbs": 1, "up": 0.3, "upgrade": 1.5, "upgraded": 1.5, "outperform": 1.5, "beats": 1.5, "beat": 1.5, "strong": 1, "robust": 1, "growth": 0.7,
    "profit": 0.5, "wins": 1, "win": 1, "bags": 1, "secures": 1, "approval": 1, "approves": 1, "approved": 1, "expands": 1, "expansion": 1, "launches": 0.5,
    "record": 1, "boost": 1, "boosts": 1, "improves": 1, "improved": 1, "recovers": 1, "recovery": 1, "bullish": 1.5, "optimistic": 1, "acquires": 0.7, "deal": 0.4,
    "dividend": 0.5, "bonus": 0.7, "buy": 0.5, "overweight": 1,
}
PHRASES_LONGEST_FIRST = sorted(PHRASES.items(), key=lambda kv: -len(kv[0]))
NEGATIVE = {
    "plunge": -2, "plunges": -2, "slump": -2, "slumps": -2, "crash": -2, "crashes": -2, "tumble": -1.5, "tumbles": -1.5, "fall": -1, "falls": -1, "drop": -1,
    "drops": -1, "slide": -1, "slides": -1, "retreat": -1, "retreats": -1, "retreated": -1, "slip": -1, "slips": -1, "slipped": -1, "cools": -0.5, "erodes": -1, "sink": -1.5, "sinks": -1.5, "decline": -1, "declines": -1, "down": -0.3, "downgrade": -1.5, "downgraded": -1.5,
    "underperform": -1.5, "misses": -1.5, "miss": -1.5, "weak": -1, "weakness": -1, "loss": -1, "losses": -1, "probe": -1, "penalty": -1.5, "fine": -1, "fined": -1.5,
    "lawsuit": -1, "sued": -1, "resigns": -1, "resignation": -1, "exits": -0.5, "ban": -1.5, "banned": -1.5, "recall": -1.5, "fire": -1, "shutdown": -1.5, "warns": -1.5,
    "warning": -1, "default": -2, "bankruptcy": -2, "insolvency": -2, "scam": -2, "fraud": -2, "cuts": -1, "cut": -1, "layoffs": -1.5, "slowdown": -1, "bearish": -1.5,
    "pessimistic": -1, "concern": -0.7, "concerns": -0.7, "risk": -0.3, "volatile": -0.3, "sell": -0.5, "underweight": -1, "delays": -1, "delayed": -1, "halts": -1.5,
}
NEGATORS = {"no", "not", "never", "without", "denies", "denied", "dismisses", "dismissed", "clears", "cleared", "fails"}
INTENSIFIERS = {"sharply": 1.3, "steeply": 1.3, "massive": 1.3, "huge": 1.3, "big": 1.15, "major": 1.15, "slightly": 0.7, "marginally": 0.7, "modest": 0.7, "modestly": 0.7}
QUESTION = re.compile(r"\?\s*$")
_TOKEN = re.compile(r"[a-z][a-z'\-]*")


def score_title(title):
    """A headline's tone from -1 to +1 (0 when no word in the list appears), and the words that decided it."""
    text = (title or "").lower()
    if not text:
        return 0.0, []
    total, hits = 0.0, []
    remaining = text
    for phrase, value in PHRASES_LONGEST_FIRST:                  # a longer phrase wins over the shorter one inside it ("from record high" over "record high")
        position = remaining.find(phrase)
        if position >= 0:
            before = _TOKEN.findall(remaining[:position])[-3:]
            total += -value * 0.7 if any(w in NEGATORS for w in before) else value         # "denies fraud" is not bad news
            hits.append(phrase)
            remaining = remaining.replace(phrase, " ")
    words = _TOKEN.findall(remaining)
    for n, word in enumerate(words):
        value = POSITIVE.get(word, NEGATIVE.get(word))
        if value is None:
            continue
        window = words[max(0, n - 3):n]
        if any(w in NEGATORS for w in window):                 # "denies fraud", "no loss": the meaning turns round
            value = -value * 0.7
        boost = max((INTENSIFIERS.get(w, 1.0) for w in window), default=1.0) if window else 1.0
        total += value * boost
        hits.append(word)
    if QUESTION.search(text):                                   # a question reports nothing
        total *= 0.3
    return round(math.tanh(total / 2.0), 3), hits[:4]


def _key(title):
    return " ".join(_TOKEN.findall((title or "").lower())[:8])


def tone(items, max_age_hours=MAX_AGE_HOURS):
    """The tone of a stock's recent headlines: {"score" -1..1, "n", "positive", "negative", "label", "confidence", "items": [...]} or None when there is nothing to read.

    items: headline dicts from engine/news.py with "title", "age_min" and "relevant". Only relevant headlines under max_age_hours count."""
    seen, rows = set(), []
    for item in items or []:
        age = item.get("age_min")
        if not item.get("relevant", True) or age is None or age > max_age_hours * 60:
            continue
        key = _key(item.get("title"))
        if not key or key in seen:
            continue
        seen.add(key)
        value, hits = score_title(item.get("title"))
        weight = 0.5 ** (age / 60.0 / HALF_LIFE_HOURS)
        rows.append({"title": item.get("title"), "source": item.get("source"), "score": value, "weight": weight, "age_min": age, "words": hits})
    if len(rows) < MIN_ITEMS:
        return None
    scored = [r for r in rows if r["score"] != 0.0]
    weights = sum(r["weight"] for r in rows)
    raw = sum(r["weight"] * r["score"] for r in rows) / weights if weights else 0.0
    n = len(rows)
    score = raw * n / (n + SHRINK)
    label = "positive" if score >= 0.15 else "negative" if score <= -0.15 else "neutral"
    top = sorted(rows, key=lambda r: -abs(r["score"] * r["weight"]))[:3]
    return {"score": round(score, 3), "n": n, "read": len(scored), "positive": sum(1 for r in rows if r["score"] > 0.15), "negative": sum(1 for r in rows if r["score"] < -0.15),
            "label": label, "confidence": "low" if n < 3 else "medium" if n < 6 else "higher",
            "items": [{"title": r["title"], "source": r["source"], "score": r["score"], "age_min": r["age_min"], "words": r["words"]} for r in top]}


def component(summary):
    """(value, text) for the short-term score, or None when there is nothing to read or nothing in the words."""
    if not summary or summary["read"] == 0:
        return None
    word = {"positive": "leaning positive", "negative": "leaning negative", "neutral": "neutral"}[summary["label"]]
    return summary["score"], (f"News tone: {word} ({summary['positive']} positive, {summary['negative']} negative of {summary['n']} recent headline"
                              f"{'' if summary['n'] == 1 else 's'}, word-based, low weight)")
