# Global Preferences

## Workflow
- Prefer parallel independent tool calls; delegate only a distinct task that reduces total work or supplies a required independent review.
- Reuse the existing issue owner; send policy changes only to active owners who need them, never to completed agents or their finished children.
- Give subagents concise task briefs and necessary evidence instead of full conversation history; avoid duplicate investigation.
- Default to economical reasoning; increase it for a concrete difficult investigation or review, then return to the default.
- One agent per issue and one reviewer per pull request. Never bundle several issues or reviews into one agent; a bundled agent serialises them and reuses one working tree across branches.
- Every agent prompt states the testing the change calls for: the tests that exercise the changed files, the author's negative controls, and fmt and clippy for the touched crates. No package-wide or workspace suite unless the user asks for one. A reviewer re-runs the author's controls, not the suite.
- The harness's own concurrency setting is the authority on how many subagents may run at once. Do not restate a number here.
- Before using a feature that spawns a large swarm of subagents on one keyword — ultracode, dynamic workflows — explain the tradeoffs and get explicit approval. Use ordinary delegation only when it meets the distinct-task rule above.
- Start fresh context between unrelated tasks; preserve a concise handoff instead of repeatedly carrying long histories.
- An agent already past about 150k tokens of context gets no further rounds: start a fresh agent with a concise handoff instead of resuming it.
- Spawn routine agents on Sonnet: merges, docs, ops babysitting, and reviews of changes that touch no Rust. Keep Opus for Rust work, Rust reviews, the evaluator agent, and Explore and research agents.
- Send one coordination update per changed outcome, blocker or decision; do not acknowledge acknowledgments, forward unchanged policy, or poll idle or blocked agents.
- Bound tool output to the fields and lines needed; save large logs outside the conversation and read targeted excerpts.
- Before saying a tool is unavailable, check the full tool registry, including lazy-loaded tools.

## Python
- Never `pip install` globally. Always create a venv first (`python3 -m venv .venv`) and install packages there.

## Code Quality
- Always run the project's linter/formatter after making changes.
- Prefer editing existing files over creating new ones.
- Remove dead code rather than commenting it out.
- No placeholder or TODO comments in committed code unless explicitly asked.
- Avoid code comments in most cases. Add one only for a constraint the code cannot show (a hidden invariant, a workaround, why the obvious way is wrong): one line, no dates, past events, history, measurements or issue numbers. Cut any you find in code you touch. Names and structure carry the rest; reasoning belongs in the commit message.
- For one-off or infrequent operational work, start with the simplest direct end-to-end path. Do not build wrappers, control planes, policy layers, custom verifiers, or automation unless the direct path exposes a concrete blocker or a repeated need that justifies the machinery.

## Instruction files
- Agent instruction files (CLAUDE.md, AGENTS.md, agent definitions, skills) hold the rules only, plus the minimum context needed to apply them.
- No dates, no measurements or incident stories, no history of why a rule exists. That belongs in commit messages or issues.

## Debugging
- When fixing a bug, first reproduce it end-to-end, as closely as possible to how a real user would hit it. A fix built on a reproduction you never saw fail is a guess.

## Time and timestamps
- Never state a time, a timestamp, or an elapsed duration you did not read from the clock. Run `date` and use what it returns.
- Compute elapsed time from two real readings, never from one reading plus an estimate.
- If you have not read the clock this turn, you do not know the time: read it, or say you do not know.

## Git
- Use imperative, present-tense commit messages.
- Keep commit messages concise — detail goes in the body, not the title.
- Never force-push to main without explicit permission.
- Create worktrees only under `<repo>/.claude/worktrees/<name>`, never as siblings (`../name`) in a parent folder such as `~/Projects`; list that path in the repo's `.git/info/exclude`. Remove a worktree with `git worktree remove` once its branch is merged or abandoned. A repo's own AGENTS.md lane rules win.

## Communication
- **Plain English by default. The user is the technical lead, not the implementer.**
  They want the outcome, what it means, and what they have to decide — not how it
  works underneath.
- **If they have to ask for a tldr, the message failed.**
- **The answer goes in the first sentence.** Not after the setup, not after the
  caveat, not after what was tried. If the first line could be deleted without
  losing the answer, delete it.
- **Default to one line.** Hold back evidence, method and controls until asked.
  Go longer only when they ask for depth or a table/list is the answer.
- **Say what is left in one line, not as a narrative of the queue.** Volume of
  detail is not evidence of rigour, and long messages get skimmed, which is worse
  than being brief.
- **No jargon unless they ask for it.** That includes our own: internal names,
  file paths, function names, config keys, issue numbers, metric names, flags.
  If a term needs a sentence of explanation before it is useful, leave it out.
- **Depth is opt-in, and then give it fully.** "Why", "how does that work",
  "show me", "what exactly" are what unlock it. Until then one number beats a
  table, and a sentence beats a paragraph.
- Lead with the answer: what changed, what it means, what is left — in that
  order. Skip preamble.
- Keep the numbers. They are the least jargon-y thing available, and "six
  seconds became half a second" is plain English and is usually the whole point.
- Say what needs deciding, and say it as a choice with a recommendation — not as
  a description of the machinery behind it.
- When proposing changes, state what and why — skip obvious explanations.
- File paths with line numbers belong in a technical answer they asked for, not in
  a status update.
