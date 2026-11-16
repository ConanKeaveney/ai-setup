# AI coding setup

My portable setup for Claude Code, Codex and OpenCode: global instructions, skills, subagents, hooks and status lines.

## Contents

| Path | What it is |
|---|---|
| `CLAUDE.md` | Global instructions: workflow, code quality, git and communication rules |
| `skills/` | Skills: engineering judgement, design docs, code review, data-platform references (Spark, Snowflake, Databricks, Iceberg, OpenSearch, Pulsar, GraphQL), Rust style, verification |
| `agents/` | Claude Code subagents (Python, Rust, ops runner) |
| `codex-agents/` | Codex agent definitions |
| `hooks/` | Claude Code hooks: block shell poll loops; push long answers back to one line |
| `bin/wait-for` | Bounded wait for a log line or condition, used by the agents and hooks |
| `statusline/` | Claude Code status line and subagent status line |
| `opencode/` | OpenCode TUI plugins (status line, subagent panel) and a `cli.json` template |
| `settings.json.in` | Claude Code settings template |

## Install (Claude Code)

Back up `~/.claude` first, then:

```sh
mkdir -p ~/.claude/{skills,agents,hooks,bin}
cp CLAUDE.md ~/.claude/CLAUDE.md
cp -R skills/* ~/.claude/skills/
cp agents/*.md ~/.claude/agents/
cp hooks/*.py ~/.claude/hooks/
cp bin/wait-for ~/.claude/bin/ && chmod +x ~/.claude/bin/wait-for
cp statusline/*.py ~/.claude/ && chmod +x ~/.claude/*statusline.py
sed "s|@HOME@|$HOME|g" settings.json.in > ~/.claude/settings.json
```

If you already have a `settings.json`, merge the `hooks` and `statusLine` blocks instead of overwriting it.

## Install (OpenCode)

```sh
cp -R opencode/statusline opencode/subagents ~/.config/opencode/
sed "s|@HOME@|$HOME|g" opencode/cli.json.in > ~/.config/opencode/cli.json
```

## Tests

```sh
python3 hooks/test_no_poll_loop.py
python3 hooks/test_one_line_default.py
(cd opencode/statusline && node --test)
(cd opencode/subagents && node --test)
```

## Customise

The skills `career-growth`, `engineering-leadership`, `engineering-principles` and `staff-engineer` are written for "the user"; edit them to fit your role and company.
