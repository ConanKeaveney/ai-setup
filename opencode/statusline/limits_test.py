import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error

import limits


RENDERER = {"pct_color": lambda p: "", "R": ""}


class LimitsTests(unittest.TestCase):
    def test_01_missing_stale_future_invalid_and_expired_are_not_zero(self):
        now = time.time()
        for capture, expected in (({}, "unknown"), ({"captured_at": now - 301}, "stale"),
                                  ({"captured_at": now + 1}, "unknown")):
            self.assertIn(expected, limits.segment("Claude Code", capture, now, RENDERER))
        for value in (None, {}, {"used_percentage": -1}, {"used_percentage": True},
                      {"used_percentage": float("nan")}, {"used_percentage": 101},
                      {"used_percentage": 50, "resets_at": now - 1}):
            snapshot = {"captured_at": now, "rate_limits": {"five_hour": value}}
            self.assertEqual(limits.segment("Claude Code", snapshot, now, RENDERER),
                             "Claude Code limits unknown" if value is None else "Claude Code 5h ?")

    def test_01b_old_claude_capture_shows_last_known_usage_with_age(self):
        now = time.time()
        old = {"captured_at": now - 627, "rate_limits": {
            "seven_day": {"used_percentage": 1, "resets_at": now + 3600}}}
        self.assertEqual(limits.segment("Claude Code", old, now, RENDERER),
                         "Claude Code 7d 1% used, week 99% through (resets in 1h00m) as of 10m ago")
        old["captured_at"] = now - 2 * 86400 - 3600
        self.assertEqual(limits.segment("Claude Code", old, now, RENDERER),
                         "Claude Code 7d 1% used, week 99% through (resets in 1h00m) as of 2d1h ago")
        expired = {"captured_at": now - 627, "rate_limits": {
            "seven_day": {"used_percentage": 1, "resets_at": now - 1}}}
        self.assertEqual(limits.segment("Claude Code", expired, now, RENDERER),
                         "Claude Code limits stale")

    def test_02_real_windows_and_partial_claude_usage(self):
        now = time.time()
        claude = {"captured_at": now, "rate_limits": {
            "seven_day": {"used_percentage": 73, "resets_at": now + 3600}}}
        self.assertEqual(limits.segment("Claude Code", claude, now, RENDERER),
                         "Claude Code 7d 73% used, week 99% through (resets in 1h00m)")
        claude["rate_limits"]["five_hour"] = {"used_percentage": 12, "resets_at": now + 90}
        self.assertEqual(limits.segment("Claude Code", claude, now, RENDERER),
                         "Claude Code 5h 12% used (resets in 2m) 7d 73% used, week 99% through (resets in 1h00m)")
        codex = {"captured_at": now, "rate_limits": {
            "primary_window": {"used_percent": 18, "reset_at": now + 3600,
                               "limit_window_seconds": 604800}, "secondary_window": None}}
        self.assertEqual(limits.segment("Codex", codex, now, RENDERER, codex=True),
                         "Codex 7d 18% used, week 99% through (resets in 1h00m)")
        codex["rate_limits"]["secondary_window"] = {
            "used_percent": 0, "reset_at": now + 90000, "limit_window_seconds": 18000}
        self.assertIn("5h 0% used (resets in 1d1h)",
                      limits.segment("Codex", codex, now, RENDERER, codex=True))
        codex["rate_limits"]["primary_window"]["reset_at"] = now + 5 * 86400 + 15 * 3600
        self.assertIn("7d 18% used, week 20% through (resets in 5d15h)",
                      limits.segment("Codex", codex, now, RENDERER, codex=True))

    def test_03_fetch_authentication_timeout_and_redirect_refusal(self):
        auth = {"tokens": {"access_token": "fixture-token", "account_id": "fixture-account"}}
        response = {"rate_limit": {"primary_window": {"used_percent": 23}, "secondary_window": None}}
        with patch("limits.urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(json.dumps(response).encode())
            self.assertEqual(limits.fetch_codex(auth), response["rate_limit"])
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, limits.USAGE_URL)
            self.assertEqual(request.get_header("Authorization"), "Bearer fixture-token")
            self.assertEqual(request.get_header("Chatgpt-account-id"), "fixture-account")
            self.assertEqual(opener.return_value.open.call_args.kwargs["timeout"], 1.5)
        self.assertIsNone(limits.NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.org"))

    def test_04_cache_throttle_auth_failure_and_account_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            root = home / ".codex"
            root.mkdir()
            path = root / "auth.json"
            def sign_in(account):
                path.write_text(json.dumps({"tokens": {"access_token": "fixture-token", "account_id": account}}))
            sign_in("fixture-a")
            with patch.dict(os.environ, {"CODEX_HOME": str(root)}):
                calls = []
                def fetch(auth):
                    calls.append(auth)
                    return {"primary_window": {"used_percent": 25}}
                now = time.time()
                first = limits.codex_snapshot(home, now, fetch)
                self.assertEqual(limits.codex_snapshot(home, now + 10, fetch), first)
                self.assertEqual(len(calls), 1)
                for cache in (home / ".cache/opencode-statusline").glob("*.json"):
                    self.assertEqual(cache.stat().st_mode & 0o777, 0o600)
                    self.assertNotIn("fixture-token", cache.read_text())
                def failed(auth):
                    raise urllib.error.HTTPError(limits.USAGE_URL, 401, "Unauthorized", {}, None)
                fallback = limits.codex_snapshot(home, now + 61, failed)
                self.assertEqual(fallback["captured_at"], first["captured_at"])
                self.assertEqual(limits.codex_snapshot(home, now + 62, fetch), fallback)
                sign_in("fixture-b")
                self.assertEqual(limits.codex_snapshot(home, now + 63, failed), {"checked_at": now + 63})
                sign_in("fixture-a")
                stale = limits.codex_snapshot(home, now + 400, failed)
                self.assertEqual(limits.segment("Codex", stale, now + 400, RENDERER, codex=True),
                                 "Codex limits stale")


if __name__ == "__main__":
    unittest.main()
