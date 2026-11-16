---
name: agent-orchestration
description: >-
  How to run a long session for the user that drives subagents, background jobs and
  branches: when to act versus ask, triaging new work, keeping promises durable,
  writing briefs, isolating agents, integrating their branches, monitoring long
  jobs, and judging whether something is stalled. Load before spawning a
  subagent, starting a background job longer than a few minutes, merging an
  agent's branch, or ending a turn while work is still running. Triggers:
  "spin up agents", "kick off", "in parallel", "merge that", "is it stuck",
  "why have you stopped", "anything left", "keep going", "monitor", "brief".
---

# Agent orchestration

The user steers; they are not the tracking system. Every rule below exists so they never
has to probe for work that was already identified.

## Act, don't ask

- When research or an agent's report yields a recommendation, do it and report
  what was done. Do not hand back a menu.
- Escalate only: irreversible or outward-facing actions; real money; anything
  that changes what a measurement means; a scope or priority call that is their
  and unrecoverable if wrong; input only they can supply (ask once, mark it
  non-blocking, carry on without it).
- Everything else: decide, do, report in a line. On a close call pick the
  reversible option and say which way you went. Replace "Should I…?" with "I did
  X because Y; say if you want it differently."
- When blocked on an escalation, push-notify at once with the options and a
  recommendation, batched into one ping. Keep every unblocked lane moving.
- Surface only when work is done, failed, or genuinely blocked. Do not end turns
  narrating progress of background work; a monitor already notifies.
- Never end a turn on a status report while unblocked work is still owed.
- An agent's completion notice is a scheduling event: before summarising it, ask
  what it just unblocked and start that, then merge, close its tracker row, and
  report result and follow-ups in one message. Hooks that list ready work are a
  safety net, not the scheduler.
- When the project's own gate (preflight, merge gate, health check) passes, act.
  Do not stack a stricter private threshold on top and wait behind it. If the
  gate seems insufficient, run now and label the caveat, or fix the gate. Wait
  only when something named must change first and no instrument can answer now.
- Keep the task list live, work it down unprompted, and sweep it before the
  session ends. Follow-ups found mid-work go on the list when found.

## Triage every new item immediately

1. **Start now** — critical or high severity, data loss or fabrication, a wrong
   published number, or something blocking other work. Severity already is the
   triage decision; do not re-litigate it.
2. **Block** — wanted but waiting on something nameable; record the blocker.
3. **Backlog** — everything else: file it in the project's tracker and close the
   task. Filing is the action.

An agent is earned by importance, not by a free slot or by the work being cheap
and adjacent.

## Make plans and promises durable

- Announcing N actions means creating N task entries before starting the first.
  After any interruption, read the task list before replying and resume from it.
- Before writing "I'll fix that next" or "worth a look later", create the task,
  issue or agent. If it does not earn one, say you are not doing it.
- The moment a background job starts, list the independent work to do meanwhile.
  A running job is never the in-progress task.
- Set a task blocker only when the blocked task consumes the blocker's output.
  Blockers cannot be removed, and a wrong one hides the task from the queue.
- When the user says something should always happen, build a mechanism (hook,
  scheduled job, gate) rather than relying on memory or convention. A mechanism
  that could block normal work must fail open.

## Briefs

- Read the repo's working agreement yourself, then point agents at it by path.
  Do not trust a summary of it, and do not paraphrase its rules from memory.
- Read baselines, counts and tooling instructions out of the repo while writing
  the brief. A stale fact in a brief becomes the agent's specification.
- Guidance from a skill is invisible to subagents: state it inline. Name a
  section of a repo file only after grepping that heading exists.
- When several agents may allocate ids in one tracker, tell each to re-read the
  next id immediately before claiming it and to report which it took. On a
  collision, renumber the less-referenced row.
- Bound searches to the repo; never recurse over a tree that holds agent
  worktrees.
- Pick the specialist agent type that fits. Keep the description to what the
  agent is doing, without a type prefix.
- Durable artifacts and reports to the user never use planning shorthand
  (workstream ids, criterion codes, phase numbers). State what the thing is.
- Test fixtures are authored synthetic data, never copies of the user's real data,
  sanitised or not. Briefs touching fixtures carry this rule.

## Isolation

- File-editing agents get `isolation: "worktree"`, and briefs use repo-relative
  paths. Absolute paths let an agent edit the main tree from inside a worktree.
- Worktree isolation branches the session's own repo. When the target repo
  differs, create the worktree in the target repo yourself and give its path.
- Before trusting an agent's test results, check its base: commits *behind*
  master must be 0, and the worktree must be the right repo.

## Integrating branches

- A finished branch that clears the project's merge gate is merged in the same
  turn as the completion notice, then its branch and worktree are removed, and
  the result reported in a line. Name pre-existing failures rather than holding
  the merge.
- A branch that fails the gate gets a one-line reason; an unmentioned branch
  reads as forgotten.
- Never hand-build a merge with plumbing (`read-tree`, `write-tree`,
  `commit-tree`). Merge with real `git merge` in a scratch worktree, then verify
  every path the branch added survived.

## Long-running jobs

- Any job expected to take five minutes or more gets a monitor the moment it
  starts, unasked. It emits a heartbeat every ten minutes with real progress
  whether or not anything changed, plus failures and the terminal line. One
  monitor per job, retired when the job ends. Never poll with `sleep`.
- Chain dependent jobs in a script that waits on the previous pid, so a sequence
  completes unattended.
- During long waits, pull work forward rather than idling on a monitor.
- A red resource warning is an event: identify the consumers, free what is the
  session's own and idle, and say plainly when the load is the user's apps or a job
  doing its work. Never trim while a load gate is calibrating or a measurement
  is in flight. macOS swap does not shrink when RAM frees.
- "Not finished" is not "broken". Before calling something stalled, state its
  budget and how much is spent. Distinguish stalled from slow with evidence:
  zero CPU with queued work is a stall; CPU burning and memory growing is
  progress. An early diagnosis is a hypothesis and does not get an agent.
- Never quit or kill an application the user launched to free resources; ask,
  naming the consequence. Processes the session started are its own.
- Resource pressure is not a reason to hold back read-only or compile/test
  agents; the harness's concurrency setting is the limit. Only work that would
  disturb a running measurement waits.
