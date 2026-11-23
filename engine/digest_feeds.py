"""The messages of the scheduled feeds (engine/feeds.py), in three styles. Cards that already exist in engine/digest.py are reused.

  A  a numbered heading with sub-points: readings, important filings, entries (volatility alert, upcoming IPOs, events, weekly summary)
  B  one numbered line per item, figures inline: movers, IPO breakouts, block deals, headlines, news lines
  C  a monospace table: indexes, commodities, sectors

Every message has a bold title with the IST time, its hashtags, sections of numbered entries (numbering restarts in each section) and the advisory footer.
Every entry carries hashtags (the stock symbol, the kind of alert) so they can be searched in Telegram.
"""
import html
import re
from datetime import datetime

from . import alerts, digest, feed_items

esc = html.escape
NBSP = chr(160)                    # a no-break space: Telegram keeps it, so the sub-points stay indented
SECTION_OF = {"signal": digest.READINGS_TITLE, "deal": digest.DEALS_TITLE, "mover": digest.MOVERS_TITLE, "low52": digest.LOW_TITLE, "ipo": "━━ IPO BREAKOUTS ━━",
              "brief": digest.BRIEF_TITLE, "news": digest.NEWS_TITLE, "bulk": "━━ BULK DEALS ━━", "filing": "━━ IMPORTANT FILINGS ━━"}
ICONS = {"readings": "\U0001F7E2", "movers": "\U0001F4C8", "ipo_breakout": "\U0001F680", "deals": "\U0001F9F1", "filings": "\U0001F4D1", "news": "\U0001F4F0", "indexes": "\U0001F4CA",
         "commodities": "\U0001F6E2", "sectors": "\U0001F9ED", "news_digest": "\U0001F5DE", "ipo_upcoming": "\U0001F4C5", "events_today": "\U0001F5D3", "weekly": "\U0001F4C6",
         "bulk_deals": "📦", "volatility": "⚡", "circuits": "🚦", "corp_actions": "📜", "surveillance": "🛑", "gaps": "📊", "action_dates": "🗓", "urgent": "⚠️"}


def tag_line(tags):
    tags = [t for t in (tags or []) if str(t).startswith("#")]
    return "  " + " ".join(esc(t) for t in tags) if tags else ""


def stock_tags(item, *extra):
    """Hashtags of a stock item: its symbol, then the extras (the kind of alert)."""
    return [t for t in dict.fromkeys([feed_items.symbol_tag(item.get("symbol")), *extra]) if t]


def list_item(number, card, tags=None):
    """Style A: '1. <b>Heading</b>' with the card's other lines as indented sub-points, then the hashtags."""
    lines = card.split("\n")
    out = [f"{number}. {lines[0]}"]
    for line in lines[1:]:
        if line.startswith("   " + digest.DASH):
            out.append(NBSP * 6 + line.strip())
        elif line.startswith(digest.BULLET):
            out.append(NBSP * 3 + line)
        else:
            out.append(NBSP * 3 + f"{digest.BULLET} {line}")
    if tags:
        out.append(NBSP * 3 + tag_line(tags).strip())
    return "\n".join(out)


def filing_card(item):
    lines = [f"\U0001F4D1 <b>{esc(item['name'])}: {esc(item['event_label'])}</b>", f"{digest.BULLET} Filing: {esc(digest.quiet(digest._clip(item['title'], digest.MAX_TITLE)))}"]
    if isinstance(item.get("impact"), (int, float)):
        lines.append(f"{digest.BULLET} Importance: {item['impact']} of 100 (rule-based, from the type of filing, the source and how recent it is)")
    lines.append(f"{digest.BULLET} Source: {esc(item['source'])} · {esc(item['when'])}")
    if str(item.get("link") or "").startswith("https://"):
        lines.append(f"{digest.BULLET} {alerts.anchor(item['link'], 'Read filing')}")
    return "\n".join(lines)


def entry_card(item, link):
    lines = [f"<b>{esc(digest.quiet(digest._clip(item['heading'], 160)))}</b>"] + [f"{digest.BULLET} {esc(digest.quiet(digest._clip(p, 220)))}" for p in item.get("points") or []]
    url = item.get("link") or link
    if str(url or "").startswith("https://"):
        lines.append(f"{digest.BULLET} {alerts.anchor(url, 'Details')}")
    return "\n".join(lines)


