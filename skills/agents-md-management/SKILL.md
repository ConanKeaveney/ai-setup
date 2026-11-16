---
name: agents-md-management
description: >-
  Use when standing instructions future agents read need to change: a project's AGENTS.md,
  "agents file", "working agreement", or the global preferences every project inherits. For
  recording a hard-won fact where the next agent will see it, adding, rewording or retiring a
  rule, bringing every file in line after a convention changes, or deciding scope (one repo or
  all). Triggers: "get this written down", "make this a rule", "that's not true anymore", "where
  should this live". Not for summarising such a file or enforcing via hooks. If CLAUDE.md is
  named, use claude-md-management.
---

Review the completed session for durable facts that would help future work in the same scope.

## Reflect

Identify only reusable information:

- Commands that were verified.
- Code-style or architecture patterns that were confirmed.
- Testing approaches that worked.
- Environment or configuration constraints.
- Safety warnings and recurring gotchas.

Exclude obvious facts, temporary state, one-off fixes, personal secrets, and anything already documented.

## Locate instruction files

Find the active instruction chain starting at the global file — `~/.claude/CLAUDE.md` or `~/.codex/AGENTS.md` — then the `AGENTS.md` files from the project root down to the working directory.

Some may be symlinks or pointers to a single shared copy; run `ls -l` on any `AGENTS.md` before editing it.

Choose the narrowest applicable file. Use the global file only for preferences that should apply across every project; note that editing it changes behaviour for every agent CLI on this machine, not just the one you are running in.

## Propose concise additions

Keep each addition to one short rule or command description. Explain why it belongs at that scope and show the proposed diff before editing.

Do not rewrite unrelated instructions or duplicate rules from broader files.

## Apply deliberately

Update only the additions the user approves, and preserve the file's existing structure.

Length is a real cost rather than a hard limit: every file in the chain is loaded into every session in its scope, so prefer rewriting or pruning an existing entry over appending a new one. If a file has grown past roughly a thousand lines, say so and propose what to cut alongside what to add.

## Maintaining `~/.claude/CLAUDE.md` (the global preferences file)

Rules in any instruction file are written as rules only: no dates, no
measurements or incident stories, no history of why the rule exists.

`~/.claude/CLAUDE.md` is the global instruction file for Claude Code; Codex
reads `~/.claude/CLAUDE.md` or `~/.codex/AGENTS.md`. Keep
the wording tool-neutral: say "your agents directory", not a hard-coded path.

Keep it to knowledge useful in almost every session, in any project. Do not
repeat what the codebase already shows; point at the authoritative file or
command instead.
