"""The scheduled job that asks a hosted language model about new headlines: python -m engine.news_ai [--publish] [--max-requests N] [--dry-run]

Reads the same providers as the build (engine/news_sources.py), keeps the headlines about tracked stocks that carry information (routine filings are
skipped), asks the model (engine/ai_sentiment.py) only about headlines it has not scored before, and stores the answers on the `data` branch:

    news-ai/scores-YYYY-MM.jsonl     every score ever stored (append-only)
    news-ai/scores-recent.json       the last 96 hours, read by the 10-minute build

Needs the job's own GITHUB_TOKEN with `models: read` (see .github/workflows/news-ai.yml). Without a token, or when the model refuses or is over its free
limit, the job stops cleanly and the build keeps using the rule-based score. Exit code is 0 either way: a missing AI layer is not a failed deploy.
"""
import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import ai_sentiment, fetch, ledger_git, news_intel, news_sources          # noqa: E402

RECENT_HOURS = 96
SKIP_EVENTS = {"routine", "investor_call", "volume"}
RAW_URL = "https://raw.githubusercontent.com/{repo}/data/news-ai/scores-recent.json"
STATUS_URL = "https://raw.githubusercontent.com/{repo}/data/news-ai/status.json"


def load_scores(repo, previous, getter=fetch.http_get):
    """({headline key: {"sentiment", "label", "event"}}, meta) from the data branch, else the previous publish's copy, else ({}, None). Never raises."""
    for source in ([RAW_URL.format(repo=repo)] if repo else []):
        try:
            data = json.loads(getter(source, retries=1, timeout=30))
            if isinstance(data, dict) and data.get("v") == 1 and isinstance(data.get("scores"), dict):
                return data["scores"], {"model": data.get("model"), "generated_at": data.get("generated_at"), "n": len(data["scores"])}
        except Exception:
            pass
    if isinstance(previous, dict) and previous.get("v") == 1 and isinstance(previous.get("scores"), dict):
        return previous["scores"], {"model": previous.get("model"), "generated_at": previous.get("generated_at"), "n": len(previous["scores"])}
    return {}, None


def load_status(repo, getter=fetch.http_get):
    """What the last job run did ({"at", "model", "read", "worth_scoring", "already_scored", "attempted", "scored", "outcome", "error"}), or None. Never raises."""
    if not repo:
        return None
    try:
        data = json.loads(getter(STATUS_URL.format(repo=repo), retries=1, timeout=30))
    except Exception:
        return None
    return data if isinstance(data, dict) and data.get("v") == 1 else None


