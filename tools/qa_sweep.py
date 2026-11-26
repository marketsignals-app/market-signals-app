"""Data and file checks on a build folder, so one run finds what would otherwise be found one report at a time.

    python tools/qa_sweep.py PATH_TO_BUILD_FOLDER      (the folder holding data.json, index.json and detail/)

Prints every defect found, grouped, with the symbols affected, and exits 1 if any "FAIL" was found. "WARN" lines are things to look at, not blockers.
See docs/release-checklist.md for what each check is for.
"""
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

LIMITS = {"data.json": 1600 * 1024, "index.json": 1800 * 1024, "index_extra.json": 2000 * 1024, "detail": 700 * 1024}   # a shard holds ~70 stocks once the whole list is analysed; Pages serves it gzipped, one shard per stock page
HIGH_DIVIDEND = {"IN": 0.03, "US": 0.025}


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class Report:
    def __init__(self):
        self.items = defaultdict(list)

    def add(self, level, check, symbol, detail=""):
        self.items[(level, check)].append((symbol, detail))

    def show(self):
        fails = 0
        for (level, check), rows in sorted(self.items.items(), key=lambda kv: (kv[0][0] != "FAIL", kv[0][1])):
            fails += level == "FAIL"
            sample = "; ".join(f"{s} {d}".strip() for s, d in rows[:6])
            print(f"{level:4} {check}: {len(rows)}" + (f"  e.g. {sample}" if sample else ""))
        return fails


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def check_files(folder, rep):
    for name, limit in (("data.json", LIMITS["data.json"]), ("index.json", LIMITS["index.json"]), ("index_extra.json", LIMITS["index_extra.json"])):
        size = (folder / name).stat().st_size
        if size > limit:
            rep.add("FAIL", f"{name} is over its size budget", name, f"{size // 1024} KB > {limit // 1024} KB")
    for f in sorted((folder / "detail").glob("*.json")):
        if f.stat().st_size > LIMITS["detail"]:
            rep.add("FAIL", "a detail file is over its size budget", f.name, f"{f.stat().st_size // 1024} KB")


def check_rows(data, index, shards, rep):
    cur = {s["symbol"]: s for s in data["stocks"]}
    rows = {r["symbol"]: r for r in index["stocks"]}
    for symbol in set(cur) & set(rows):
        rep.add("FAIL", "a stock is in both data.json and index.json", symbol)
    if len(rows) != len(index["stocks"]) or len(cur) != len(data["stocks"]):
        rep.add("FAIL", "duplicate symbols inside a file", "")
    for symbol, s in {**cur, **rows}.items():
        if not finite(s.get("price")) or s["price"] <= 0:
            rep.add("FAIL", "price is not a positive number", symbol, str(s.get("price")))
        ch = s.get("change_pct")
        if finite(ch) and abs(ch) > 60:
            rep.add("WARN", "day change over 60% (check the quote)", symbol, f"{ch:+.1f}%")
        for key in ("name", "market"):
            if not s.get(key):
                rep.add("FAIL", f"missing {key}", symbol)
    # lite records against their full records, and index rows against their detail records
    for symbol, s in cur.items():
        full = shards.get(s.get("shard"), {}).get(symbol)
        if not full:
            rep.add("FAIL", "a main-list stock has no full record in its detail file", symbol)
            continue
        for hz in ("short", "long"):
            if (s[hz]["label"], s[hz]["score"]) != (full[hz]["label"], full[hz]["score"]):
                rep.add("FAIL", "reading differs between data.json and the detail file", symbol, hz)
    for symbol, r in rows.items():
        if r.get("analysed"):
            full = shards.get(r["shard"], {}).get(symbol)
            if not full:
                rep.add("FAIL", "an analysed stock has no record in its detail file", symbol)
                continue
            for hz in ("short", "long"):
                if (r[hz]["label"], r[hz]["score"]) != (full[hz]["label"], full[hz]["score"]):
                    rep.add("FAIL", "reading differs between index.json and the detail file", symbol, hz)
        elif r.get("short") or r.get("long"):
            rep.add("FAIL", "an unanalysed row carries a reading", symbol)
    counts = Counter(r["market"] for r in rows.values())
    print(f"rows: {len(cur)} main list, {len(rows)} others {dict(counts)}, analysed {sum(1 for r in rows.values() if r.get('analysed'))}")
    return cur, rows


def plausible_fundamentals(symbol, price, f, rep):
    pe, eps, pb, book = f.get("pe"), f.get("eps"), f.get("pb"), f.get("book_value")
    if finite(pe) and (pe <= 0 or pe > 2000):
        rep.add("WARN", "P/E outside 0 to 2000", symbol, f"{pe}")
    if finite(pe) and finite(eps) and eps > 0 and price and abs(price / eps / pe - 1) > 0.3:
        rep.add("WARN", "P/E does not match price / EPS (units or currency?)", symbol, f"pe {pe:.1f} vs {price / eps:.1f}")
    if finite(pb) and finite(book) and book > 0 and price and abs(price / book / pb - 1) > 0.3:
        rep.add("WARN", "P/B does not match price / book value", symbol, f"pb {pb:.2f} vs {price / book:.2f}")
    for key, low, high in (("roe", -5, 5), ("roa", -3, 3), ("profit_margin", -50, 1.01), ("operating_margin", -50, 1.01), ("current_ratio", 0, 500),
                           ("debt_to_equity", 0, 200), ("market_cap", 1, 1e15)):
        v = f.get(key)
        if finite(v) and not low <= v <= high:
            rep.add("WARN", f"{key} outside {low} to {high}", symbol, f"{v}")
    ev, ebitda, ratio = f.get("enterprise_value"), f.get("ebitda"), f.get("ev_ebitda")
    if all(finite(x) for x in (ev, ebitda, ratio)) and ebitda and abs(ev / ebitda / ratio - 1) > 0.3:
        rep.add("WARN", "EV/EBITDA does not match EV / EBITDA", symbol, f"{ratio:.1f} vs {ev / ebitda:.1f}")


