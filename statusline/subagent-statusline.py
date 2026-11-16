#!/usr/bin/env python3
"""Per-subagent row decoration: goal, type, elapsed, model, tokens, quiet.

Reads the harness payload on stdin; prints one {"id", "content"} JSON line per task.
"""

from __future__ import annotations

import json
import os
import sys
import time

R = "\033[0m"
DIM = "\033[2m"
RED = "\033[1;31m"
YEL = "\033[33m"
CYA = "\033[36m"

WARN_ELAPSED_S = 15 * 60
CRIT_ELAPSED_S = 60 * 60

QUIET_SAMPLES = 16


def elapsed(start_ms) -> tuple[str, str] | None:
    """(text, colour) from an epoch-millisecond start time."""
    try:
        secs = int(time.time() - float(start_ms) / 1000.0)
    except (TypeError, ValueError):
        return None
    if secs < 0:
        return None
    col = RED if secs >= CRIT_ELAPSED_S else YEL if secs >= WARN_ELAPSED_S else DIM
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m", col
    if m:
        return f"{m}m{s:02d}s", col
    return f"{s}s", col


def tokens(n) -> str | None:
    try:
        v = int(n)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    if v >= 1000:
        return f"{v / 1000:.1f}k".replace(".0k", "k")
    return str(v)


def is_quiet(samples) -> bool:
    if not isinstance(samples, list) or len(samples) < QUIET_SAMPLES:
        return False
    return len(set(samples)) == 1


def goal(task: dict, at: str | None = None) -> str | None:
    """What the agent was asked to do, without a redundant `<type>:` prefix."""
    for key in ("description", "label", "name"):
        v = task.get(key)
        if isinstance(v, str) and v.strip():
            v = v.strip()
            if at:
                prefix = f"{at}:"
                if v.lower().startswith(prefix.lower()):
                    stripped = v[len(prefix) :].strip()
                    if stripped:
                        v = stripped
            return v if len(v) <= 44 else v[:43] + "…"
    return None


TYPE_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".subagent-types.json")


def _load_cache() -> dict:
    try:
        with open(TYPE_CACHE) as f:
            c = json.load(f)
        return c if isinstance(c, dict) else {}
    except Exception:
        return {}


def _scan_transcript(path: str, wanted: set[str]) -> dict:
    """Map agent id -> subagent_type by joining spawn tool_uses to their results.

    The payload's `type` is the task kind, not the specialist type.
    """
    use_types: dict[str, str] = {}
    found: dict[str, str] = {}
    try:
        with open(path) as f:
            for line in f:
                if "subagent_type" not in line and "agentId" not in line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                content = ((rec.get("message") or {}).get("content")) or []
                if not isinstance(content, list):
                    continue
                for c in content:
                    if not isinstance(c, dict):
                        continue
                    if c.get("type") == "tool_use" and c.get("name") in ("Agent", "Task"):
                        st = (c.get("input") or {}).get("subagent_type")
                        if st:
                            use_types[c.get("id")] = st
                    elif c.get("type") == "tool_result":
                        blob = json.dumps(c.get("content"))
                        for aid in wanted:
                            if aid in blob:
                                st = use_types.get(c.get("tool_use_id"))
                                if st:
                                    found[aid] = st
    except Exception:
        return {}
    return found


def resolve_types(tasks: list, transcript_path) -> dict:
    """Cached id -> subagent_type. Only rescans when an id is genuinely unknown."""
    ids = {t.get("id") for t in tasks if isinstance(t, dict) and t.get("id")}
    cache = _load_cache()
    missing = {i for i in ids if i not in cache}
    if missing and isinstance(transcript_path, str) and transcript_path:
        found = _scan_transcript(transcript_path, missing)
        if found:
            cache.update(found)
            try:
                if len(cache) > 200:
                    cache = dict(list(cache.items())[-200:])
                with open(TYPE_CACHE, "w") as f:
                    json.dump(cache, f)
            except Exception:
                pass
    return cache


def agent_type(task: dict, types: dict) -> str | None:
    """The specialist type, unabbreviated."""
    v = types.get(task.get("id"))
    if not isinstance(v, str) or not v.strip():
        return None
    return v.strip()


def content_for(task: dict, types: dict) -> str:
    bits: list[str] = []

    at = agent_type(task, types)

    g = goal(task, at)
    if g:
        bits.append(g)

    if at:
        bits.append(f"{CYA}{at}{R}")

    el = elapsed(task.get("startTime"))
    if el:
        text, col = el
        bits.append(f"{col}{text}{R}")

    model = task.get("model")
    effort = task.get("effort")
    if isinstance(model, str) and model:
        short = next((f for f in ("opus", "sonnet", "haiku", "fable") if f in model), model)
        bits.append(f"{DIM}{short}{'/' + str(effort) if effort else ''}{R}")

    tok = tokens(task.get("tokenCount"))
    if tok:
        bits.append(f"{DIM}{tok} tok{R}")

    if is_quiet(task.get("tokenSamples")):
        bits.append(f"{DIM}quiet{R}")

    return f" {DIM}·{R} ".join(bits)


def visible_len(s: str) -> int:
    out, i = 0, 0
    while i < len(s):
        if s[i] == "\033":
            j = s.find("m", i)
            if j == -1:
                break
            i = j + 1
            continue
        out += 1
        i += 1
    return out


def clip(s: str, width: int) -> str:
    """Truncate on visible characters, keeping the reset so colour cannot leak."""
    if width <= 0 or visible_len(s) <= width:
        return s
    out, seen, i = [], 0, 0
    while i < len(s) and seen < width - 1:
        if s[i] == "\033":
            j = s.find("m", i)
            if j == -1:
                break
            out.append(s[i:j + 1])
            i = j + 1
            continue
        out.append(s[i])
        seen += 1
        i += 1
    return "".join(out) + "…" + R


def main() -> int:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
    except Exception:
        return 0
    if not isinstance(data, dict):
        return 0

    try:
        width = int(data.get("columns") or 0)
    except (TypeError, ValueError):
        width = 0

    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        return 0

    _types = resolve_types(tasks, data.get("transcript_path"))

    for task in tasks:
        if not isinstance(task, dict):
            continue
        tid = task.get("id")
        if not isinstance(tid, str) or not tid:
            continue
        try:
            body = content_for(task, _types)
        except Exception:
            continue
        if not body:
            continue
        print(json.dumps({"id": tid, "content": clip(body, width)}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
