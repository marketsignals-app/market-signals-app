"""News intelligence: what a company's news is, how credible it is, how much it could matter, and how the price has reacted.

Rule-based and deterministic: there is no language model in this pipeline, so nothing here "understands" an article. It reads the exchange's own
category for official announcements, a keyword classifier for headlines, a word list for tone (engine/sentiment.py), a source-credibility table, and
the price, volume and sector figures the app already has. Every number is explainable from those inputs, and the page says that it is rule-based.

Per story:   event type, sentiment (-100..+100), credibility (0..100), relevance (0..100), impact (0..100), short- and long-term implications, risks.
Per stock:   latest important stories, overall sentiment and impact, fundamental impact, interpretation (Bullish, Bearish, Neutral or Mixed), key risks,
             market reaction (price, volume and sector against the news) and how it compares with the existing reading.

Rules that matter:
  * A story that appears in several outlets is ONE story: near-identical headlines are clustered, the best source represents it, the others are listed
    as corroboration. Corroboration raises credibility a little; it never counts the story twice.
  * News never creates a signal. It is a validation layer: it confirms, conflicts with, or says nothing about the existing reading.
  * Low credibility (rumour language, a single unknown source) pulls the interpretation to Neutral and is named as a risk.
  * Routine filings (newspaper copies, shareholder-meeting notices, call schedules) carry almost no impact.
"""
import re
from datetime import datetime, timezone

from . import ai_sentiment, sentiment

HALF_LIFE_HOURS = 36.0
MIN_RECENCY = 0.15
MAX_AGE_HOURS = 96
DUPLICATE_JACCARD = 0.55

TIER1 = {"reuters", "bloomberg", "the economic times", "economic times", "et markets", "et now", "business standard", "mint", "livemint", "the hindu businessline",
         "businessline", "moneycontrol", "cnbc-tv18", "financial express", "the financial express", "pti", "press trust of india", "ndtv profit", "the hindu", "bse", "nse"}
TIER2 = {"zee business", "the times of india", "times of india", "india today", "business today", "hindustan times", "forbes india", "fortune india", "the print", "theprint",
         "outlook business", "the tribune", "deccan herald", "the new indian express", "the indian express", "indian express", "firstpost", "news18", "ani", "ians"}
RUMOUR = re.compile(r"\b(reportedly|rumou?rs?|speculat\w+|sources? (?:say|said|told)|according to sources|unconfirmed|may|might|could|likely|set to|eyes?|plans? to|in talks)\b", re.I)

