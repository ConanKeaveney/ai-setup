#!/usr/bin/env python3
"""Claude Code status line: model, context use, branch and usage limits."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

# Branches that count as "home". Anything else is called out loudly, because
# work landing on the wrong branch is the failure this is here to prevent.
DEFAULT_BRANCHES = {
    b.strip()
    for b in os.environ.get("CLAUDE_STATUSLINE_DEFAULT_BRANCH", "master,main").split(",")
    if b.strip()
}

# --- memory thresholds ------------------------------------------------------
# Deliberately aligned with hooks/mem-guard.py, which is the thing that will
# actually refuse to spawn work, so the bar and the guard never disagree about
# whether the machine is in trouble. Two differences, both on purpose:
#
#  * The guard's critical swap line is 512 MB free *and* RAM already tight. A
#    warning that arrives at the deny line arrives too late to act on, so the
#    bar goes red at 1536 MB of swap headroom instead. While this was being
#    written the machine sat at 12.7 GiB swap used / 1.3 GiB free at load 5.3
#    -- the pre-OOM condition, and exactly the state the bar must shout about.
#  * Percent-of-swap-used is NOT a threshold anywhere. macOS grows the swap
#    file on demand, so the ratio sits near 90% on a healthy machine. Absolute
#    swap used, and absolute headroom before the next expansion, are the
#    signals that mean something.
#
# RAM headroom uses `kern.memorystatus_level`, which is bit-for-bit the number
# `memory_pressure -Q` prints as "System-wide memory free percentage" (verified
# against it: both read 32 on the same sample) -- one integer sysctl instead of
# a subprocess. Raw free pages are useless here: they sit near zero on a
# healthy macOS box and would fire constantly.
WARN_SWAP_USED_MB = 6144    # bench/preflight.sh's own FAIL line; mem-guard warns here
CRIT_SWAP_FREE_MB = 1536    # see above: earlier than the guard's 512 MB deny line
WARN_RAM_FREE_PCT = 15      # mem-guard WARN_FREE_PCT
CRIT_RAM_FREE_PCT = 5       # mem-guard CRIT_FREE_PCT

# Context and rate-limit windows share one scale so that "yellow" means the
# same thing everywhere on the line.
WARN_PCT = 60
CRIT_PCT = 85

MB = 1024 * 1024

R = "\033[0m"
DIM = "\033[2m"
RED = "\033[1;31m"
YEL = "\033[33m"
GRN = "\033[32m"
CYA = "\033[36m"
MAG = "\033[35m"


# --- repo identity, straight off the filesystem ------------------------------
def read_small(path: str) -> str | None:
    try:
        with open(path, "r", errors="replace") as fh:
            return fh.read(4096)
    except OSError:
        return None


def discover_git(start: str) -> tuple[str, str, str] | None:
    """Walk up for a repo. Returns (git_dir, common_dir, toplevel) or None.

    Handles all three shapes of `.git` without running git:
      * a directory        -> ordinary repo, git_dir == common_dir
      * `gitdir: <path>` with a sibling `commondir` file -> linked worktree
      * `gitdir: <path>` without one -> submodule (NOT a worktree, so
        common_dir == git_dir and `linked` stays false, which is correct)
    """
    d = os.path.abspath(start)
    while True:
        g = os.path.join(d, ".git")
        if os.path.isdir(g):
            return g, g, d
        if os.path.isfile(g):
            line = (read_small(g) or "").strip()
            if not line.startswith("gitdir:"):
                return None
            gd = line[len("gitdir:"):].strip()
            gd = os.path.normpath(gd if os.path.isabs(gd) else os.path.join(d, gd))
            common = gd
            c = (read_small(os.path.join(gd, "commondir")) or "").strip()
            if c:
                common = os.path.normpath(c if os.path.isabs(c) else os.path.join(gd, c))
            return gd, common, d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def head_ref(git_dir: str) -> tuple[str, str | None]:
    """(branch, short_sha). branch is 'HEAD' when detached, and then sha is set.

    Reading the file rather than asking git makes detached HEAD *easier*: the
    sha we would otherwise need a second `git rev-parse` for is the file.
    """
    head = (read_small(os.path.join(git_dir, "HEAD")) or "").strip()
    if head.startswith("ref:"):
        ref = head[4:].strip()
        return (ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref), None
    if head:
        return "HEAD", head[:7]
    return "", None


def git_status(cwd: str) -> str | None:
    """The one subprocess. Dirty rows + branch header in a single call."""
    try:
        p = subprocess.run(
            ["git", "status", "--porcelain=v1", "-b", "--untracked-files=normal"],
            cwd=cwd, capture_output=True, text=True, timeout=2.0,
        )
    except Exception:
        return None
    return p.stdout if p.returncode == 0 else None


# --- memory, in-process ------------------------------------------------------
def sample_memory() -> dict[str, float] | None:
    """Swap headroom, RAM free percentage and load, with no subprocesses.

    `vm.swapusage` yields a `struct xsw_usage`; `kern.memorystatus_level` is a
    plain int. Load average is included because it is the *trap*, not the
    signal -- it read 8.1 through the OOM incident -- and printing it beside
    the numbers that were actually true is the only way that stays learned.

    Test seam: `CLAUDE_STATUSLINE_FAKE_MEM="used_mb,total_mb,free_mb,ram_pct,load"`
    substitutes the sample. The real machine can only be in one state at a
    time, so without this there is no way to show the healthy render and the
    pre-OOM render side by side.
    """
    fake = os.environ.get("CLAUDE_STATUSLINE_FAKE_MEM")
    if fake:
        try:
            used, total, free, ram, load = (float(x) for x in fake.split(","))
            return {"swap_used_mb": used, "swap_total_mb": total,
                    "swap_free_mb": free, "ram_free_pct": ram, "load1": load}
        except ValueError:
            return None

    try:
        import ctypes  # imported here: nothing else on this path needs it

        libc = ctypes.CDLL(None, use_errno=True)

        class XSWUsage(ctypes.Structure):
            _fields_ = [
                ("total", ctypes.c_uint64),
                ("avail", ctypes.c_uint64),
                ("used", ctypes.c_uint64),
                ("pagesize", ctypes.c_uint32),
                ("encrypted", ctypes.c_int),
            ]

        buf = XSWUsage()
        size = ctypes.c_size_t(ctypes.sizeof(buf))
        if libc.sysctlbyname(b"vm.swapusage", ctypes.byref(buf), ctypes.byref(size),
                             None, ctypes.c_size_t(0)) != 0:
            return None

        m = {
            "swap_total_mb": buf.total / MB,
            "swap_free_mb": buf.avail / MB,
            "swap_used_mb": buf.used / MB,
        }

        lvl = ctypes.c_int()
        lsize = ctypes.c_size_t(ctypes.sizeof(lvl))
        if libc.sysctlbyname(b"kern.memorystatus_level", ctypes.byref(lvl),
                             ctypes.byref(lsize), None, ctypes.c_size_t(0)) == 0:
            m["ram_free_pct"] = float(lvl.value)

        try:
            m["load1"] = os.getloadavg()[0]
        except OSError:
            pass
        return m
    except Exception:
        return None


def memory_tier(m: dict[str, float]) -> tuple[str, str]:
    """('crit'|'warn'|'ok', which signal tripped)."""
    ram = m.get("ram_free_pct", 100.0)
    used = m.get("swap_used_mb", 0.0)
    free = m.get("swap_free_mb", float("inf"))

    if ram <= CRIT_RAM_FREE_PCT:
        return "crit", f"RAM free at or below {CRIT_RAM_FREE_PCT}%"
    if used >= WARN_SWAP_USED_MB and free < CRIT_SWAP_FREE_MB:
        return "crit", (f"swap past {WARN_SWAP_USED_MB / 1024:.0f} GB used with under "
                        f"{CRIT_SWAP_FREE_MB / 1024:.1f} GB headroom")
    if ram <= WARN_RAM_FREE_PCT:
        return "warn", f"RAM free at or below {WARN_RAM_FREE_PCT}%"
    if used >= WARN_SWAP_USED_MB:
        return "warn", f"swap used at or above {WARN_SWAP_USED_MB / 1024:.0f} GB"
    return "ok", ""


def memory_segment(m: dict[str, float] | None) -> tuple[str | None, str]:
    """(rendered segment or None, reason it is absent/present) -- healthy is silent."""
    if m is None:
        return None, "memory unreadable (sysctl failed)"
    level, signal = memory_tier(m)
    if level == "ok":
        return None, "memory healthy, hidden on purpose"

    bits = [f"swap {m['swap_used_mb'] / 1024:.1f}/{m['swap_total_mb'] / 1024:.1f}G "
            f"({m['swap_free_mb'] / 1024:.1f} free)"]
    if "ram_free_pct" in m:
        bits.append(f"ram {m['ram_free_pct']:.0f}%")
    if "load1" in m:
        bits.append(f"load {m['load1']:.1f}")
    body = " ".join(bits)
    if level == "crit":
        return f"{RED}!! MEM {body}{R}", signal
    return f"{YEL}mem {body}{R}", signal


# --- stdin-supplied fields ---------------------------------------------------
def window_label(size) -> str | None:
    try:
        n = int(size)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"
    if n >= 1000:
        return f"{n // 1000}k"
    return str(n)


def pct_color(p: float) -> str:
    return RED if p >= CRIT_PCT else YEL if p >= WARN_PCT else DIM


def until(epoch_seconds) -> str | None:
    try:
        delta = int(float(epoch_seconds) - time.time())
    except (TypeError, ValueError):
        return None
    if delta <= 0:
        return None
    h, m = divmod(delta // 60, 60)
    d, h = divmod(h, 24)
    if d:
        return f"{d}d{h}h"
    return f"{h}h{m:02d}m" if h else f"{m}m"


USAGE_CACHE = os.path.expanduser("~/.claude/state/usage.json")
USAGE_LOCK = USAGE_CACHE + ".fetching"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
USAGE_REFRESH_S = 60
USAGE_MAX_AGE_S = 300
USAGE_LOCK_S = 30


def fetch_usage() -> None:
    """Child process: ask Anthropic for plan usage and cache it in stdin shape."""
    import urllib.request
    from datetime import datetime

    try:
        raw = subprocess.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True, text=True, timeout=5,
        ).stdout
        token = json.loads(raw)["claudeAiOauth"]["accessToken"]
        req = urllib.request.Request(USAGE_URL, headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
            "User-Agent": "statusline",
        })
        with urllib.request.urlopen(req, timeout=10) as r:
            body = json.load(r)
        rl = {}
        for key in ("five_hour", "seven_day"):
            w = body.get(key)
            if not isinstance(w, dict) or not isinstance(w.get("utilization"), (int, float)):
                continue
            entry = {"used_percentage": float(w["utilization"])}
            if w.get("resets_at"):
                entry["resets_at"] = datetime.fromisoformat(w["resets_at"]).timestamp()
            rl[key] = entry
        os.makedirs(os.path.dirname(USAGE_CACHE), exist_ok=True)
        tmp = f"{USAGE_CACHE}.{os.getpid()}"
        with open(tmp, "w") as f:
            json.dump({"captured_at": time.time(), "rate_limits": rl}, f)
        os.replace(tmp, USAGE_CACHE)
    except Exception:
        pass
    finally:
        try:
            os.unlink(USAGE_LOCK)
        except OSError:
            pass


def read_usage_cache() -> tuple[dict | None, float | None]:
    try:
        with open(USAGE_CACHE) as f:
            c = json.load(f)
        return c.get("rate_limits"), time.time() - float(c["captured_at"])
    except Exception:
        return None, None


def maybe_refresh_usage(age: float | None) -> None:
    """Start one detached fetch when the cache is old; never wait for it."""
    if age is not None and age < USAGE_REFRESH_S:
        return
    try:
        if time.time() - os.path.getmtime(USAGE_LOCK) < USAGE_LOCK_S:
            return
        os.unlink(USAGE_LOCK)
    except OSError:
        pass
    try:
        os.makedirs(os.path.dirname(USAGE_LOCK), exist_ok=True)
        os.close(os.open(USAGE_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "--fetch-usage"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
    except OSError:
        pass


def with_fresh_usage(data: dict) -> tuple[dict, str]:
    """Prefer usage fetched in the last few minutes over the last reply's figures."""
    rl, age = read_usage_cache()
    maybe_refresh_usage(age)
    if isinstance(rl, dict) and rl and age is not None and age < USAGE_MAX_AGE_S:
        return {**data, "rate_limits": rl}, f"fetched {age:.0f}s ago"
    return data, "from last reply (no fresh fetch)"


