#!/usr/bin/env python3
"""PreToolUse guard: block shell sleep/poll loops; wait with a background job instead."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
DECISION_LOG = HOME / ".claude" / "poll-loop-decisions.jsonl"

#: A bare sleep of this many seconds or fewer is allowed through.
SETTLE_S = 120

#: Loop constructs. A poll loop needs one of these AND a wait inside it.
LOOP = re.compile(r"(?<![-\w])(?:until|while)\b|\bfor\s+\w+\s+in\b")

STATE_DIR = HOME / ".claude" / "poll-state"
REPEAT_WINDOW_S = 180
REPEAT_LIMIT = 2

READONLY = {
    "tail", "head", "cat", "grep", "egrep", "rg", "ps", "pgrep", "ls", "date",
    "echo", "true", ":", "wc", "sed", "awk", "du", "df", "stat", "test", "[",
    "printf", "find", "jq", "lsof", "uptime", "vm_stat", "sleep", "cd", "export",
}
READONLY_SUB = {
    "git": {"status", "log", "show", "diff", "rev-parse"},
    "gh": {"pr", "run", "issue"},
}
READONLY_GH_VERB = {"view", "list", "checks", "status"}
SEGMENT_SPLIT = re.compile(r"\s*(?:;|&&|\|\||\||\n)\s*")
NOOP_ECHO = re.compile(r"echo(\s+[\"']?[\w.:\-]+[\"']?){0,3}")
NOOP_SLEEP = re.compile(r"sleep\s+[\d.]+")


def segments(text: str) -> list[str]:
    return [s.strip() for s in SEGMENT_SPLIT.split(text) if s.strip()]


def is_readonly(text: str) -> bool:
    if ">" in text.replace("2>&1", "").replace(">/dev/null", "").replace("> /dev/null", ""):
        return False
    for seg in segments(text):
        words = seg.split()
        head = words[0]
        if head in READONLY:
            continue
        if head == "git" and len(words) > 1 and words[1] in READONLY_SUB["git"]:
            continue
        if head == "gh" and len(words) > 2 and words[1] in READONLY_SUB["gh"] and words[2] in READONLY_GH_VERB:
            continue
        if "--status" in words and any(w.endswith("build_lease.py") for w in words[:2]):
            continue
        return False
    return True


def is_spin(text: str) -> bool:
    segs = segments(text)
    if not segs or (len(segs) == 1 and segs[0].split()[0] in ("date", "sleep")):
        return False
    for seg in segs:
        if seg in ("true", ":") or seg.split()[0] == "date":
            continue
        if NOOP_ECHO.fullmatch(seg) or NOOP_SLEEP.fullmatch(seg):
            continue
        return False
    return True


def repeat_count(payload: dict, text: str) -> int:
    """Times this read-only command already ran in the window; records this run."""
    key = payload.get("transcript_path") or ""
    if not key:
        return 0
    norm = " ".join(text.split())
    path = STATE_DIR / (re.sub(r"[^\w.-]", "_", key)[-150:] + ".json")
    now = time.time()
    try:
        seen = json.loads(path.read_text())
    except (OSError, ValueError):
        seen = []
    seen = [e for e in seen if now - e[0] < REPEAT_WINDOW_S]
    count = sum(1 for _, c in seen if c == norm)
    seen.append([now, norm])
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(seen[-200:]))
    except OSError:
        pass
    return count

#: The wait itself. `sleep 90`, `sleep 0.5`, and a foreground `tail -f`.
SLEEP = re.compile(r"\bsleep\s+[\d.]+")
TAIL_F = re.compile(r"\btail\s+(?:-\w+\s+)*-\w*f")

#: Shapes seen in the transcripts, quoted for the message.
KNOWN = (
    (re.compile(r"until\s+!?\s*pgrep"), "until ! pgrep ...; do sleep n; done"),
    (re.compile(r"while\s+pgrep"), "while pgrep ...; do sleep n; done"),
    (re.compile(r"until\s+grep"), "until grep -q ... log; do sleep n; done"),
    (re.compile(r"while\s+!\s*grep"), "while ! grep -q ... log; do sleep n; done"),
    (re.compile(r"until\s+\["), "until [ -s file ]; do sleep n; done"),
)


def strip_heredocs(raw: str) -> str:
    """Drop heredoc bodies. Their contents are a program, not a command line."""
    out, skip_to = [], None
    for line in raw.splitlines():
        if skip_to is not None:
            if line.strip() == skip_to:
                skip_to = None
            continue
        m = re.search(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", line)
        if m:
            skip_to = m.group(1)
        out.append(line)
    return "\n".join(out)


def strip_quoted(text: str) -> str:
    """Blank out quoted spans. Shell KEYWORDS never live inside quotes.

    `echo "the loop used to sleep 60 in a while"` is prose, and the first draft
    of this guard refused it — reproducing, inside the guard written to avoid it,
    the precise defect that had `long-job-delegate.py` refusing `grep` earlier
    the same day. Caught by this file's own negative controls, which is what they
    are for.

    Quotes are replaced by spaces rather than deleted, so that
    `until grep -qE "a|b" log; do sleep 5; done` keeps its structure and is still
    read as the poll loop it is.
    """
    out, quote = [], None
    for ch in text:
        if quote:
            out.append(" ")
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def bare_settle_seconds(text: str) -> float | None:
    """Seconds of a `sleep` that is NOT inside a loop, else None."""
    if LOOP.search(text):
        return None
    hits = [float(m) for m in re.findall(r"\bsleep\s+([\d.]+)", text)]
    return sum(hits) if hits else None


def classify(payload: dict) -> tuple[str | None, str]:
    """(what_is_wrong, why_exempt). A non-None first element means refuse."""
    if payload.get("tool_name") != "Bash":
        return None, "not Bash"
    ti = payload.get("tool_input") or {}
    raw = ti.get("command") or ""
    if not raw.strip():
        return None, "empty command"

    if ti.get("run_in_background") is True:
        return None, "already backgrounded"

    # Heredoc bodies are a program, not a command line; quoted spans are data,
    # not syntax. Both must be out of the way before any keyword matching.
    text = strip_quoted(strip_heredocs(raw))

    inline = dict(re.findall(r"\b([A-Z_][A-Z0-9_]*)=(\S*)", text))
    overridden = inline.get("CLAUDE_POLL_LOOP", "").lower() in (
        "off",
        "0",
        "false",
    ) or os.environ.get("CLAUDE_POLL_LOOP", "").lower() in ("off", "0", "false")

    has_loop = bool(LOOP.search(text))

    # THE OVERRIDE DOES NOT COVER A FOREGROUND `tail -f`, and this is the one
    # shape it must not cover. an evaluator waited on test
    # results four times with
    #
    #     CLAUDE_POLL_LOOP=off grep -m1 -E "^exit=" <(tail -f -n +1 run.log)
    #
    # `grep -m1` exits on the first match, but `tail -f` never does — it holds
    # the pipe open, so the call cannot return. All four were SIGTERMed at the
    # 590 s cap **with the answer already in the log**: ~40 minutes lost, the
    # tests themselves having finished in seconds. The guard caught it correctly
    # every time and was waved through every time.
    #
    # The override exists for a short settle the guard reads as a wait. It was
    # never for this: a foreground `tail -f` has no terminating case, so
    # "I know what I am doing" cannot be true of it. Narrowed rather than
    # removed, because `sleep`-shaped false positives are real and the escape
    # hatch earns its keep there.
    if TAIL_F.search(text) and not has_loop:
        return "a foreground `tail -f`", ""

    # THE OVERRIDE DOES NOT COVER A LONG SLEEP EITHER, for the same reason it
    # does not cover `tail -f`: it exists for "a short settle the guard reads as
    # a wait", and a settle is seconds. a reviewer spent
    # **12.3 of its 21.8 minutes** — 56% of its whole life — inside ten calls of
    #
    #     CLAUDE_POLL_LOOP=off sleep 420; cat <log>
    #
    # waiting on a build it had itself backgrounded, and which the harness would
    # have woken it for. The guard caught it correctly ten times and was waved
    # through ten times, because the refusal text below named the escape hatch in
    # its closing line: an agent that hits the block reads the bypass in the same
    # breath. That sentence is gone, and the override is now bounded by what it
    # claims to be for.
    if overridden and (m := SLEEP_SECONDS.search(text)):
        try:
            secs = float(m.group(1))
        except ValueError:
            secs = 0.0
        if secs > SETTLE_CAP_S:
            return (f"a {secs:.0f}s sleep, which the override does not cover "
                    f"(it is for a settle of {SETTLE_CAP_S:.0f}s or less)"), ""

    if overridden:
        return None, "override"

    has_wait = bool(SLEEP.search(text)) or bool(TAIL_F.search(text))
    if has_loop and has_wait:
        for pat, shape in KNOWN:
            if pat.search(text):
                return shape, ""
        return "a loop whose body sleeps", ""

    settle = bare_settle_seconds(text)
    if settle is not None:
        if settle > SETTLE_S:
            return f"a bare `sleep {settle:g}`, longer than {SETTLE_S}s", ""
        return None, "short sleep"

    if is_spin(strip_heredocs(raw)):
        return "a step that does nothing but pass time", ""

    if is_readonly(text) and repeat_count(payload, raw) >= REPEAT_LIMIT:
        return "the same status check, run again within three minutes", ""

    return None, "not a poll loop"


def deny_text(shape: str) -> str:
    return (
        f"This waits by polling — {shape}. Every step re-reads your whole "
        "context, so a check every few seconds costs hundreds of times what one "
        "blocking wait does.\n"
        "\n"
        "Wait in ONE call that blocks until the job is done:\n"
        "  1. Launch the job with `run_in_background: true`, ending the command "
        "with `; echo \"EXIT=$?\"` and writing to a log.\n"
        "  2. Then, in the foreground, with Bash `timeout: 600000`:\n"
        "       ~/.claude/bin/wait-for --log job.log "
        "--until '^EXIT=|FAILED|panicked|error\\[E[0-9]|Killed' --max 540\n"
        "     Other conditions: `--pid N`, `--check '<cmd that exits 0 when ready>'`, "
        "`--for <seconds>`. Exit 124 means not yet: run the same command again.\n"
        "  3. Match FAILURE signatures as well as success: a wait that matches "
        "only success is silent through a crash.\n"
        "\n"
        "If there is other work that does not depend on the job, do it first, "
        "then wait. Never fill the time with checks or no-op commands."
    )


#: A settle is seconds; a wait is not. Bounds what `CLAUDE_POLL_LOOP=off` may
#: wave through.
SETTLE_CAP_S = 30.0
SLEEP_SECONDS = re.compile(r"\bsleep\s+([0-9]+(?:\.[0-9]+)?)\b")


def log(record: dict) -> None:
    try:
        DECISION_LOG.parent.mkdir(parents=True, exist_ok=True)
        with DECISION_LOG.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        pass


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        shape, exempt = classify(payload)
        if shape is None:
            return 0
        log({
            "t": time.time(),
            "decision": "deny",
            "shape": shape,
            "session": payload.get("session_id", ""),
            "agent": payload.get("agent_type", ""),
            "cmd": (payload.get("tool_input") or {}).get("command", "")[:200],
        })
        json.dump(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": deny_text(shape),
                }
            },
            sys.stdout,
        )
    except Exception:
        return 0  # fail open, deliberately
    return 0


if __name__ == "__main__":
    if "--probe" in sys.argv:
        cmd = " ".join(a for a in sys.argv[1:] if a != "--probe")
        s, why = classify({"tool_name": "Bash", "tool_input": {"command": cmd}})
        print(f"{'POLL LOOP: ' + s if s else 'allowed (' + why + ')'}")
        sys.exit(0)
    sys.exit(main())