# ---------- event types ----------
# key, label, NSE category regex, headline regex, prior direction (-1..+1, applied when the words give none), materiality 0..1, horizon, short-term, long-term, risk
EVENTS = [
    ("insolvency", "Insolvency or default", r"insolvency|default", r"\b(insolvency|bankruptcy|defaults?|nclt|going concern|winding up)\b", -1.0, 1.0, "both",
     "A default or insolvency process usually hits the price at once.", "It puts the continuation of the business, and the equity's value, in question.", "Recovery for shareholders is uncertain and often small."),
    ("fraud_legal", "Regulatory action or legal matter", r"action\(s\) (?:initiated|taken)|litigation|dispute|show cause|sebi|penalty|disciplinary", r"\b(fraud|scam|sebi (?:order|notice|probe)|show cause|raid|probe|investigation|penalty|fined?|lawsuit|sued|ban(?:ned)?|arrest|enforcement directorate|\bed\b|cbi)\b", -0.8, 0.8, "both",
     "Regulatory or legal news often triggers a quick sell-off until the size of the problem is known.", "Penalties, restrictions or loss of licences can change earnings and governance for years.", "The outcome and its size are unknown; headlines can be worse than the final result, or better."),
    ("results", "Financial results", r"financial results|outcome of board meeting|results", r"\b(q[1-4]\b|quarterly results|results|net profit|profit (?:rises|falls|jumps|drops|surges|plunges)|revenue|earnings|ebitda|margins?)\b", 0.0, 0.9, "both",
     "Results move the price within days, depending on how they compare with expectations.", "The earnings trend and margins feed the long-term view.", "One quarter can mislead: one-off items, base effects and guidance matter."),
    ("guidance", "Guidance or outlook", r"guidance|outlook", r"\b(guidance|outlook|forecast|expects?|raises? (?:target|forecast)|cuts? (?:target|forecast))\b", 0.0, 0.8, "both",
     "Changes in guidance reprice expectations quickly.", "It signals management's view of demand and margins for the coming year.", "Guidance is a forecast and is often revised."),
    ("order_win", "Order or contract win", r"bagging|receiving of orders|orders?/contracts?", r"\b(wins?|bags?|secures?|receives?|bagged|awarded)\b.{0,40}\b(orders?|contracts?|tender|deal)\b|\border (?:win|book|inflow)\b", 0.7, 0.6, "both",
     "An order win can lift the price for a few sessions if it is large against the company's size.", "It adds to revenue visibility; the margin on the order decides how much it matters.", "Order size against revenue, margins and execution risk are not in the headline."),
    ("acquisition", "Acquisition or merger", r"acquisition|amalgamation|merger|demerger|scheme of arrangement", r"\b(acquires?|acquisition|merger|demerger|takeover|buys? (?:stake|company)|to acquire|amalgamation|open offer)\b", 0.2, 0.7, "long",
     "The price reaction depends on the price paid and how it is funded.", "Strategy, debt and integration decide whether it adds value.", "Overpaying, extra debt and integration problems are the usual risks."),
    ("rating", "Credit rating or analyst view", r"credit rating", r"\b(rating (?:upgrade|downgrade|reaffirm\w*)|upgrad\w+|downgrad\w+|target price|price target|initiates? coverage|outperform|underperform|overweight|underweight)\b", 0.0, 0.5, "short",
     "Rating and target changes move the price briefly, mostly on the day.", "A change in credit rating changes borrowing costs; analyst targets add little lasting information.", "Analyst views are opinions and often follow the price."),
    ("management", "Management or board change", r"resignation|change in management|change in director|appointment|cessation", r"\b(resigns?|resignation|steps? down|quits?|appoints?|appointed|new (?:ceo|cfo|md|chairman)|ceo|cfo|managing director)\b", -0.2, 0.45, "both",
     "The price may react on the day, more if a CEO or CFO leaves suddenly.", "Leadership stability and continuity matter for execution.", "Abrupt exits, especially of finance heads or auditors, can signal problems the headline does not explain."),
    ("dividend", "Dividend or buyback", r"dividend|buyback|buy back|bonus|split", r"\b(dividends?|buy-?back|bonus (?:issue|shares)|stock split|special dividend)\b", 0.6, 0.5, "short",
     "Payouts support the price around the record date.", "They show cash generation and capital-allocation habits.", "A one-off payout is not a trend."),
    ("fundraising", "Fund raising or dilution", r"allotment|preferential|qip|rights issue|fund ?raising|issue of securities", r"\b(qip|preferential (?:issue|allotment)|rights issue|raises? (?:funds|capital)|fund ?raising|ipo|fpo|ofs|offer for sale|stake sale|block deal)\b", -0.1, 0.45, "both",
     "New shares can weigh on the price near the issue.", "Funds used for growth or debt reduction can help; dilution lowers each share's claim.", "Dilution and the use of the money decide the effect."),
    ("expansion", "Capacity expansion or launch", r"capacity|expansion|commissioning|new plant|launch", r"\b(capex|capacity (?:addition|expansion)|expansion|commissions?|new plant|launch(?:es|ed)?|inaugurat\w+)\b", 0.5, 0.45, "long",
     "Little immediate price effect unless the plan is large.", "New capacity and products support future revenue, if demand is there.", "Delays, cost overruns and weak demand are the risks."),
    ("volume", "Spurt in volume", r"spurt in volume", r"\bspurt in volume\b", 0.0, 0.3, "short", "Unusual trading can precede or follow news; it says activity rose, not why.", "Not a lasting factor by itself.", "The cause is not stated."),
    ("investor_call", "Investor meet or call", r"analysts?/institutional|investor meet|con\. call|conference call|investor presentation|earnings call", r"\b(earnings call|conference call|investor meet|analyst meet)\b", 0.0, 0.15, "short",
     "A scheduled call, usually no price effect by itself.", "Little lasting information.", "Content of the call is what matters, not the notice."),
    ("routine", "Routine filing", r"newspaper publication|shareholders? meeting|esop|esos|esps|general updates|^updates|intimation|trading window|closure of|record date|agm|postal ballot|certificate|compliance", r"$^", 0.0, 0.08, "short",
     "Routine filing, normally no price effect.", "No lasting information.", "Nothing material is stated."),
    ("press_release", "Press release", r"press release", r"$^", 0.0, 0.2, "short", "Company-issued news; read the release for substance.", "Depends on what the release announces.", "Company-issued wording is promotional by nature."),
    ("market", "Market or sector news", r"$^", r"\b(sensex|nifty|rbi|inflation|crude|rupee|fii|fpi|budget|gdp|repo rate|sector)\b", 0.0, 0.3, "short",
     "Market-wide news moves many stocks together.", "Policy and macro conditions shape sector earnings.", "Effects differ from stock to stock."),
    ("general", "General news", r"$^", r"$^", 0.0, 0.3, "short", "Effect on the price is unclear from the headline.", "Effect on the business is unclear from the headline.", "The headline does not say how it affects earnings."),
]
_EVENT_BY_KEY = {e[0]: e for e in EVENTS}
SECTOR_WORDS = {"Banks": r"\bbanks?|banking|npa|rbi\b", "IT": r"\bit services|software|tech(?:nology)?|infosys|tcs|wipro", "Pharma": r"\bpharma|drug|usfda|medicine|healthcare",
                "Auto": r"\bauto(?:mobile)?s?|vehicle|ev\b|two-?wheeler", "Metals": r"\bmetals?|steel|aluminium|copper|zinc", "Energy": r"\boil|gas|power|energy|crude|renewable",
                "FMCG": r"\bfmcg|consumer goods", "Realty": r"\breal estate|realty|housing", "Financials": r"\bnbfc|insurance|financial services|mutual fund"}


