"""What has already been sent to Telegram, kept on the `data` branch instead of only inside the published site.

The published state.json is saved only when a build passes its checks and deploys. Alerts go out earlier in the run, so a run that failed after sending
forgot what it had sent, and the next run sent it again. This memory is written straight after the alerts are sent, before the checks and the deploy.

    alerts/memory.json   {"v": 1, "saved_at": ISO time, "state": {the keys below}}

A run reads it first. If it is newer than (or as new as) the published state it wins for these keys; if it cannot be read the published state is used,
which is the behaviour before this file existed.
"""
import json
import os
from pathlib import Path

FILE = "alerts/memory.json"
KEYS = ("seen_alerts", "alert_sides", "news_alert_history", "deal_seen", "mover_seen", "index_seen", "briefs_sent", "notified_outcomes", "reply_queue",
        "feeds_sent", "feed_queue", "filing_seen", "regime_seen", "health_seen", "vol_seen", "announced", "action_seen", "surv_state", "ban_state", "digest_seen")


def read(directory):
    """The stored memory from a working copy of the data branch, or None if there is none or it is not valid."""
    try:
        data = json.loads((Path(directory) / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not (isinstance(data, dict) and data.get("v") == 1 and isinstance(data.get("saved_at"), str) and isinstance(data.get("state"), dict)):
        return None
    return data


def restore(state, memory):
    """`state` with the remembered keys put back, if the memory is at least as new as the state. Returns (state, whether the memory was used)."""
    if not memory or memory["saved_at"] < (state.get("memory_at") or ""):
        return state, False
    merged = dict(state)
    for key in KEYS:
        if key in memory["state"]:
            merged[key] = memory["state"][key]
    return merged, True


def write(directory, new_state, saved_at):
    """Write the memory file for this run's state and stamp the state with the same time, so the published copy and this one can be compared."""
    new_state["memory_at"] = saved_at
    body = {"v": 1, "saved_at": saved_at, "state": {k: new_state[k] for k in KEYS if k in new_state}}
    path = Path(directory) / FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    os.replace(temporary, path)
