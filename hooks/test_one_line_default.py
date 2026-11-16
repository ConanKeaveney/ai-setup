#!/usr/bin/env python3
"""Drive `one-line-default.py` through the cases it exists to separate.

Every assertion here was watched to fail against a deliberately broken copy of
the guard before being kept — the rule this repository applies to its own
guards, applied to the guard about the rule.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "one-line-default.py")


def _transcript(pairs: list[tuple[str, str]]) -> str:
    """A JSONL transcript from (role, text) pairs, in order."""
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as fh:
        for role, text in pairs:
            fh.write(
                json.dumps(
                    {"message": {"role": role, "content": [{"type": "text", "text": text}]}}
                )
                + "\n"
            )
    return path


def run(pairs, session="t-session", state_dir=None) -> dict:
    path = _transcript(pairs)
    env = dict(os.environ)
    if state_dir:
        env["HOME"] = state_dir
        os.makedirs(os.path.join(state_dir, ".claude", "state"), exist_ok=True)
    out = subprocess.run(
        [sys.executable, HOOK],
        input=json.dumps({"transcript_path": path, "session_id": session}),
        capture_output=True,
        text=True,
        env=env,
    )
    os.unlink(path)
    assert out.returncode == 0, f"the hook must always exit 0: {out.stderr}"
    return json.loads(out.stdout) if out.stdout.strip() else {}


LONG = (
    "Here is the first thing I checked and what it showed.\n"
    "Then the second thing, which took a while and is worth explaining.\n"
    "A third point about what is still running in the background.\n"
    "And a closing summary of everything above, restated."
)
ONE_LINE = "Merged and deployed; live on 8080."


def main() -> int:
    failures = []

    def check(name, cond, detail=""):
        if cond:
            print(f"  PASS  {name}")
        else:
            print(f"  FAIL  {name}  {detail}")
            failures.append(name)

    with tempfile.TemporaryDirectory() as home:
        # A long answer to a plain question is blocked.
        r = run([("user", "did it merge"), ("assistant", LONG)], "s1", home)
        check("long answer to a plain question is blocked", r.get("decision") == "block", r)

        # ...but only once for that question, or the guard loops forever.
        r2 = run([("user", "did it merge"), ("assistant", LONG)], "s1", home)
        check("the same question is not blocked twice", r2.get("decision") != "block", r2)

        # A new question gets its own single block.
        r3 = run([("user", "what about the other one"), ("assistant", LONG)], "s1", home)
        check("a NEW question is blocked again", r3.get("decision") == "block", r3)

    with tempfile.TemporaryDirectory() as home:
        # One line is never blocked.
        r = run([("user", "did it merge"), ("assistant", ONE_LINE)], "s2", home)
        check("a one-line answer passes", r.get("decision") != "block", r)

    with tempfile.TemporaryDirectory() as home:
        # Depth was asked for, so length is allowed.
        r = run([("user", "why did that fail?"), ("assistant", LONG)], "s3", home)
        check("an explicit 'why' unlocks length", r.get("decision") != "block", r)
        r = run([("user", "show me the numbers"), ("assistant", LONG)], "s3b", home)
        check("'show me' unlocks length", r.get("decision") != "block", r)

    with tempfile.TemporaryDirectory() as home:
        # `tldr` is a complaint, never a licence. Without this the guard would
        # go quiet at exactly the moment they are objecting to length.
        r = run([("user", "tldr"), ("assistant", LONG)], "s4", home)
        check("'tldr' does NOT unlock length", r.get("decision") == "block", r)

    with tempfile.TemporaryDirectory() as home:
        # A fenced block they asked to see is not prose and must not count.
        fenced = "Run this:\n\n```\n" + "\n".join(f"line {i}" for i in range(30)) + "\n```"
        r = run([("user", "what do i run"), ("assistant", fenced)], "s5", home)
        check("a code block does not count as prose", r.get("decision") != "block", r)

        table = "Here:\n\n| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n| 5 | 6 |"
        r = run([("user", "what did each arm score"), ("assistant", table)], "s5b", home)
        check("a table does not count as prose", r.get("decision") != "block", r)

    with tempfile.TemporaryDirectory() as home:
        # One enormous paragraph is one line, and is exactly the shape the line
        # count cannot see. The character bound is what catches it.
        blob = "word " * 200
        r = run([("user", "did it merge"), ("assistant", blob)], "s6", home)
        check("one huge paragraph is caught by the char bound", r.get("decision") == "block", r)

    # Fails open on a transcript that is not there.
    out = subprocess.run(
        [sys.executable, HOOK],
        input=json.dumps({"transcript_path": "/nonexistent/x.jsonl", "session_id": "s7"}),
        capture_output=True,
        text=True,
    )
    check("a missing transcript fails open", out.returncode == 0 and not out.stdout.strip())

    # And on garbage in.
    out = subprocess.run([sys.executable, HOOK], input="not json", capture_output=True, text=True)
    check("garbage input fails open", out.returncode == 0 and not out.stdout.strip())

    print(f"\n{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