def rate_limit_segment(data: dict) -> tuple[str | None, str]:
    """`5h 34% 7d 92% resets 3h10m`, or nothing at all.

    Absent is *unknown*, never zero: issue #40094 reports `rate_limits` missing
    entirely on some Max plans -- not null, not an empty object, simply absent
    -- and a confident `0%` there is worse than silence. Every hop is a .get().
    """
    rl = data.get("rate_limits")
    if not isinstance(rl, dict):
        return None, "rate_limits absent from stdin (unknown, not 0%)"

    bits: list[str] = []
    worst = -1.0
    worst_reset = None
    seen: list[str] = []
    for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
        w = rl.get(key)
        if not isinstance(w, dict):
            continue
        raw = w.get("used_percentage")
        if not isinstance(raw, (int, float)):
            continue
        p = float(raw)
        seen.append(label)
        bits.append(f"{pct_color(p)}{label} {p:.0f}%{R}")
        if p > worst:
            worst, worst_reset = p, w.get("resets_at")

    if not bits:
        return None, "rate_limits present but no window carried a used_percentage"

    # The reset clock only earns its width once a window is worth worrying
    # about -- at that point "can I wait it out?" is the actual question.
    if worst >= WARN_PCT:
        left = until(worst_reset)
        if left:
            bits.append(f"{DIM}resets {left}{R}")
    return " ".join(bits), f"rate_limits present ({'+'.join(seen)})"


