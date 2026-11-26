"""Figures worked out from what is already fetched (Yahoo gives four annual figures, so three-year rates are the longest that can be stated): growth rates and cash ratios from the annual statements, debt and valuation ratios from the
fundamentals, and relative strength against the benchmark index.

Each function returns None rather than a number it cannot stand behind: a rate needs both ends of the period to exist and to be positive, a ratio needs
a positive denominator, and figures are only combined when they belong to the same fiscal year. A financial company (a bank, an insurer, a lender) is
flagged because debt, current ratio, cash flow and EBITDA mean something different for it, and rules treat those figures as not applicable."""
from datetime import date

ANNUAL_TOLERANCE_DAYS = 60      # fiscal year ends drift a little between years
STALE_DAYS = 600                # the newest annual figure must be less than about 20 months old


def _rows(statements, name):
    """[(date, value)] of one annual series, oldest first, numbers only."""
    out = []
    for row in ((statements or {}).get("annual") or {}).get(name) or []:
        value = row.get("value") if isinstance(row, dict) else None
        if isinstance(value, (int, float)) and not isinstance(value, bool) and row.get("date"):
            try:
                out.append((date.fromisoformat(row["date"]), float(value)))
            except ValueError:
                continue
    return sorted(out)


def _at(rows, day):
    """The value whose date is within the tolerance of the day, or None."""
    best = None
    for when, value in rows:
        gap = abs((when - day).days)
        if gap <= ANNUAL_TOLERANCE_DAYS and (best is None or gap < best[0]):
            best = (gap, value)
    return best[1] if best else None


def cagr(rows, years, today=None):
    """Compound annual growth in percent over the years ending at the newest annual figure. None when either end is missing or not positive, or when the
    newest figure is stale (growth of a loss, or from a loss, has no meaning as a rate)."""
    if not rows:
        return None
    last_day, end = rows[-1]
    if today and (today - last_day).days > STALE_DAYS:
        return None
    try:
        start = _at(rows, date(last_day.year - years, last_day.month, min(last_day.day, 28)))
    except ValueError:
        return None
    if start is None or start <= 0 or end <= 0:
        return None
    return round(((end / start) ** (1 / years) - 1) * 100, 1)


def profit_up_years(rows, window=3):
    """How many of the last `window` year-on-year changes in annual net profit were increases (0 to window). Needs window + 1 years in a row."""
    if len(rows) < window + 1:
        return None
    last = rows[-(window + 1):]
    if any(abs((last[k + 1][0] - last[k][0]).days - 365) > ANNUAL_TOLERANCE_DAYS for k in range(window)):
        return None                                   # a missing year would make "in a row" untrue
    return sum(1 for k in range(window) if last[k + 1][1] > last[k][1])


def ocf_to_profit(statements):
    """Operating cash flow divided by net profit for the newest year both exist, when the profit is positive."""
    ocf, profit = _rows(statements, "operating_cash_flow"), _rows(statements, "net_income")
    if not ocf or not profit:
        return None
    day = profit[-1][0]
    flow = _at(ocf, day)
    if flow is None or profit[-1][1] <= 0:
        return None
    return round(flow / profit[-1][1], 2)


def roce_approx(statements):
    """Operating income over equity plus debt for the newest year all three exist, in percent. An approximation: the textbook capital employed also
    removes current liabilities, which are not fetched."""
    ebit, equity, debt = _rows(statements, "operating_income"), _rows(statements, "equity"), _rows(statements, "total_debt")
    if not ebit or not equity:
        return None
    day = ebit[-1][0]
    capital_equity, capital_debt = _at(equity, day), (_at(debt, day) if debt else 0.0)
    if capital_equity is None or capital_debt is None or capital_equity + capital_debt <= 0:
        return None
    return round(ebit[-1][1] / (capital_equity + capital_debt) * 100, 1)


def currency_ok(record):
    """True when the statements are in the currency the price is quoted in. Amounts from the statements (cash flow, EBITDA) can only be set against the
    market cap or enterprise value then: a company that reports in dollars while its shares trade in rupees (Infosys) would give a ratio out by the exchange
    rate. Yahoo's own EV/EBITDA and free cash flow figures were seen to mix currencies in the same way, so they are not used for ratios."""
    statement_currency = (record.get("statements") or {}).get("currency")
    price_currency = record.get("currency") or ("INR" if (record.get("symbol") or "").endswith(".NS") else None)
    return bool(statement_currency) and statement_currency == price_currency


def _latest(statements, name, today=None):
    rows = _rows(statements, name)
    if not rows or (today and (today - rows[-1][0]).days > STALE_DAYS):
        return None
    return rows[-1]