def classify(desc, text):
    """The event type tuple for an announcement category (desc) and its headline/text. The exchange's own category wins when it matches."""
    desc, text = (desc or "").lower(), (text or "").lower()
    if desc:
        for event in EVENTS:
            if event[2] != "$^" and re.search(event[2], desc):
                return event
    for event in EVENTS:
        if event[3] != "$^" and re.search(event[3], text, re.I):
            return event
    return _EVENT_BY_KEY["general"]


def source_credibility(name, kind):
    """(0..100, tier word) for a source: the exchange itself is highest, known outlets high, unknown sources low."""
    n = (name or "").strip().lower()
    if kind == "nse":
        return 95, "official filing"
    if n in TIER1 or any(t in n for t in ("economic times", "business standard", "moneycontrol", "livemint", "reuters", "bloomberg")):
        return 82, "established outlet"
    if n in TIER2:
        return 66, "recognised outlet"
    return 45, "unknown source"


# ---------- stories ----------

def _tokens(title):
    return {w for w in re.findall(r"[a-z]{3,}", (title or "").lower()) if w not in {"the", "and", "for", "with", "from", "that", "this", "has", "have", "will", "its", "are", "was", "after", "over", "says", "said"}}


def make_story(raw, now, name=None):
    """One scored story from a raw item: {"title", "text", "source", "link", "ts", "kind" ("nse" or "media"), "desc" (NSE category), "relevance" (0..1)}."""
    title, text = raw.get("title") or "", raw.get("text") or raw.get("title") or ""
    event = classify(raw.get("desc"), f"{title} {text}")
    ai = raw.get("ai") if isinstance(raw.get("ai"), dict) else None
    if ai_sentiment.AI_WEIGHT > 0 and event[0] == "general" and ai and ai.get("event") in _EVENT_BY_KEY:         # only when the model has a say: it may name the event the rules did not find
        event = _EVENT_BY_KEY[ai["event"]]
    key, label, _, _, prior, materiality, horizon, short_note, long_note, risk = event
    words, hits = sentiment.score_title(f"{title} {text}" if raw.get("kind") == "nse" else title)
    # words decide when they say something; the event's prior fills in only when they say nothing, and then only partly
    if abs(words) >= 0.05:
        direction = words if prior == 0 else 0.75 * words + 0.25 * prior
    else:
        direction = 0.6 * prior
    score = max(-100, min(100, round(direction * 100)))
    rule_score = score
    score, ai_used = ai_sentiment.blend(score, ai)                               # shadow mode: the rule score stands; the model's is kept beside it
    credibility, tier = source_credibility(raw.get("source"), raw.get("kind"))
    if raw.get("kind") != "nse" and RUMOUR.search(title):
        credibility = max(20, credibility - 25)
    age = None
    if isinstance(raw.get("ts"), (int, float)):
        age = max(0.0, (now.timestamp() - raw["ts"]) / 3600.0)
    recency = 1.0 if age is None else max(MIN_RECENCY, 0.5 ** (age / HALF_LIFE_HOURS))
    relevance = max(0.0, min(1.0, raw.get("relevance", 1.0)))
    boost = 1.15 if re.search(r"\b(record|plunge|surge|soar|crash|slump)\w*", title, re.I) else 1.0
    impact = round(min(100.0, materiality * 100 * (credibility / 100) * relevance * recency * boost))
    return {"title": title, "source": raw.get("source") or "", "link": raw.get("link") or "", "ts": raw.get("ts"), "kind": raw.get("kind") or "media",
            "event": key, "event_label": label, "sentiment": score, "rule_sentiment": rule_score, "ai_sentiment": ai["sentiment"] if ai_used else None, "tone": "Positive" if score >= 20 else "Negative" if score <= -20 else "Neutral",
            "credibility": credibility, "tier": tier, "relevance": round(relevance * 100), "impact": impact, "horizon": horizon, "words": hits,
            "short_term": short_note, "long_term": long_note, "risk": risk, "sources": [raw.get("source") or ""], "duplicates": 0, "ai": ai_used, "rumour": bool(RUMOUR.search(title)) and raw.get("kind") != "nse",
            "age_hours": round(age, 1) if age is not None else None, "recency": round(recency, 2), "symbol": raw.get("symbol"), "name": name}