def line_item(number, item):
    """Style B: one numbered line with the figures inline and the hashtags at the end."""
    kind = item["kind"]
    if kind in ("mover", "low52"):
        body = (f"<b>{esc(item['name'])}</b> · {esc('; '.join(item['tags']))}{' · small stock' if item.get('small') else ''} · "
                f"{esc(alerts.money_text(item['price'], item.get('currency') or ''))}")
        move = item.get("move") if isinstance(item.get("move"), (int, float)) else 0
        extra = ("#Surge" if move >= 10 else "#Crash" if move <= -10 else "#Rising" if move > 0 else "#Falling") if kind == "mover" else "#52WeekLow"
        tags = stock_tags(item, "#Mover" if kind == "mover" else "#52WeekLow", extra)
    elif kind == "ipo":
        body = f"\U0001F680 <b>{esc(item['name'])}</b> · {esc('; '.join(item['tags']))} · {esc(alerts.money_text(item['price'], item.get('currency') or ''))}"
        tags = stock_tags(item, "#IPOBreakout")
    elif kind == "deal":
        body = (f"<b>{esc(item['name'])}</b> · block deal {item['qty']:,} shares at {esc(alerts.money_text(item['price'], 'INR'))} ({esc(alerts.money_crore(item['value']))})"
                + (f" · {item['pchange']:+.2f}%" if isinstance(item.get("pchange"), (int, float)) else ""))
        tags = stock_tags(item, "#BlockDeal")
    elif kind == "bulk":
        client = f" · {esc(digest.quiet(item['client']))}" if item.get("client") else ""
        body = (f"<b>{esc(item['name'])}</b> · {esc(item['side'])} {item['qty']:,.0f} shares at {esc(alerts.money_text(item['price'], 'INR'))} "
                f"({esc(alerts.money_crore(item['value']))}){client}")
        tags = stock_tags(item, "#BulkDeal", "#Buy" if item["side"] == "BUY" else "#Sell")
    elif kind == "news":
        source = esc(digest.quiet(item["source"] or "unknown"))
        age = esc(alerts.news.age_text(item.get("age_min")) or "time unknown")
        read = f" {alerts.anchor(item['link'], 'Read article')}" if str(item.get("link") or "").startswith("https://") else ""
        body = f"<b>{esc(item['name'])}</b>: {esc(digest.quiet(digest._clip(item['title'], 150)))} ({source}, {age}){read}"
        tags = stock_tags(item, "#News")
    else:
        read = f" {alerts.anchor(item['link'], 'Read article')}" if str(item.get("link") or "").startswith("https://") else ""
        body = esc(digest.quiet(item["text"])) + read
        tags = item.get("tags")
    return f"{number}. {body}" + tag_line(tags)


def table_block(item):
    """Style C: a monospace table, its source and the hashtags. Telegram does not align columns, so the table is a preformatted block."""
    rows = [item["header"]] + item["rows"] if any(item["header"]) else list(item["rows"])
    widths = [max(len(str(r[c])) for r in rows) for c in range(len(rows[0]))]
    out = []
    for r in rows:
        cells = [str(r[0]).ljust(widths[0])] + [str(v).rjust(widths[i]) for i, v in enumerate(r[1:-1], 1)] + [str(r[-1])]
        out.append("  ".join(cells).rstrip())
    return "<pre>" + esc("\n".join(out)) + "</pre>\n" + esc("Source: " + item["source"]) + tag_line(item.get("tags"))


# ---------- numbers go in tables: each alert that carries figures becomes a row of a monospace table ----------
def money(value):
    """A price or level without the currency sign (the caption says rupees): two decimals under 1,000, one above, so a column lines up."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "-"
    return f"{value:,.2f}" if abs(value) < 1000 else f"{value:,.1f}"


def quantity(value):
    if not isinstance(value, (int, float)):
        return "-"
    return f"{value / 1e7:,.2f}cr" if value >= 1e7 else f"{value / 1e5:,.1f}L" if value >= 1e5 else f"{value:,.0f}"


def crore(value):
    if not isinstance(value, (int, float)):
        return "-"
    return f"{value / 1e7:,.1f}cr" if value >= 1e6 else f"{value / 1e5:,.1f}L"


def pct(value, digits=1):
    return f"{value:+.{digits}f}%" if isinstance(value, (int, float)) else "-"


def short(symbol, width=10):
    return str(symbol or "").replace(".NS", "").replace(".BO", "")[:width]


def one_day(iso):
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d %b").lstrip("0")
    except (TypeError, ValueError):
        return "-"


def day_range(first, last):
    try:
        a, b = datetime.strptime(first, "%Y-%m-%d"), datetime.strptime(last, "%Y-%m-%d")
    except (TypeError, ValueError):
        return "-"
    return f"{a.day}-{b.day} {b:%b}" if a.month == b.month else f"{a.day} {a:%b}-{b.day} {b:%b}"


def _note_of(tags):
    """The mover's tags without the percentage, shortened: 'volume 7.9x average' becomes 'vol 7.9x'."""
    out = []
    for t in tags or []:
        if re.match(r"^[+-]\d", t):
            continue
        t = re.sub(r"volume (\S+) average", r"vol \1", t).replace("at 52-week high", "52w high").replace("at 52-week low", "52w low")
        out.append(t)
    return "; ".join(out)