def context_segment(data: dict) -> tuple[str | None, str]:
    """`ctx 42% /1M`. 42% of 1M and 42% of 200k are different decisions."""
    cw = data.get("context_window")
    if not isinstance(cw, dict):
        return None, "context_window absent from stdin"
    raw = cw.get("used_percentage")
    try:
        p = int(float(raw))
    except (TypeError, ValueError):
        return None, "context_window.used_percentage null (no messages yet)"
    size = window_label(cw.get("context_window_size"))
    tail = f"{DIM} /{size}{R}" if size else ""
    why = "context present" + ("" if size else ", window size absent")
    return f"{pct_color(p)}ctx {p}%{R}{tail}", why


# --- assembly ----------------------------------------------------------------
def build(data: dict) -> tuple[list[str], list[tuple[str, str]]]:
    """(segments, [(field, why present/absent)]) -- the second list feeds --explain."""
    why: list[tuple[str, str]] = []

    model = (data.get("model") or {}).get("display_name") or "claude"
    cwd = (data.get("workspace") or {}).get("current_dir") or data.get("cwd") or os.getcwd()

    parts = [f"{DIM}{model}{R}"]

    # Memory goes second, not last: a critical warning that only exists at the
    # far right of the line is a warning that a narrow terminal truncates away.
    mem, mem_why = memory_segment(sample_memory())
    why.append(("mem", mem_why))
    if mem:
        parts.append(mem)

    parts.append(f"{CYA}{os.path.basename(cwd) or cwd}{R}")

    found = discover_git(cwd)
    if found is None:
        why.append(("git", "no .git found walking up from cwd"))
    else:
        git_dir, common_dir, top = found
        linked = os.path.realpath(git_dir) != os.path.realpath(common_dir)
        branch, sha = head_ref(git_dir)
        why.append(("git", f"repo at {top}" + (" (linked worktree)" if linked else "")))

        # --- branch, called out when it is not home --------------------------
        # A feature branch is *correct* in a worktree and alarming in the main
        # tree, and a marker that fires on every worktree line teaches people
        # to ignore it.
        on_default = branch in DEFAULT_BRANCHES
        if branch == "HEAD":
            parts.append(f"{RED}!! DETACHED HEAD @ {sha or '?'}{R}")
        elif not branch:
            parts.append(f"{DIM}branch?{R}")
        elif on_default:
            parts.append(f"{GRN}{branch}{R}")
        elif linked:
            parts.append(f"{MAG}{branch}{R}")
        else:
            parts.append(f"{RED}!! NOT {'/'.join(sorted(DEFAULT_BRANCHES))} -> {branch}{R}")

        # --- dirty counts + ahead/behind, from one porcelain call ------------
        st = git_status(cwd)
        if st is None:
            parts.append(f"{DIM}git?{R}")
            why.append(("dirty", "git status failed; branch above still read from .git/HEAD"))
        else:
            rows = st.splitlines()
            head = rows[0] if rows and rows[0].startswith("##") else ""
            staged = unstaged = untracked = 0
            for row in rows[1:]:
                if len(row) < 2:
                    continue
                x, y = row[0], row[1]
                if row.startswith("??"):
                    untracked += 1
                    continue
                if x not in " ?":
                    staged += 1
                if y not in " ?":
                    unstaged += 1
            dirty = staged + unstaged + untracked
            if dirty:
                labelled = [(staged, "staged"), (unstaged, "mod"), (untracked, "new")]
                bits = [f"{n} {name}" for n, name in labelled if n]
                parts.append(f"{YEL}{dirty} dirty{R} {DIM}({', '.join(bits)}){R}")
            else:
                parts.append(f"{GRN}clean{R}")
            why.append(("dirty", f"git status ok ({dirty} dirty)"))

            track = ""
            if "[ahead " in head or "[behind " in head:
                seg = head[head.index("[") + 1: head.rindex("]")]
                for token in seg.split(", "):
                    if token.startswith("ahead "):
                        track += f" +{token.split()[1]}"
                    elif token.startswith("behind "):
                        track += f" -{token.split()[1]}"
            elif head and "..." not in head and not on_default:
                # Only worth saying on a feature branch, where it means the work
                # exists nowhere else. On master it is permanent noise.
                track = " no-upstream"
            if track:
                parts.append(f"{MAG}{track.strip()}{R}")

        # --- worktrees: the question that kept getting asked ------------------
        try:
            others = len(os.listdir(os.path.join(common_dir, "worktrees")))
        except OSError:
            others = 0
        if linked:
            parts.append(f"{MAG}wt:{os.path.basename(os.path.realpath(git_dir))}{R}")
        elif others:
            parts.append(f"{DIM}main-tree +{others} wt{R}")
        else:
            parts.append(f"{DIM}main-tree{R}")

    ctx, ctx_why = context_segment(data)
    why.append(("ctx", ctx_why))
    if ctx:
        parts.append(ctx)

    lim, lim_why = rate_limit_segment(data)
    why.append(("limits", lim_why))
    if lim:
        parts.append(lim)

    return parts, why


