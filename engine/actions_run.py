"""Fetches what the NSE publishes about corporate actions, circuits, surveillance and the F&O ban, and turns it into the records of engine/actions.py.

Each source is read at most as often as it changes: the price-band lists every run while the market is open, the others once an hour. Every request goes through
sessions.Source (shared refusal handling: a 401 or 403 pauses the source, nothing is worked around), so a source that is down never stops the others or the build.
"""
from datetime import datetime, timedelta, timezone

from . import actions, sessions
from .fetch import http_get

IST = timezone(timedelta(hours=5, minutes=30))
CORPORATE_ACTIONS = "https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date={start}&to_date={end}"
BANDS = "https://www.nseindia.com/api/live-analysis-price-band-hitter?index={side}"
ASM = "https://www.nseindia.com/api/reportASM"
GSM = "https://www.nseindia.com/api/reportGSM"
FO_BAN = "https://nsearchives.nseindia.com/content/fo/fo_secban.csv"
HOURLY = 55                     # minutes between reads of the slow sources
SOURCE_NAMES = {"corpact": "NSE corporate actions", "bands_upper": "NSE price bands (upper)", "bands_lower": "NSE price bands (lower)", "asm": "NSE ASM list", "gsm": "NSE GSM list",
                "secban": "NSE F&O ban list"}


def _due(state, now, minutes):
    """True when the source has not been read for `minutes` minutes (or never)."""
    try:
        last = datetime.fromisoformat((state or {}).get("fetched_at") or "")
    except (TypeError, ValueError):
        return True
    return (now - last).total_seconds() >= minutes * 60


def _read(nse, key, url, now, minutes, text=False, getter=http_get):
    """(payload or None, whether it was read this run). The state of the source is kept in nse[key]."""
    if not _due(nse.get(key), now, minutes):
        return None, False
    source = sessions.Source(SOURCE_NAMES[key], url)
    source.text = text
    payload, nse[key] = source.fetch(now, nse.get(key), getter=getter)
    return payload, payload is not None


def collect(now, now_ts, nse, news_items, quotes, market_of, india_open, movers, names, memory, cfg=None, getter=http_get):
    """(records, state to remember {"surv_state", "ban_state"}). nse is the shared source-state dict (updated in place). memory has the last surveillance and ban states."""
    cfg = cfg or {}
    today = now.astimezone(IST).date()
    today_iso = today.isoformat()
    minutes_of_day = now.astimezone(IST).hour * 60 + now.astimezone(IST).minute
    records = actions.announcement_records(news_items, now_ts)
    remembered = {"surv_state": memory.get("surv_state"), "ban_state": memory.get("ban_state")}

    window = CORPORATE_ACTIONS.format(start=(today - timedelta(days=2)).strftime("%d-%m-%Y"), end=(today + timedelta(days=30)).strftime("%d-%m-%Y"))
    payload, read = _read(nse, "corpact", window, now, HOURLY, getter=getter)
    if read:
        records += actions.corporate_action_records(payload, now_ts)

    if india_open:
        circuit = cfg.get("circuits") or {}
        upper, got_upper = _read(nse, "bands_upper", BANDS.format(side="upper"), now, 0, getter=getter)
        lower, got_lower = _read(nse, "bands_lower", BANDS.format(side="lower"), now, 0, getter=getter)
        if got_upper or got_lower:
            records += actions.circuit_records(upper, lower, now_ts, today_iso, min_band=float(circuit.get("min_band", 5)), min_turnover=float(circuit.get("min_turnover_crore", 1)) * 1e7)
        if 9 * 60 + 15 <= minutes_of_day <= 10 * 60 + 30:
            records += actions.gap_records(quotes, market_of, now_ts, today_iso, min_gap=float((cfg.get("gaps") or {}).get("min_gap", 3)))
        records += actions.surge_crash_records(movers, names, now_ts, today_iso)

    asm, got_asm = _read(nse, "asm", ASM, now, HOURLY, getter=getter)
    gsm, got_gsm = _read(nse, "gsm", GSM, now, HOURLY, getter=getter)
    if got_asm and got_gsm:                                       # both lists are needed: a half read would look like removals
        changes, remembered["surv_state"] = actions.surveillance_records(asm, gsm, memory.get("surv_state"), now_ts, today_iso)
        records += changes
    ban, got_ban = _read(nse, "secban", FO_BAN, now, HOURLY, text=True, getter=getter)
    if got_ban:
        changes, remembered["ban_state"] = actions.fo_ban_records(ban, memory.get("ban_state"), now_ts, today_iso)
        records += changes
    return records, remembered


def source_status(nse):
    """The state of each source for the Announcements tab: [{"name", "ok", "fetched_at", "error"}]."""
    out = []
    for key, name in SOURCE_NAMES.items():
        state = nse.get(key) or {}
        out.append({"name": name, "ok": bool(state.get("ok")), "fetched_at": state.get("fetched_at"), "error": state.get("error")})
    return out