YAHOO = "Yahoo Finance (delayed)"
MAX_TABLE_TAGS = 25


def to_row(item):
    """A description of the table row for an alert item, or None when the item stays a text entry:
    {"title", "header", "aligns" (l or r per column), "row", "notes" (lines under the table), "caption", "source", "tags"}."""
    kind, stats = item.get("kind"), item.get("stats") or {}
    sym = short(item.get("symbol"))
    if kind in ("mover", "low52"):
        move = item.get("move") if isinstance(item.get("move"), (int, float)) else 0
        title = "52-WEEK LOWS" if kind == "low52" else "RISING" if move >= 0 else "FALLING"
        extra = "#52WeekLow" if kind == "low52" else "#Surge" if move >= 10 else "#Crash" if move <= -10 else "#Rising" if move > 0 else "#Falling"
        note = _note_of(item.get("tags")) or ("52w low" if kind == "low52" else "")
        return {"title": title, "header": ["Stock", "Move", "Price", "Note"], "aligns": "lrrl", "row": [sym, pct(move), money(item.get("price")), (note + (" small" if item.get("small") else "")).strip()],
                "caption": "Prices in rupees", "source": YAHOO, "tags": stock_tags(item, "#Mover", extra)}
    if kind == "ipo":
        level = re.search(r"([\d,]+\.\d+)", " ".join(item.get("tags") or []))
        return {"title": "IPO BREAKOUTS", "header": ["Stock", "Move", "Price", "Level"], "aligns": "lrrr", "row": [sym, pct(item.get("move")), money(item.get("price")), level.group(1) if level else "-"],
                "caption": "Level is the listing-day high (breakout) or low (breakdown). Prices in rupees", "source": YAHOO, "tags": stock_tags(item, "#IPOBreakout")}
    if kind == "deal":
        return {"title": "BLOCK DEALS", "header": ["Stock", "Qty", "Price", "Value", "Chg"], "aligns": "lrrrr", "row": [sym, quantity(item.get("qty")), money(item.get("price")), crore(item.get("value")), pct(item.get("pchange"), 2)],
                "caption": "Chg is against the previous close. Prices in rupees. Buyer and seller are published after the close", "source": "NSE live block-deals feed", "tags": stock_tags(item, "#BlockDeal")}
    if kind == "bulk":
        return {"title": "BULK DEALS", "header": ["Stock", "Side", "Qty", "Price", "Value"], "aligns": "llrrr", "row": [sym, item.get("side", ""), quantity(item.get("qty")), money(item.get("price")), crore(item.get("value"))],
                "notes": [f"{sym}: {item['client']}"] if item.get("client") else [], "caption": "Client names as the NSE publishes them. Prices in rupees", "source": "NSE large-deals file (published after the close)",
                "tags": stock_tags(item, "#BulkDeal", "#Buy" if item.get("side") == "BUY" else "#Sell")}
    if kind == "signal":
        levels = item.get("levels") or {}
        side = item.get("side")
        word = "BULLISH" if side == "buy" else "BEARISH" if side == "sell" else "MIXED"
        notes = [f"{sym}: {alerts.compact(r)}" for r in (item.get("reasons") or [])[:2]]
        caption = "Ref = nearest reference level (resistance or support). Risk = volatility risk level. Prices in rupees"
        if notes:
            caption += chr(10) + "Key: " + alerts.LEGEND
        return {"title": f"{word} READINGS, {'WEEKS' if item.get('horizon') == 'short' else 'MONTHS-TO-YEARS'} VIEW", "header": ["Stock", "Score", "Price", "Ref", "Risk"], "aligns": "lrrrr",
                "row": [sym, f"{item['score']:+d}" if isinstance(item.get("score"), int) else "-", money(item.get("price")), money(levels.get("price")), money(levels.get("risk_price"))],
                "notes": notes, "caption": caption, "source": YAHOO, "tags": stock_tags(item, "#Bullish" if side == "buy" else "#Bearish" if side == "sell" else "#Mixed", "#WeeksView" if item.get("horizon") == "short" else "#LongTerm")}
    if kind == "entry" and stats:
        if "ratio" in stats:
            notes = [p for p in item.get("points", []) if p.startswith("Earlier reading alert")]
            return {"title": "VOLATILITY BREACHES", "header": ["Stock", "Move", "x Range", "Price", "Prev"], "aligns": "lrrrr", "row": [sym or short(item.get("heading", "").split(":")[0]), pct(stats["move_pct"]),
                    f"{stats['ratio']:.1f}x", money(stats["price"]), money(stats["previous"])], "notes": [f"{(sym or '')}: {n}" for n in notes],
                    "caption": f"x Range = today's move over its 14-day average daily range (ATR {money(stats['atr'])}). Beyond 2x is unusually large. Prices in rupees", "source": YAHOO, "tags": item.get("tags")}
        if "status" in stats:
            return {"title": "UPCOMING IPOS", "header": ["IPO", "Open-Close", "Price", "Sub", "GMP"], "aligns": "lrrrr",
                    "row": [str(stats.get("name") or "")[:10], day_range(stats.get("open"), stats.get("close")), money(stats.get("price")),
                            f"{stats['sub']:.1f}x" if isinstance(stats.get("sub"), (int, float)) else "-", pct(stats.get("gmp_pct"), 0) if stats.get("gmp_pct") is not None else "-"],
                    "notes": [f"{str(stats.get('name'))[:10]}: {stats['status']}, lists {one_day(stats.get('listing'))}"], "caption": "Sub = subscription so far. GMP = grey-market premium, unofficial. Price in rupees",
                    "source": "Investorgain and the exchanges", "tags": item.get("tags")}
        if "ex" in stats:
            return {"title": "SHARE ACTIONS COMING UP", "header": ["Stock", "Action", "Ex-date", "Record"], "aligns": "llrr", "row": [sym, stats["label"][:12], (stats.get("ex") or "-")[5:], (stats.get("record") or "-")[5:]],
                    "caption": "Dates are month-day", "source": "NSE corporate actions (official)", "tags": item.get("tags")}
        if "last" in stats:
            return {"title": item.get("title") or "INDEX ALERT", "header": ["Index", "Level", "Move"], "aligns": "lrr", "row": [stats["name"], f"{stats['last']:,.2f}", ", ".join(stats.get("tags") or [])],
                    "notes": [stats["hint"]] if stats.get("hint") else [], "caption": "", "source": stats.get("source") or "NSE", "tags": item.get("tags")}
        if "kv" in stats:
            return {"title": "WEEKLY SUMMARY, TRACK RECORD", "header": ["Measure", "Value"], "aligns": "lr", "rows": stats["kv"], "notes": item.get("points") or [], "caption": "", "source": "the app's track-record ledger",
                    "tags": item.get("tags")}
    if kind == "line" and stats:
        if "band" in stats:
            return {"title": item.get("title"), "header": ["Stock", "Band", "Price", "Day", "Turnover"], "aligns": "lrrrr", "row": [sym, f"{stats['band']:g}%", money(stats["price"]), pct(stats["move_pct"]), crore(stats["turnover"])],
                    "caption": "Prices in rupees", "source": "NSE price-band feed", "tags": item.get("tags")}
        if "gap_pct" in stats:
            return {"title": item.get("title"), "header": ["Stock", "Gap", "Open", "Prev", "Now"], "aligns": "lrrrr", "row": [sym, pct(stats["gap_pct"]), money(stats.get("open")), money(stats.get("prev")), money(stats["price"])],
                    "caption": "Gap is the open against the previous close. Prices in rupees", "source": YAHOO, "tags": item.get("tags")}
    return None