def check_full_records(cur, rows, shards, rep):
    records = {s: r for sh in shards.values() for s, r in sh.items()}
    stats = Counter()
    for symbol, rec in records.items():
        price, market = rec.get("price"), rec.get("market")
        f = rec.get("fundamentals") or {}
        plausible_fundamentals(symbol, price, f, rep)
        ind = rec.get("indicators") or {}
        if finite(ind.get("rsi")) and not 0 <= ind["rsi"] <= 100:
            rep.add("FAIL", "RSI outside 0 to 100", symbol, str(ind["rsi"]))
        hi, lo = ind.get("hi252"), ind.get("lo252")
        if finite(hi) and finite(lo) and (hi < lo or price > hi * 1.2 or price < lo * 0.8):
            rep.add("WARN", "price far outside its own 52-week range", symbol, f"{price} vs {lo}-{hi}")
        d = rec.get("dividend")
        if d:
            stats["dividend"] += 1
            listed = sum(p["amount"] for p in d.get("ttm_payments", []))
            if d.get("ttm_payments") is not None and abs(listed - d["ttm_amount"]) > 1e-6 * max(1, d["ttm_amount"]):     # the published form may omit the payment list
                rep.add("FAIL", "12-month dividend is not the sum of the listed payments", symbol, f"{d['ttm_amount']} vs {listed}")
            if abs(d["ttm_yield"] - d["ttm_amount"] / price) > 2e-5:                  # the stored yield is rounded to 5 decimals
                rep.add("FAIL", "12-month yield is not amount / price", symbol)
            if d.get("ttm_regular_amount") is not None and d["ttm_regular_amount"] > d["ttm_amount"] + 1e-9:     # absent on records written before the field existed
                rep.add("FAIL", "recurring amount is above the 12-month amount", symbol)
            if d["ttm_yield"] > 0.5:
                rep.add("WARN", "dividend yield over 50% (a one-off or a data error?)", symbol, f"{d['ttm_yield']:.0%}")
            if d.get("payments_per_year") and d.get("forward_amount") is None and d.get("frequency") not in ("Irregular", "Single payment"):
                rep.add("WARN", "a pattern was found but no recurring amount", symbol)
            if isinstance(d.get("history"), list) and len(d["history"]) > 8:
                rep.add("FAIL", "dividend history is longer than its limit", symbol)
        check = rec.get("dividend_check")
        if check:
            stats["check_" + check["status"]] += 1
            if check["status"] == "differs" and not check.get("note"):
                rep.add("FAIL", "a dividend cross-check that differs has no note", symbol)
        elif d and rec.get("market"):
            stats["check_none"] += 1
        if "High dividend" in rec.get("lists", []):
            recurring = (d or {}).get("ttm_regular_yield")
            if recurring is not None and recurring < HIGH_DIVIDEND.get(market, 1) - 1e-9:       # a record from before the field existed has no recurring yield until it is re-analysed
                rep.add("FAIL", "in the High dividend list below its yield threshold", symbol, str(recurring))
        if not rec.get("short") or not rec.get("long"):
            rep.add("FAIL", "record without a reading", symbol)
    print("full records:", len(records), dict(stats))


def check_index_fields(rows, shards, rep, extra):
    for symbol, r in rows.items():
        if r.get("lists") and len(set(r["lists"])) != len(r["lists"]):
            rep.add("FAIL", "duplicate list names in a row", symbol)
        if r.get("series") not in (None, "BE", "BZ", "SME"):
            rep.add("FAIL", "unknown series", symbol, str(r.get("series")))
        y = r.get("dividend_yield")
        if finite(y) and (y < 0 or y > 1):
            rep.add("FAIL", "row dividend yield outside 0 to 100%", symbol, str(y))
        if r.get("analysed") and symbol not in extra:
            rep.add("WARN", "an analysed row has no entry in index_extra.json (no technical values for the filters)", symbol)
        if finite(r.get("high52")) and finite(r.get("low52")) and r["high52"] < r["low52"]:
            rep.add("FAIL", "52-week high below the low", symbol)


def main(argv):
    folder = Path(argv[1] if len(argv) > 1 else "site")
    rep = Report()
    data, index = load(folder / "data.json"), load(folder / "index.json")
    shards = {f.stem: load(f) for f in (folder / "detail").glob("*.json")}
    check_files(folder, rep)
    cur, rows = check_rows(data, index, shards, rep)
    check_full_records(cur, rows, shards, rep)
    check_index_fields(rows, shards, rep, load(folder / "index_extra.json").get("stocks", {}))
    status = data.get("status") or {}
    for c in status.get("checks", []):
        if c.get("state") not in ("ok", "info"):
            rep.add("WARN", "status check is not ok", c.get("name"), c.get("state") + " " + str(c.get("detail", ""))[:80])
    fails = rep.show()
    print("RESULT:", "FAIL" if fails else "no failures")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
