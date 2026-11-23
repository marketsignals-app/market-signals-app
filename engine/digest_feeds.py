"""The messages of the scheduled feeds (engine/feeds.py), in three styles. Cards that already exist in engine/digest.py are reused.

  A  a numbered heading with sub-points: readings, important filings, entries (volatility alert, upcoming IPOs, events, weekly summary)
  B  one numbered line per item, figures inline: movers, IPO breakouts, block deals, headlines, news lines
  C  a monospace table: indexes, commodities, sectors

Every message has a bold title with the IST time, its hashtags, sections of numbered entries (numbering restarts in each section) and the advisory footer.
Every entry carries hashtags (the stock symbol, the kind of alert) so they can be searched in Telegram.
"""
import html
from datetime import datetime

from . import alerts, digest, feed_items

esc = html.escape
NBSP = chr(160)                    # a no-break space: Telegram keeps it, so the sub-points stay indented
SECTION_OF = {"signal": digest.READINGS_TITLE, "deal": digest.DEALS_TITLE, "mover": digest.MOVERS_TITLE, "low52": digest.LOW_TITLE, "ipo": "━━ IPO BREAKOUTS ━━",
              "brief": digest.BRIEF_TITLE, "news": digest.NEWS_TITLE, "bulk": "━━ BULK DEALS ━━", "filing": "━━ IMPORTANT FILINGS ━━"}
ICONS = {"readings": "\U0001F7E2", "movers": "\U0001F4C8", "ipo_breakout": "\U0001F680", "deals": "\U0001F9F1", "filings": "\U0001F4D1", "news": "\U0001F4F0", "indexes": "\U0001F4CA",
         "commodities": "\U0001F6E2", "sectors": "\U0001F9ED", "news_digest": "\U0001F5DE", "ipo_upcoming": "\U0001F4C5", "events_today": "\U0001F5D3", "weekly": "\U0001F4C6",
         "bulk_deals": "📦", "volatility": "⚡", "urgent": "⚠️"}


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
    if isinstance(item.get("sentiment"), (int, float)):
        lines.append(f"{digest.BULLET} Rule-based reading: sentiment {item['sentiment']:+d}, impact {item.get('impact')} (official source, not a signal)")
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
        tags = stock_tags(item, "#Mover" if kind == "mover" else "#52WeekLow")
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
        read = f" {alerts.anchor(item['link'], 'Read')}" if str(item.get("link") or "").startswith("https://") else ""
        body = f"<b>{esc(item['name'])}</b>: {esc(digest.quiet(digest._clip(item['title'], 150)))} ({source}, {age}){read}"
        tags = stock_tags(item, "#News")
    else:
        read = f" {alerts.anchor(item['link'], 'Read')}" if str(item.get("link") or "").startswith("https://") else ""
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


def _section(item):
    kind = item["kind"]
    title = item.get("title") if kind in ("table", "entry", "line") and item.get("title") else SECTION_OF.get(kind, digest.NEWS_TITLE)
    return title if str(title).startswith("━") else f"━━ {title} ━━"


def render_feed(items, links, now_ts, label, feed_tags=(), icon="\U0001F4CA", max_chars=None, max_messages=digest.MAX_MESSAGES):
    """[(text, start, end)]: the messages of one feed, in Telegram HTML. start and end are positions in items (end exclusive)."""
    max_chars = max_chars or alerts.TELEGRAM_MAX_CHARS
    if not items:
        return []
    when = datetime.fromtimestamp(now_ts, digest.IST).strftime("%a %d %b, %H:%M IST")
    has_signal = any(i["kind"] == "signal" for i in items)           # the "levels are indicative" note belongs to readings only

    def body(chunk):
        parts, last, number = [], None, 0              # (text, is one line) so one-line items sit on consecutive lines
        for index in chunk:
            item = items[index]
            link = links[index] if links and index < len(links) else None
            section = _section(item)
            if section != last:
                parts.append((section, False))
                last, number = section, 0
            number += 1
            kind = item["kind"]
            if kind == "table":
                parts.append((table_block(item), False))
            elif kind == "signal":
                side = "#Bullish" if item["side"] == "buy" else "#Bearish" if item["side"] == "sell" else "#Mixed"
                parts.append((list_item(number, digest.reading_card(item, link), stock_tags(item, side, "#WeeksView" if item["horizon"] == "short" else "#LongTerm")), False))
            elif kind == "filing":
                parts.append((list_item(number, filing_card(item), stock_tags(item, "#Filing")), False))
            elif kind == "entry":
                parts.append((list_item(number, entry_card(item, link), item.get("tags")), False))
            else:
                parts.append((line_item(number, item), True))
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