def render_table(header, rows, aligns):
    """The rows as aligned monospace text (columns padded to their widest cell)."""
    every = [header] + [list(map(str, r)) for r in rows]
    widths = [max(len(str(r[c])) for r in every) for c in range(len(header))]
    lines = []
    for r in every:
        cells = [str(v).ljust(widths[c]) if aligns[c] == "l" else str(v).rjust(widths[c]) for c, v in enumerate(r)]
        lines.append("  ".join(cells).rstrip())
    return "<pre>" + esc("\n".join(lines)) + "</pre>"


def group_block(group):
    """A table of consecutive rows with the same title and columns, then its notes, caption, source and the hashtags of all its rows."""
    notes = [n for g in group["items"] for n in g.get("notes", [])]
    tags = list(dict.fromkeys(t for g in group["items"] for t in (g.get("tags") or [])))[:MAX_TABLE_TAGS]        # a long table does not get a hashtag line as long as itself
    rows = [r for g in group["items"] for r in (g.get("rows") or [g["row"]])]
    first = group["items"][0]
    parts = [render_table(first["header"], rows, first["aligns"])]
    if notes:
        parts.append(chr(10).join(esc(n) for n in notes))
    if first.get("caption"):
        parts.append(esc(first["caption"]))
    parts.append(esc("Source: " + first["source"]) + tag_line(tags))
    return chr(10).join(parts)


