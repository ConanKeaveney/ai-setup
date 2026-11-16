import json
import os
import runpy
import sys

from limits import segments


def render(data):
    path = os.path.expanduser("~/.claude/statusline.py")
    renderer = runpy.run_path(path, run_name="opencode_statusline")
    line = renderer["render"](data)
    dim, reset = renderer["DIM"], renderer["R"]
    if not data.get("context_window"):
        line += f" {dim}| ctx unknown{reset}"
    home = os.environ.get("OPENCODE_STATUSLINE_USAGE_HOME")
    for part in segments(renderer, home=home):
        line += f" {dim}|{reset} {part}"
    return line


if __name__ == "__main__":
    try:
        print(json.dumps({"line": render(json.load(sys.stdin))}))
    except Exception:
        print(json.dumps({"line": "status unavailable | ctx unknown | limits unknown"}))
