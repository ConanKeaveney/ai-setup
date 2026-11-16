#!/usr/bin/env python3
"""Stop hook: block once when a final answer runs long and the user did not ask for depth."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time

#: Prose longer than this is blocked once. Two lines rather than one: an answer
#: that is a sentence plus a short follow-on is within the spirit, and pinning
#: at exactly one line would fire on things nobody objects to. The character
#: bound catches the single enormous paragraph, which the line count cannot.
MAX_LINES = 2
MAX_CHARS = 350
#: Distinct jargon tokens tolerated in a default answer before it is refused.
MAX_JARGON = 2

#: Words in the USER's last message that ask for depth. From CLAUDE.md's own
#: list -- "why", "how does that work", "show me", "what exactly" -- plus the
#: obvious siblings. Depth is opt-in and **the unlock lasts one answer**, which
#: is automatic here: the next turn has a new user message.
UNLOCKS = (
    "why", "how ", "how'", "how?", "show me", "what exactly", "explain",
    "in detail", "walk me through", "more detail", "elaborate", "depth",
    "give me the detail", "talk me through", "break it down", "full picture",
    "compare", "options", "trade-off", "tradeoff", "list ", "table",
    "what are the", "which ones", "step by step", "summarise", "summarize",
    "write up", "draft", "plan", "report",
)

#: A `tldr` is a COMPLAINT about the previous answer, never a licence for a long
#: one. Listed so it is never mistaken for an unlock by a future edit.
NOT_UNLOCKS = ("tldr", "tl;dr", "too long", "shorter", "one line", "in one line")


def _state_path(session_id: str) -> str:
    d = os.path.expanduser("~/.claude/state/one-line-default")
    os.makedirs(d, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_-]", "", session_id or "unknown")[:64]
    return os.path.join(d, f"{safe}.json")


def _already_blocked(session_id: str, fingerprint: str) -> bool:
    """True when this turn has already been refused once.

    Keyed on a fingerprint of the user's message, so a *new* question gets its
    own single block. Without that, one long answer would silence the guard for
    the rest of the session; with it keyed on the assistant's text instead, an
    edited-but-still-long answer would be blocked forever, which is the loop
    this must not create.
    """
    path = _state_path(session_id)
    try:
        with open(path) as fh:
            prior = json.load(fh)
    except Exception:
        prior = {}
    if prior.get("fingerprint") == fingerprint:
        return True
    try:
        with open(path, "w") as fh:
            json.dump({"fingerprint": fingerprint, "at": time.time()}, fh)
    except Exception:
        # Cannot record it, so cannot promise not to loop: let it through.
        return True
    return False


def _strip_uncounted(text: str) -> str:
    """Remove what the rule was never about: code, output, links, quoted logs.

    A fenced block is something they asked to see -- a command, a diff, a rendered
    refusal -- and counting it would make the guard fire on answers that are one
    line of prose around a block they wanted. Tables are stripped for the same
    reason: CLAUDE.md explicitly allows one "when a table is genuinely the
    answer".
    """
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"^\s*\|.*\|\s*$", "", text, flags=re.M)  # table rows
    text = re.sub(r"^\s*[-|: ]+\s*$", "", text, flags=re.M)  # table rules
    return text


def _prose_shape(text: str) -> tuple[int, int]:
    body = _strip_uncounted(text)
    lines = [ln for ln in (l.strip() for l in body.splitlines()) if ln]
    return len(lines), len(" ".join(lines))


#: Structural jargon only — shapes that cannot be ordinary English, so a false
#: positive needs a genuinely odd sentence rather than an unlucky word choice.
#: CLAUDE.md names the class: "internal names, file paths, function names,
#: config keys, issue numbers, metric names, flags".
_JARGON_PATTERNS = (
    r"#\d+",                                  # issue and PR references
    r"(?<!\w)--[a-z][a-z0-9-]+",               # command-line flags
    r"(?<!\w)~?/[\w.\-/]*\w",                  # absolute or ~ paths
    r"\b[\w.\-]+/[\w.\-/]*\.\w{1,5}\b",       # relative paths with an extension
    r"\b\w+\.(?:rs|py|md|json|toml|yaml|yml|jsonl|sh)\b",   # filenames
    r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+){1,}\b",   # snake_case identifiers
    r"\b[A-Za-z_]\w*::[A-Za-z_]\w*",           # Rust paths / methods
    r"\b[a-z][a-z0-9]*\.[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+\b",  # dotted config keys
)

#: A term the user themselves used is not jargon in the reply — answering
#: "is #692 done" with "#692" is plain speech, not a lapse.
def _jargon(assistant: str, user: str) -> list[str]:
    body = _strip_uncounted(assistant)
    theirs = user.lower()
    found: list[str] = []
    for pattern in _JARGON_PATTERNS:
        for m in re.findall(pattern, body):
            tok = m if isinstance(m, str) else m[0]
            if tok.lower() in theirs:
                continue
            if tok not in found:
                found.append(tok)
    return found


def _last_messages(transcript_path: str) -> tuple[str, str]:
    """(last assistant text, last user text) from a JSONL transcript."""
    assistant, user = "", ""
    with open(transcript_path, errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            role = (rec.get("message") or {}).get("role") or rec.get("role")
            content = (rec.get("message") or {}).get("content")
            if isinstance(content, list):
                text = "".join(
                    c.get("text", "")
                    for c in content
                    if isinstance(c, dict) and c.get("type") == "text"
                )
            elif isinstance(content, str):
                text = content
            else:
                continue
            if not text.strip():
                continue
            if role == "assistant":
                assistant = text
            elif role == "user":
                user = text
                assistant = ""  # a new question resets what we are judging
    return assistant, user


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    # A stop that is already being blocked by something else, or a subagent's
    # stop, is not ours to judge.
    if payload.get("stop_hook_active"):
        return 0

    transcript = payload.get("transcript_path") or ""
    if not transcript or not os.path.exists(transcript):
        return 0

    try:
        assistant, user = _last_messages(transcript)
    except Exception:
        return 0

    if not assistant.strip():
        return 0

    low_user = user.lower()
    if any(u in low_user for u in UNLOCKS) and not any(
        n in low_user for n in NOT_UNLOCKS
    ):
        return 0

    lines, chars = _prose_shape(assistant)
    jargon = _jargon(assistant, user)
    too_long = lines > MAX_LINES or chars > MAX_CHARS
    # Two is the threshold, not one: naming the single file they asked about is
    # answering the question, and blocking that would teach evasion.
    too_jargony = len(jargon) >= MAX_JARGON
    if not too_long and not too_jargony:
        return 0

    # **`hashlib`, never `hash()`.** Python randomises `hash()` per process
    # unless `PYTHONHASHSEED` is set, and this hook is a fresh process every
    # turn — so a `hash()` fingerprint never matches the one it wrote a moment
    # ago, the "blocked once" check never fires, and the guard refuses the same
    # answer forever. Caught by its own test, which is the only reason it is not
    # in the session that was meant to benefit from it.
    fingerprint = hashlib.sha256(user.strip().encode()).hexdigest()[:32]
    if _already_blocked(payload.get("session_id", ""), fingerprint):
        return 0

    if too_jargony and not too_long:
        reason = (
            f"That answer was inside the length limit but leaned on "
            f"{len(jargon)} pieces of jargon they did not use themselves: "
            + ", ".join(jargon[:6])
            + ".\n\nCLAUDE.md: plain English, and that explicitly includes our "
            "own — internal names, file paths, function names, config keys, "
            "issue numbers, metric names and flags. He is the technical lead, "
            "not the implementer: they want the outcome and what it means, not "
            "the machinery behind it.\n\nSay the same thing in words. Name what "
            "the thing DOES rather than what it is called. A path or an issue "
            "number belongs in a technical answer they asked for; in a status "
            "update it is noise they have to decode.\n\nIf a term is genuinely the "
            "answer — they asked which file, or which issue — say it again and it "
            "will go through. This blocks once per question."
        )
    else:
        reason = (
        f"That answer was {lines} line(s) and {chars} characters of prose. "
        f"The default is ONE line, in plain English — the user's standing "
        f"instruction in ~/.claude/CLAUDE.md.\n\n"
        f"They did not ask for depth in their last message, so this is the default "
        f"case. Re-answer in one line: the answer itself, no preamble, no "
        f"summary of what you checked, no list of what is still running. A "
        f"number and a fact are a complete answer.\n\n"
        f"If the length was genuinely right — a correction, a completion "
        f"report, a decision they have to make — say it again and it will go "
        f"through. This blocks once per question, not repeatedly. But the "
        f"measured history is that it almost never is: the answers that "
        f"provoked a `tldr` ran a median of 1,320 characters, and every one of "
        f"them felt like the exception while it was being written."
    )
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Fail open. A broken guard must not wedge the session.
        sys.exit(0)