def dedupe(stories):
    """Cluster near-identical headlines (syndication) into one story each. The most credible, then the newest, represents the cluster; the other
    sources are listed, `duplicates` counts the repeats, and corroboration by a second distinct source raises credibility by 8 (to at most 95)."""
    clusters = []

    def signature(story):
        """The same official filing posted on both exchanges: same stock, same event type, within the same 12 hours."""
        if story["kind"] in ("nse", "bse") and story.get("symbol") and story.get("ts") is not None:
            return (story["symbol"], story["event"], int(story["ts"] // (12 * 3600)))
        return None

    for story in sorted(stories, key=lambda s: (-s["credibility"], -(s["ts"] or 0))):
        tokens, sig = _tokens(story["title"]), signature(story)
        for cluster in clusters:
            other = cluster["tokens"]
            union = tokens | other
            if (sig is not None and sig == cluster["sig"]) or (union and len(tokens & other) / len(union) >= DUPLICATE_JACCARD):
                cluster["items"].append(story)
                break
        else:
            clusters.append({"tokens": tokens, "items": [story], "sig": sig})
    out = []
    for cluster in clusters:
        head = dict(cluster["items"][0])
        sources = []
        for item in cluster["items"]:
            for s in item["sources"]:
                if s and s not in sources:
                    sources.append(s)
        head["sources"], head["duplicates"] = sources, len(cluster["items"]) - 1
        if len(sources) >= 2 and head["kind"] != "nse":
            head["credibility"] = min(95, head["credibility"] + 8)
            head["impact"] = min(100, round(head["impact"] * 1.05))
        out.append(head)
    return out


# ---------- one stock ----------

FUNDAMENTAL_EVENTS = {"insolvency", "fraud_legal", "results", "guidance", "order_win", "acquisition", "rating", "management", "dividend", "fundraising", "expansion"}


def analyse_stock(stories, now):
    """The stock-level picture from its de-duplicated stories (strongest impact first). None when there are no stories."""
    stories = [s for s in stories if s["age_hours"] is None or s["age_hours"] <= MAX_AGE_HOURS]
    if not stories:
        return None
    stories = sorted(stories, key=lambda s: (-s["impact"], s["age_hours"] if s["age_hours"] is not None else 9e9))
    weight = sum(s["impact"] for s in stories)
    score = round(sum(s["impact"] * s["sentiment"] for s in stories) / (weight + 10)) if weight else 0       # +10 pulls a stock with only trivial news toward zero
    impact = round(min(100, stories[0]["impact"] + 0.25 * sum(s["impact"] for s in stories[1:4])))
    material = [s for s in stories if s["impact"] >= 25]
    pos = [s for s in material if s["sentiment"] >= 20]
    neg = [s for s in material if s["sentiment"] <= -20]
    label = "Mixed" if pos and neg else "Positive" if score >= 20 else "Negative" if score <= -20 else "Neutral"
    cred = round(sum(s["credibility"] * max(s["impact"], 1) for s in stories) / sum(max(s["impact"], 1) for s in stories))
    reliable = cred >= 55
    interpretation = "Mixed" if label == "Mixed" else "Bullish" if label == "Positive" and reliable else "Bearish" if label == "Negative" and reliable else "Neutral"

    drivers = [s for s in stories if s["event"] in FUNDAMENTAL_EVENTS and s["impact"] >= 20]
    top_driver = drivers[0] if drivers else None
    level = "high" if top_driver and top_driver["impact"] >= 55 else "medium" if top_driver and top_driver["impact"] >= 35 else "low" if top_driver else "none"
    fundamental = {"level": level, "direction": ("positive" if top_driver["sentiment"] >= 20 else "negative" if top_driver["sentiment"] <= -20 else "unclear") if top_driver else None,
                   "drivers": [s["event_label"] for s in drivers[:3]],
                   "text": (f"{level.capitalize()} {('positive' if top_driver['sentiment'] >= 20 else 'negative' if top_driver['sentiment'] <= -20 else 'unclear')} fundamental impact: "
                            f"{', '.join(dict.fromkeys(s['event_label'].lower() for s in drivers[:3]))}") if top_driver else "No news with a clear effect on the company's fundamentals"}

    risks = []
    if label == "Mixed":
        risks.append("Positive and negative news at the same time: the net effect is unclear.")
    if any(s["event"] in ("fraud_legal", "insolvency") and s["sentiment"] < 0 for s in material):
        risks.append("Regulatory, legal or solvency news: the outcome and its size are not known yet.")
    if any(s["event"] == "management" and s["sentiment"] < 0 for s in material):
        risks.append("A management or board exit: continuity and the reason matter.")
    if any(s["rumour"] for s in material):
        risks.append("Some of the news rests on reports or sources not confirmed by the company.")
    if material and all(len(s["sources"]) == 1 and s["kind"] != "nse" for s in material):
        risks.append("The important stories come from a single outlet each and are not corroborated by the exchange or a second source.")
    if not reliable:
        risks.append("Average source credibility is low, so the interpretation is held at Neutral.")
    if top_driver:
        risks.append(top_driver["risk"])
    explanation = (f"{len(stories)} recent stor{'y' if len(stories) == 1 else 'ies'} read by rules: sentiment {score:+d} (impact-weighted), impact {impact}, average credibility {cred}. "
                   + (f"Most important: {stories[0]['event_label'].lower()} ({stories[0]['tone'].lower()}, impact {stories[0]['impact']}, {stories[0]['tier']})." if stories else ""))
    horizons = {"short": next((s["short_term"] for s in stories if s["horizon"] in ("short", "both") and s["impact"] >= 20), None),
                "long": next((s["long_term"] for s in stories if s["horizon"] in ("long", "both") and s["impact"] >= 20), None)}
    return {"label": label, "interpretation": interpretation, "sentiment": score, "impact": impact, "credibility": cred, "n": len(stories), "fundamental": fundamental,
            "risks": list(dict.fromkeys(risks))[:5], "explanation": explanation, "horizons": horizons, "stories": stories[:8],
            "latest": [s for s in sorted(stories, key=lambda s: (-(s["impact"] * s["recency"]), s["age_hours"] or 0))[:3]],
            "generated_at": now.isoformat(timespec="seconds")}


# ---------- how the price reacted, and how it compares with the reading ----------

def reaction(intel, change_pct, volume_ratio, sector_change_pct):
    """{"state", "text"} comparing the news direction with today's price move, volume and the stock's sector. None without news."""
    if not intel:
        return None
    direction = 1 if intel["sentiment"] >= 20 else -1 if intel["sentiment"] <= -20 else 0
    if change_pct is None:
        return {"state": "unknown", "text": "No price move is available to compare with the news."}
    move = "up" if change_pct > 0.5 else "down" if change_pct < -0.5 else "little changed"
    parts = [f"Price {move} {abs(change_pct):.1f}%" if move != "little changed" else "Price little changed"]
    if isinstance(volume_ratio, (int, float)):
        parts.append(f"volume {volume_ratio:.1f}x its 20-day average")
    if isinstance(sector_change_pct, (int, float)):
        relative = change_pct - sector_change_pct
        parts.append(f"{'ahead of' if relative > 0.3 else 'behind' if relative < -0.3 else 'in line with'} its sector ({sector_change_pct:+.1f}%)")
    if direction == 0 or abs(change_pct) <= 0.5:
        state = "no clear reaction"
    elif (change_pct > 0) == (direction > 0):
        state = "price confirms"
    else:
        state = "price diverges"
    heavy = isinstance(volume_ratio, (int, float)) and volume_ratio >= 1.5
    text = ", ".join(parts) + ". " + {"price confirms": "The move agrees with the direction of the news" + (", on heavy volume." if heavy else "."),
                                       "price diverges": "The move is against the direction of the news" + (", on heavy volume, which makes the disagreement more notable." if heavy else ": the market may be discounting it or looking at something else."),
                                       "no clear reaction": "No clear price reaction to the news yet."}[state]
    return {"state": state, "text": text}


def validate(intel, reading_side):
    """How the news compares with the existing reading: "confirms", "conflicts" or "neutral". Never a signal. reading_side: "buy", "sell", "hold" or None."""
    if not intel or reading_side not in ("buy", "sell") or intel["interpretation"] in ("Neutral",):
        return {"state": "neutral", "text": "The news neither supports nor opposes the current reading."}
    if intel["interpretation"] == "Mixed":
        return {"state": "neutral", "text": "The news is mixed, so it does not settle the current reading either way."}
    agrees = (intel["interpretation"] == "Bullish") == (reading_side == "buy")
    return {"state": "confirms" if agrees else "conflicts",
            "text": (f"The {intel['interpretation'].lower()} news {'agrees with' if agrees else 'runs against'} the current {'bullish' if reading_side == 'buy' else 'bearish'} reading "
                     f"(news impact {intel['impact']}, credibility {intel['credibility']}).")}


# ---------- sectors and the dashboard ----------

def sector_of_text(text):
    for sector, pattern in SECTOR_WORDS.items():
        if re.search(pattern, text or "", re.I):
            return sector
    return None


def sector_table(stock_rows, sector_moves):
    """One row per sector: [{"sector", "stocks", "sentiment", "impact", "positive", "negative", "price_move_pct", "state"}], most news first.

    stock_rows: [{"sector", "intel"}]. sector_moves: {sector: 1-day move in percent}."""
    groups = {}
    for row in stock_rows:
        if row.get("intel"):
            groups.setdefault(row["sector"], []).append(row["intel"])
    table = []
    for sector, items in groups.items():
        weight = sum(i["impact"] for i in items)
        score = round(sum(i["impact"] * i["sentiment"] for i in items) / (weight + 10)) if weight else 0
        move = sector_moves.get(sector)
        direction = 1 if score >= 20 else -1 if score <= -20 else 0
        state = "no clear reaction" if move is None or direction == 0 or abs(move) < 0.3 else "price confirms" if (move > 0) == (direction > 0) else "price diverges"
        table.append({"sector": sector, "stocks": len(items), "sentiment": score, "impact": round(weight / len(items)), "positive": sum(1 for i in items if i["label"] == "Positive"),
                      "negative": sum(1 for i in items if i["label"] == "Negative"), "mixed": sum(1 for i in items if i["label"] == "Mixed"), "price_move_pct": move, "state": state})
    return sorted(table, key=lambda r: -(r["stocks"] * (abs(r["sentiment"]) + r["impact"])))