def render(data: dict) -> str:
    parts, _ = build(data)
    return f" {DIM}|{R} ".join(parts)


RATE_LIMITS_EXPORT = os.path.expanduser("~/.claude/state/rate-limits.json")


def export_rate_limits(data: dict) -> None:
    """Leave the newest `rate_limits` on disk so a session can read its own usage.

    Claude Code hands the figures only to this command, on stdin. Written
    atomically with the time it was seen; absent stays absent, never a zero.
    """
    rl = data.get("rate_limits")
    if not isinstance(rl, dict):
        return
    try:
        os.makedirs(os.path.dirname(RATE_LIMITS_EXPORT), exist_ok=True)
        tmp = f"{RATE_LIMITS_EXPORT}.{os.getpid()}"
        with open(tmp, "w") as f:
            json.dump({"captured_at": time.time(), "rate_limits": rl}, f)
        os.replace(tmp, RATE_LIMITS_EXPORT)
    except Exception:
        pass


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    data, _ = with_fresh_usage(data)
    export_rate_limits(data)
    print(render(data))
    return 0


if __name__ == "__main__":
    try:
        if "--fetch-usage" in sys.argv:
            fetch_usage()
            sys.exit(0)
        if "--explain" in sys.argv:
            # Why is each optional field on the bar, or not? Hidden-because-healthy
            # and hidden-because-no-data are indistinguishable on the bar itself.
            try:
                payload = json.load(sys.stdin)
            except Exception:
                payload = {}
            payload, usage_why = with_fresh_usage(payload)
            segs, reasons = build(payload)
            reasons.append(("usage", usage_why))
            print(f" {DIM}|{R} ".join(segs))
            for field, reason in reasons:
                print(f"  {field:<7} {reason}")
            sys.exit(0)
        sys.exit(main())
    except Exception:
        print("")  # never let the status line be the thing that looks broken
        sys.exit(0)