def debt_to_ebitda(statements, today=None):
    """Total debt over EBITDA of the same fiscal year, both from the annual statements (so in one currency, whichever it is)."""
    ebitda = _latest(statements, "ebitda", today)
    if not ebitda or ebitda[1] <= 0:
        return None
    debt = _at(_rows(statements, "total_debt"), ebitda[0])
    return round(debt / ebitda[1], 2) if debt is not None and debt >= 0 else None


def ev_to_ebitda(record, today=None):
    """Enterprise value over the newest annual EBITDA. Only when the statements are in the price currency."""
    ebitda, ev = _latest(record.get("statements"), "ebitda", today), (record.get("fundamentals") or {}).get("enterprise_value")
    if not currency_ok(record) or not ebitda or ebitda[1] <= 0 or not isinstance(ev, (int, float)) or ev <= 0:
        return None
    return round(ev / ebitda[1], 1)


def price_to_fcf(record, today=None):
    """Market cap over the newest annual free cash flow, when that is positive and in the price currency."""
    fcf, cap = _latest(record.get("statements"), "free_cash_flow", today), (record.get("fundamentals") or {}).get("market_cap")
    if not currency_ok(record) or not fcf or fcf[1] <= 0 or not isinstance(cap, (int, float)) or cap <= 0:
        return None
    return round(cap / fcf[1], 1)


def fcf_crore(record, today=None):
    """The newest annual free cash flow in rupees crore (any sign), for NSE stocks whose statements are in rupees."""
    fcf = _latest(record.get("statements"), "free_cash_flow", today)
    if not currency_ok(record) or not fcf or not (record.get("symbol") or "").endswith(".NS"):
        return None
    return round(fcf[1] / 1e7, 1)


def is_financial(fundamentals):
    return ((fundamentals or {}).get("sector") or "") == "Financial Services"


def relative_strength(dates, closes, bench_by_date, sessions=126):
    """The stock's return over the last `sessions` sessions minus the benchmark's over the same dates, in percentage points. None unless both ends
    have a benchmark close within three days."""
    if len(closes) <= sessions or len(dates) != len(closes) or not bench_by_date:
        return None
    first_day, last_day = dates[-(sessions + 1)], dates[-1]

    def bench(day):
        target = date.fromisoformat(day)
        best = None
        for key, value in bench_by_date.items():
            gap = (target - date.fromisoformat(key)).days
            if 0 <= gap <= 3 and (best is None or gap < best[0]):
                best = (gap, value)
        return best[1] if best else None
    start, end = bench(first_day), bench(last_day)
    if not start or not end or closes[-(sessions + 1)] <= 0:
        return None
    return round(((closes[-1] / closes[-(sessions + 1)] - 1) - (end / start - 1)) * 100, 1)


def correct_fundamentals(record, today=None):
    """Replace Yahoo's EV/EBITDA, which mixes currencies for some companies (Infosys 934, HCL Tech 1333), with the one worked out here from the statements, or
    remove it when that cannot be done. Changes the record's own fundamentals; running it again changes nothing."""
    fundamentals = record.get("fundamentals")
    if not isinstance(fundamentals, dict) or "ev_ebitda" not in fundamentals or not (record.get("statements") or {}).get("annual"):
        return                                       # without statements there is nothing to check Yahoo's figure against, so it stays
    own = ev_to_ebitda(record, today)
    if own is None:
        del fundamentals["ev_ebitda"]
    else:
        fundamentals["ev_ebitda"] = own


def derive(record, today=None):
    """{name: number} of the figures above for one record (fundamentals and statements attached). Names with no value are left out."""
    fundamentals, statements = record.get("fundamentals") or {}, record.get("statements") or {}
    revenue, profit, eps = _rows(statements, "revenue"), _rows(statements, "net_income"), _rows(statements, "eps")
    yoy = ((statements.get("summary") or {}).get("yoy") or {})
    values = {
        "rev_cagr3": cagr(revenue, 3, today), "profit_cagr3": cagr(profit, 3, today), "eps_cagr3": cagr(eps, 3, today),
        "profit_up_years": profit_up_years(profit), "ocf_to_profit": ocf_to_profit(statements), "roce": roce_approx(statements),
        "op_growth": yoy.get("operating_income"), "debt_to_ebitda": debt_to_ebitda(statements, today), "price_to_fcf": price_to_fcf(record, today),
        "ev_ebitda": ev_to_ebitda(record, today), "fcf_cr": fcf_crore(record, today),
    }
    return {k: v for k, v in values.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
