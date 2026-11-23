"""A rough tone for a headline, from a word list. Experimental: it is shown on the website and is not used in any reading or alert.

A plain word list for financial headlines (no outside service, nothing is sent anywhere) scores a headline from -1 to +1, with negation handled
("denies fraud" is not negative), a phrase list ahead of the single words ("record profit" before "profit", and the longest phrase wins), and an intensity word
("sharply", "slumps").

What this is and is not:
  * A word list reads words, not meaning. Sarcasm, context and headlines that report a fall as bad news for someone else are misread. Accuracy was not
    measured against labelled data, which does not exist for this feed; treat the tone as rough.
  * It is not part of any Buy or Sell reading, any Telegram alert or any backtest (it was part of the short-term reading until 23 Nov 2026 and was removed because it
    had not been validated). The website shows it, labelled experimental.
"""
import math
import re


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
