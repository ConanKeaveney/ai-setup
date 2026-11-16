import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
import urllib.request


MAX_AGE = 300
POLL_INTERVAL = 60
USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def read_json(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def recent(value, now, age=MAX_AGE):
    return number(value) and 0 <= now - value <= age


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_codex(auth):
    tokens = auth.get("tokens") or {}
    token, account = tokens.get("access_token"), tokens.get("account_id")
    if not isinstance(token, str) or not token or not isinstance(account, str) or not account:
        raise ValueError("Codex sign-in unavailable")
    request = urllib.request.Request(USAGE_URL, headers={
        "Authorization": f"Bearer {token}",
        "ChatGPT-Account-Id": account,
        "User-Agent": "codex-cli",
    })
    with urllib.request.build_opener(NoRedirect).open(request, timeout=1.5) as response:
        raw = response.read(1048577)
    if len(raw) > 1048576:
        raise ValueError("Usage response too large")
    value = json.loads(raw)
    limits = value.get("rate_limit")
    if not isinstance(limits, dict):
        raise ValueError("Usage limits unavailable")
    return {key: limits.get(key) for key in ("primary_window", "secondary_window")}


def codex_snapshot(home, now, fetch=fetch_codex):
    root = Path(os.environ.get("CODEX_HOME", home / ".codex"))
    auth = read_json(root / "auth.json")
    tokens = auth.get("tokens")
    if not isinstance(tokens, dict) or not tokens.get("account_id") or not tokens.get("access_token"):
        return {}
    identity = hashlib.sha256(str(tokens["account_id"]).encode()).hexdigest()
    directory = home / ".cache/opencode-statusline"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / f"codex-{identity}.json"
    snapshot = read_json(path)
    if recent(snapshot.get("checked_at"), now, POLL_INTERVAL):
        return snapshot
    with (directory / f"codex-{identity}.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return snapshot
        snapshot = read_json(path)
        if recent(snapshot.get("checked_at"), now, POLL_INTERVAL):
            return snapshot
        try:
            limits = fetch(auth)
            snapshot = {"captured_at": now, "rate_limits": limits}
        except Exception:
            pass
        snapshot["checked_at"] = now
        fd, temporary = tempfile.mkstemp(dir=directory, prefix=".codex-")
        try:
            with os.fdopen(fd, "w") as output:
                json.dump(snapshot, output)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return snapshot


def duration(seconds, rounding=math.ceil):
    minutes = rounding(seconds / 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    return f"{days}d{hours}h" if days else f"{hours}h{minutes:02d}m" if hours else f"{minutes}m"


WEEK = 604800


def window(label, value, now, pct_key, reset_key, renderer, length=None):
    if not isinstance(value, dict):
        return f"{label} ?"
    percent, reset = value.get(pct_key), value.get(reset_key)
    if not number(percent) or not 0 <= percent <= 100 or not number(reset) or reset <= now:
        return f"{label} ?"
    through = ""
    if length == WEEK:
        elapsed = min(100, max(0, 100 * (1 - (reset - now) / WEEK)))
        through = f", week {elapsed:.0f}% through"
    return (f"{renderer['pct_color'](percent)}{label} {percent:.0f}%{renderer['R']}"
            f" used{through} (resets in {duration(reset - now)})")


def segment(name, snapshot, now, renderer, codex=False):
    captured = snapshot.get("captured_at")
    if not recent(captured, now):
        if not number(captured) or captured >= now:
            return f"{name} limits unknown"
        limits = snapshot.get("rate_limits")
        if codex or not isinstance(limits, dict):
            return f"{name} limits stale"
        windows = [window(label, limits.get(key), now, "used_percentage", "resets_at", renderer, length)
                   for key, label, length in (("five_hour", "5h", 18000), ("seven_day", "7d", WEEK))
                   if limits.get(key) is not None]
        windows = [part for part in windows if not part.endswith(" ?")]
        if not windows:
            return f"{name} limits stale"
        return f"{name} {' '.join(windows)} as of {duration(now - captured, math.floor)} ago"
    limits = snapshot.get("rate_limits")
    if not isinstance(limits, dict):
        return f"{name} limits unknown"
    if codex:
        windows = []
        for key in ("primary_window", "secondary_window"):
            value = limits.get(key)
            seconds = value.get("limit_window_seconds") if isinstance(value, dict) else None
            if not number(seconds) or seconds <= 0:
                continue
            if seconds % 86400 == 0:
                label = f"{seconds / 86400:g}d"
            elif seconds % 3600 == 0:
                label = f"{seconds / 3600:g}h"
            else:
                label = f"{seconds / 60:g}m"
            windows.append(window(label, value, now, "used_percent", "reset_at", renderer, seconds))
    else:
        windows = [window(label, limits.get(key), now, "used_percentage", "resets_at", renderer, length)
                   for key, label, length in (("five_hour", "5h", 18000), ("seven_day", "7d", WEEK))
                   if limits.get(key) is not None]
    return f"{name} {' '.join(windows)}" if windows else f"{name} limits unknown"


def segments(renderer, home=None, now=None, fetch=fetch_codex):
    home = Path.home() if home is None else Path(home)
    now = time.time() if now is None else now
    claude = read_json(home / ".claude/state/rate-limits.json")
    try:
        codex = codex_snapshot(home, now, fetch)
    except (OSError, ValueError):
        codex = {}
    return [segment("Claude Code", claude, now, renderer),
            segment("Codex", codex, now, renderer, codex=True)]