def candidates(items, index, now):
    """[(key, title, symbol)] of headlines worth scoring: about a tracked stock, not routine, newer than RECENT_HOURS, one per distinct headline."""
    by_symbol, _ = news_sources.map_items(items, index)
    seen, out = set(), []
    for symbol, rows in by_symbol.items():
        for item in rows:
            event = news_intel.classify(item.get("desc"), f"{item['title']} {item.get('text') or ''}")[0]
            age = (now.timestamp() - item["ts"]) / 3600 if item.get("ts") else None
            if event in SKIP_EVENTS or (age is not None and age > RECENT_HOURS):
                continue
            title = item["title"] if item["kind"] != "nse" else (item.get("text") or item["title"])
            k = ai_sentiment.key(title)
            if k not in seen:
                seen.add(k)
                out.append((k, title, symbol, item.get("ts") or 0, item["kind"]))
    out.sort(key=lambda r: (r[4] != "nse", -r[3]))                       # official filings first, then newest
    return [(k, t, s) for k, t, s, _, _ in out]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--publish", action="store_true", help="store the scores on the data branch")
    parser.add_argument("--max-requests", type=int, default=6, help="model calls per run (each scores up to 25 headlines)")
    parser.add_argument("--dry-run", action="store_true", help="show what would be scored, call nothing")
    parser.add_argument("--data-dir", default="", help="use this folder as the data branch checkout (no git); for testing")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    token = os.environ.get("GITHUB_TOKEN", "")
    model = os.environ.get("NEWS_AI_MODEL") or ai_sentiment.DEFAULT_MODEL
    config = json.loads((ROOT / "config" / "universe.json").read_text(encoding="utf-8"))
    names = {s[0]: s[1] for s in config["stocks"] if s[2] == "IN"}
    items, statuses = news_sources.collect(now, {}, log=print)
    index = news_sources.NameIndex(names)
    wanted = candidates(items, index, now)
    print(f"{len(items)} items read, {len(wanted)} headlines about tracked stocks are worth scoring")

    folder = args.data_dir
    remote = ""
    if args.publish and not folder:
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        remote = f"https://github.com/{repo}.git" if repo else ""
        folder = str(Path(tempfile.mkdtemp()) / "data")
        if remote:
            ledger_git.prepare(folder, remote, token=token or None)
    base = Path(folder) / "news-ai" if folder else None
    stored = {}
    if base and (base / "scores-recent.json").exists():
        try:
            stored = json.loads((base / "scores-recent.json").read_text(encoding="utf-8")).get("scores", {})
        except ValueError:
            stored = {}
    todo = [(k, t, s) for k, t, s in wanted if k not in stored][: args.max_requests * ai_sentiment.BATCH]
    print(f"{len(stored)} headlines already scored, {len(todo)} new ones to score")
    status = {"v": 1, "at": now.isoformat(timespec="seconds"), "model": model, "read": len(items), "worth_scoring": len(wanted), "already_scored": len(stored),
              "attempted": len(todo), "scored": 0, "outcome": None, "error": None}

    def record(outcome, error=None, scored=0):
        """Write the run's outcome next to the scores, so the site can say why there are (or are not) AI scores without anyone reading the job log."""
        status.update(outcome=outcome, error=error, scored=scored)
        if base is None or args.dry_run:
            return
        base.mkdir(parents=True, exist_ok=True)
        (base / "status.json").write_text(json.dumps(status, separators=(",", ":")), encoding="utf-8")
        if remote:
            try:
                ledger_git.publish(folder, f"News AI status {status['at']}", token=token or None)
            except (ledger_git.GitError, OSError) as err:
                print("Status not saved:", err)

    if args.dry_run:
        return 0
    if not todo:
        record("nothing new to score")
        return 0
    if not token:
        print("No GITHUB_TOKEN with the models scope: nothing scored. The build keeps using the rule-based score.")
        record("no token")
        return 0

    scores, error = ai_sentiment.score([t for _, t, _ in todo], token, model)
    stamp = now.isoformat(timespec="seconds")
    fresh = {}
    for index_, value in scores.items():
        k = todo[index_][0]
        fresh[k] = {"sentiment": value["sentiment"], "label": value["label"], "event": value["event"], "at": stamp}
    print(f"{len(fresh)} of {len(todo)} headlines scored" + (f"; stopped on: {error}" if error else ""))
    if not (base and fresh):
        record("stopped: " + error if error else "model returned no usable scores", error, len(fresh))
        return 0
    if base and fresh:
        status.update(outcome="scored" + (" (stopped early)" if error else ""), error=error, scored=len(fresh))
        base.mkdir(parents=True, exist_ok=True)
        with open(base / f"scores-{now.strftime('%Y-%m')}.jsonl", "a", encoding="utf-8", newline="\n") as handle:
            for k, v in fresh.items():
                handle.write(json.dumps({"k": k, **v, "model": model}, separators=(",", ":")) + "\n")
        cutoff = (now - timedelta(hours=RECENT_HOURS)).isoformat(timespec="seconds")
        merged = {k: v for k, v in {**stored, **fresh}.items() if v.get("at", stamp) >= cutoff}
        (base / "scores-recent.json").write_text(json.dumps({"v": 1, "model": model, "generated_at": stamp, "scores": merged}, separators=(",", ":")), encoding="utf-8")
        (base / "status.json").write_text(json.dumps(status, separators=(",", ":")), encoding="utf-8")
        if remote:
            pushed = ledger_git.publish(folder, f"News AI scores {stamp}", token=token or None)
            print("Published to the data branch" if pushed else "Nothing new to publish")
    return 0


if __name__ == "__main__":
    sys.exit(main())