def _section(item):
    kind = item["kind"]
    if kind == "mover":                                  # movers are shown as rising or falling
        return "━━ RISING ━━" if (item.get("move") or 0) >= 0 else "━━ FALLING ━━"
    title = item.get("title") if kind in ("table", "entry", "line") and item.get("title") else SECTION_OF.get(kind, digest.NEWS_TITLE)
    return title if str(title).startswith("━") else f"━━ {title} ━━"


def render_feed(items, links, now_ts, label, feed_tags=(), icon="\U0001F4CA", max_chars=None, max_messages=digest.MAX_MESSAGES):
    """[(text, start, end)]: the messages of one feed, in Telegram HTML. start and end are positions in items (end exclusive)."""
    max_chars = max_chars or alerts.TELEGRAM_MAX_CHARS
    if not items:
        return []
    when = datetime.fromtimestamp(now_ts, digest.IST).strftime("%a %d %b, %H:%M IST")
    has_signal = any(i["kind"] == "signal" for i in items)           # the "levels are indicative" note belongs to readings only

    shaped = {}

    def row_of(index):
        if index not in shaped:
            shaped[index] = to_row(items[index])
        return shaped[index]

    def body(chunk):
        parts, last, number = [], None, 0              # (text, is one line) so one-line items sit on consecutive lines
        group = None
        for index in chunk:
            item = items[index]
            link = links[index] if links and index < len(links) else None
            row = row_of(index)
            if row:
                key = (row["title"], tuple(row["header"]))
                if group and group["key"] == key:
                    group["items"].append(row)
                    continue
                if group:
                    parts.append((group_block(group), False))
                section = row["title"] if str(row["title"]).startswith("━") else f"━━ {row['title']} ━━"
                parts.append((section, False))
                group, last, number = {"key": key, "items": [row]}, section, 0
                continue
            if group:
                parts.append((group_block(group), False))
                group = None
            section = _section(item)
            if section != last:
                parts.append((section, False))
                last, number = section, 0
            number += 1
            kind = item["kind"]
            if kind == "table":
                parts.append((table_block(item), False))
            elif kind == "filing":
                parts.append((list_item(number, filing_card(item), stock_tags(item, "#Filing")), False))
            elif kind == "entry":
                parts.append((list_item(number, entry_card(item, link), item.get("tags")), False))
            else:
                parts.append((line_item(number, item), True))
        if group:
            parts.append((group_block(group), False))
        text = ""
        for position, (part, one_line) in enumerate(parts):
            if position:
                text += chr(10) if one_line and parts[position - 1][1] else digest.NL2
            text += part
        return text

    def build(chunk, number, parts, left_out):
        suffix = f" ({number}/{parts})" if parts > 1 else ""
        head = f"{icon} <b>{esc(label)}</b> · {when}{suffix}"
        tags = " ".join(esc(t) for t in feed_tags)
        text = head + ("\n" + tags if tags else "") + digest.NL2 + body(chunk)
        if number == parts and left_out:
            text += f"{digest.NL2}+{left_out} more. Open the app to see them."
        return text + digest.NL2 + (digest.FOOTER if has_signal else html.escape(alerts.ADVISORY))

    chunks, current = [], []
    for index in range(len(items)):
        trial = current + [index]
        if current and alerts.visible_length(build(trial, max_messages, max_messages, 99999)) > max_chars:     # measured with the longest suffix and the "more" line, so it always fits
            chunks.append(current)
            current = [index]
        else:
            current = trial
    if current:
        chunks.append(current)
    kept = chunks[:max_messages]
    left_out = len(items) - sum(len(c) for c in kept)
    return [(build(chunk, number, len(kept), left_out), chunk[0], chunk[-1] + 1) for number, chunk in enumerate(kept, 1)]
