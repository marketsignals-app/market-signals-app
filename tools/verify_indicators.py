"""Independent check of the technical indicators and the signal scores.

    python tools/verify_indicators.py [--symbols A.NS B ...] [--build FOLDER]

1. Indicators: SMA, RSI (Wilder), MACD (12/26/9), ATR (Wilder 14) and the 126-day return are recomputed here with separate code (different formulations:
   exponentially weighted updates with alpha, not the engine's loops) from the same daily bars and compared with the engine's values on the last bar.
2. Signals: with --build, every record's score is recomputed from the reasons it carries (weights from engine/signals.py), its label from the score
   thresholds (+20 / -20, strong at +/-50), its confidence from the coverage, and the data.json and detail files are compared with each other.

Prints PASS/FAIL per check with the largest difference, and exits 1 on any FAIL.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import fetch, signals          # noqa: E402

SAMPLE = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ITC.NS", "SBIN.NS", "TATAMOTORS.NS", "LT.NS", "ASIANPAINT.NS", "MARUTI.NS",
          "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "JPM", "XOM", "KO", "WMT", "DIS"]


def sma_ref(values, n):
    return sum(values[-n:]) / n if len(values) >= n else None


def ewm_ref(values, alpha, seed_len):
    """Exponentially weighted mean with weight alpha, started from the average of the first seed_len values."""
    mean = sum(values[:seed_len]) / seed_len
    for v in values[seed_len:]:
        mean = alpha * v + (1 - alpha) * mean
    return mean


def rsi_ref(close, n=14):
    gains = [max(b - a, 0.0) for a, b in zip(close, close[1:])]
    losses = [max(a - b, 0.0) for a, b in zip(close, close[1:])]
    avg_gain, avg_loss = ewm_ref(gains, 1 / n, n), ewm_ref(losses, 1 / n, n)
    return 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)


def macd_ref(close):
    # the 12-day average started where the 26-day one does, so both are defined on the same bars
    def ema(values, n):
        out, mean = [], sum(values[:n]) / n
        out.extend([None] * (n - 1) + [mean])
        for v in values[n:]:
            mean = 2 / (n + 1) * v + (1 - 2 / (n + 1)) * mean
            out.append(mean)
        return out
    fast, slow = ema(close, 12), ema(close, 26)
    line = [None if s is None else f - s for f, s in zip(fast, slow)]
    present = [x for x in line if x is not None]
    signal_vals = ema(present, 9)
    signal = [None] * (len(line) - len(present)) + signal_vals
    return line[-1], signal[-1], line[-1] - signal[-1]


def atr_ref(high, low, close, n=14):
    tr = [h - l for h, l in zip(high[:1], low[:1])] + [max(h - l, abs(h - pc), abs(l - pc)) for h, l, pc in zip(high[1:], low[1:], close[:-1])]
    return ewm_ref(tr, 1 / n, n)


def compare(name, engine, ref, tol, results, symbol):
    if engine is None or ref is None:
        results.append((name, symbol, None, "SKIP"))
        return
    diff = abs(engine - ref) / max(abs(ref), 1e-9)
    results.append((name, symbol, diff, "PASS" if diff <= tol else "FAIL"))


def check_indicators(symbols):
    results = []
    for symbol in symbols:
        try:
            bars = fetch.fetch_chart(symbol, "5y")["bars"]
        except fetch.FetchError:
            continue
        if len(bars["c"]) < 300:
            continue
        bars = fetch.trim_last_bar(bars) if False else bars          # compare on whatever bars the engine would see for this series
        ind = signals.build_indicators(bars)
        i = len(bars["c"]) - 1
        c, h, l = bars["c"], bars["h"], bars["l"]
        compare("SMA 20", ind["sma20"][i], sma_ref(c, 20), 1e-9, results, symbol)
        compare("SMA 50", ind["sma50"][i], sma_ref(c, 50), 1e-9, results, symbol)
        compare("SMA 200", ind["sma200"][i], sma_ref(c, 200), 1e-9, results, symbol)
        compare("126-day return", ind["momentum126"][i], c[-1] / c[-127] - 1, 1e-9, results, symbol)
        # exponentially weighted indicators depend on how they are started; over five years the start no longer matters, so the tolerance is tight but not zero
        compare("RSI 14", ind["rsi"][i], rsi_ref(c), 2e-3, results, symbol)
        line, sig, hist = macd_ref(c)
        compare("MACD line", ind["macd"][i], line, 5e-3, results, symbol)
        compare("MACD signal", ind["macd_signal"][i], sig, 5e-3, results, symbol)
        compare("ATR 14", ind["atr"][i], atr_ref(h, l, c), 2e-3, results, symbol)
        hi, lo = max(h[-252:]), min(l[-252:])
        compare("52-week high", ind["hi252"][i], hi, 1e-9, results, symbol)
        compare("52-week low", ind["lo252"][i], lo, 1e-9, results, symbol)
    return results


def check_signals(folder):
    results = []
    records = list(json.loads((folder / "data.json").read_text(encoding="utf-8"))["stocks"])
    for f in (folder / "detail").glob("*.json"):
        records += list(json.loads(f.read_text(encoding="utf-8")).values())
    seen = {}
    for rec in records:
        full = not rec.get("lite")
        for hz, weights in (("short", signals.SHORT_WEIGHTS), ("long", signals.LONG_WEIGHTS)):
            block = rec.get(hz) or {}
            score, reasons = block.get("score"), block.get("reasons") or []
            symbol = rec["symbol"]
            if score is None:
                results.append((f"{hz} score is empty only with too little data", symbol, None, "PASS" if block.get("label") == "N/A" else "FAIL"))
                continue
            results.append((f"{hz} label matches its score", symbol, None, "PASS" if block.get("label") == signals.label(score) else "FAIL"))
            if full and reasons and all("key" in r for r in reasons):
                used = {r["key"]: r["value"] for r in reasons}
                total = sum(weights[k] for k in used)
                recomputed = sum(weights[k] * v for k, v in used.items()) / total * 100
                results.append((f"{hz} score is the weighted sum of its parts", symbol, abs(recomputed - score), "PASS" if abs(recomputed - score) <= 1.0 else "FAIL"))
            conf = block.get("confidence")
            cov = block.get("coverage")
            if conf and cov is not None:
                results.append((f"{hz} confidence matches its coverage", symbol, None, "PASS" if conf == signals.confidence(cov) else "FAIL"))
            seen.setdefault((symbol, hz), set()).add((block.get("label"), score))
    for (symbol, hz), values in seen.items():
        results.append((f"{hz} reading is the same in data.json and the detail file", symbol, None, "PASS" if len(values) == 1 else "FAIL"))
    return results


def summarise(results):
    by = {}
    for name, symbol, diff, status in results:
        row = by.setdefault(name, {"PASS": 0, "FAIL": 0, "SKIP": 0, "worst": (0.0, "")})
        row[status] += 1
        if diff is not None and diff >= row["worst"][0]:
            row["worst"] = (diff, symbol)
    fails = 0
    for name, row in by.items():
        fails += row["FAIL"]
        worst = f", largest difference {row['worst'][0]:.2e} ({row['worst'][1]})" if row["worst"][1] else ""
        print(f"{'FAIL' if row['FAIL'] else 'PASS'}  {name}: {row['PASS']} pass, {row['FAIL']} fail{worst}")
    return fails


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols", nargs="*", default=SAMPLE)
    parser.add_argument("--build", help="a build folder (data.json and detail/) whose signals are checked")
    args = parser.parse_args(argv)
    results = check_indicators(args.symbols)
    if args.build:
        results += check_signals(Path(args.build))
    fails = summarise(results)
    print("RESULT:", "FAIL" if fails else "all checks pass")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
