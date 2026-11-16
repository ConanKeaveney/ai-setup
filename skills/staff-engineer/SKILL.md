---
name: staff-engineer
description: >-
  The user's operating manual for being a Staff Engineer at whatever company they are at. Load whenever
  they ask what they should be focusing on, what their priority is right now, whether something is
  worth their time, how to handle leadership, roadmap or stakeholders, how to start in a new job,
  how to prepare for a review or promotion, or whether they are "operating at staff level".
  Trigger phrases: "what should I be working on", "what's my priority", "is this worth my time",
  "am I doing staff work", "staff engineer", "how do I get to principal", "first 90 days",
  "new job", "onboarding", "listening tour", "stakeholders", "leadership wants", "roadmap",
  "1:1 with my manager", "managing up", "sponsor", "brag doc", "promo case", "performance review",
  "should I say no to this", "I'm too busy", "glue work". Evergreen: carries the framework, not any
  company's current priorities — those are looked up fresh each time.
---

# Staff Engineer

A staff engineer is judged by what the organisation achieves **because of them**, not by what
they ship personally. Every answer this skill gives comes back to that.

## Step 1 — get the live context before advising

This file holds no company facts. Company facts live in a
`leadership-priorities.md` note the user keeps for the current company — read it
first if it exists, and offer to update it when they learn something new (after a 1:1, a planning
cycle, a reorg). If it doesn't exist, offer to create one from their meeting notes. Then fill any
gaps from their notes, meeting transcripts, task list, or by asking one question:

1. **Where they are in tenure** — first 30 days, 30–90, or established. The advice differs sharply.
2. **What leadership currently cares about** — the manager's and their manager's stated
   priorities, the roadmap, the OKRs. If this isn't known, *finding out is the priority*.
3. **What is on their plate** — current projects, commitments, what is stalled.
4. **What the next level is asking of them** — any feedback on the gap to the next level.

If 2 is unknown or stale (older than a quarter, or a reorg happened), say so and make
"go and ask" the first recommendation.

## Step 2 — the four things that count

Distilled from public engineering ladders (Dropbox, GitLab,
CircleCI, Carta). A piece of work is staff-level when it has all three of the first:

| Dimension | Test |
|---|---|
| **Scope** | Needs alignment across teams, or several engineers on the team. Not something they could do alone in a sprint. |
| **Impact** | Moves a measurable goal leadership already tracks — cost, reliability, revenue, velocity, a customer metric. If they can't name the number, it isn't impact yet. |
| **Technical complexity** | A genuinely hard design, data-model, migration or rollout problem. |
| **Multiplier** | Other engineers get better or faster because of it — mentoring, guardrails, docs, a reusable pattern, unblocking. |

A common rule of thumb for a promotion case: **three or more projects of 3+ months** that each
hit scope, impact and complexity, plus "mastery in role" (running the team well, operational
excellence, mentoring, inclusion). Use that as the yardstick for "is my year on track".

**Next level up (Principal) differs mainly in breadth:** driving initiatives across a whole org
rather than a team cluster, and mentoring many people rather than a few. Scope of a project that
"one team could own" reads as staff, not principal.

## Step 3 — choosing what to work on

**Work on, in this order** (Larson, *Work on what matters*):
1. **Existential issues** — survival, stability, money at risk. Drop everything else.
2. **What leadership is already pulling on** that is **under-resourced** — high attention, low
   crowding. Crowded flagship work gives little marginal impact.
3. **Finish stalled things** — a stuck project is risk; finishing it is leverage.
4. **Edit, don't author** — reshape someone else's plan so it lands, broker the consensus it needs.
5. **Foster growth** — mentoring has leverage comparable to a hire.
6. **What only they can do** — work that won't happen without them.

**Avoid:**
- **Snacking** — easy, low-impact work that feels productive.
- **Preening** — high-visibility, low-impact work.
- **Chasing ghosts** — fixing problems from the *previous* company. The classic new-hire trap.
- **Hero coding** — shipping the most tickets while multiplying no one.
- **Local optimisation** — over-weighting their own team's needs over the org's.

**Quick check for any request on their time** (Reilly): is this the most important thing they could
be doing *from the organisation's point of view*? Does it build credibility, relationships or
skills? If none, say no or hand it off.

## Step 4 — leadership, roadmap and alignment

- **Authority is loaned** by their manager and sponsor; keep it topped up (Larson).
  - Never surprise the manager. Feed them context — scaling pain, cross-team friction — as
    intelligence, not complaints.
  - Ask directly in 1:1s what they're worried about and what they'd want done differently.
- **Have a sponsor at director level or above** and a written, agreed view of what success looks
  like at 6 and 12 months.
- **Translate platform work into business outcomes** in the words product and leadership use.
- **Radiate intent** (Reilly): announce what they're going to do so people can object, rather than
  asking permission for everything.
- **Glue work is real staff work, but only if visible.** Agree it with the manager explicitly, or
  it reads as "not technical enough" at review time.
- **Write things down.** Design docs → after ~5, synthesise a strategy (Larson, *Write five then
  synthesize*). Better wrong than vague. When actually writing or reviewing one, load the
  `design-doc` skill.

## Step 5 — new-job playbook (first 90 days)

**Days 0–30: listen and map.**
- Week 1: manager 1:1 — priorities, roadmap, what a great first 90 days looks like, what worries them.
- Weeks 1–2: leadership above the manager — org priorities, how the team is judged.
- Weeks 1–4: listening tour of every stakeholder — downstream consumers, upstream producers,
  PM, peers, on-call owners. Ask everyone the same questions: what's working, what hurts, what
  would you fix first, what would you want from someone in my role.
- Read the existing roadmap, OKRs, recent design docs, ADRs and incident postmortems.
- Build Reilly's three maps: **locator** (where the team sits, what the business needs from it),
  **topographic** (how decisions really get made, who holds informal power, past failed attempts
  and why), **treasure** (the agreed destination — or the fact that there isn't one).

**Days 30–60: play back and plan.**
- Write up what they heard; play it back to the manager and peer staff engineers; correct it.
- Pick a few under-resourced, high-pull problems. Agree 30/60/90 expectations and the path to the
  next level with the manager.
- Start a peer network of other staff+ engineers.

**Days 60–90: earn credibility.**
- Early wins on real pain: unstick a stalled project, fix a hot spot (flaky pipeline, cost spike,
  quality incident), sharpen an important design doc.
- Ship some code in the core systems.
- Only then propose a strategy. **No premature rewrites** — find out why the fence is there first.

**Throughout:** keep a brag doc from day 1 (wins, numbers, links), and send the manager weekly
context.

## Step 6 — what senior leaders reward (lessons from real hiring loops)

Patterns directors, managers, PMs and principal engineers actually probed for or said they value:

- **Drive and mentor at breadth.** The bar above staff is "drives a lot, mentors a lot of
  people" across teams. Delivering well on one team's projects reads as staff, not beyond.
- **Data/platform as a product.** A long-term vision, named customers, a roadmap a PM can
  partner on — not a pile of pipelines.
- **Opportunity cost out loud.** Buy what isn't a core competency; build only where it's the
  edge. Weigh vendor risk and total cost of ownership, not just running cost. Don't prematurely
  optimise.
- **Challenge the status quo, with numbers.** Leaders want "here's what I changed and what it
  moved", not hypotheticals.
- **Calm and shipping.** PMs value stability and steady delivery over constant re-architecture;
  big migrations need a reason the business feels.
- **Know the stakeholder map.** A good PM may already have dozens of stakeholders tiered — ask
  for it rather than rebuilding it.
- **Safe rollouts.** Small batches, stress tests, never trust a third party's docs blindly.
- **Simplicity.** Cut scope; build what's asked; question features nobody needs yet.
- **Have a view on AI vs the platform.** "Won't the AI just do it?" is a live question for any
  data team — be ready to explain why modelling, quality and semantics still matter.

## Step 7 — managing technical quality (when quality is the problem)

Climb only as far as needed (Larson): fix hot spots → adopt proven practices one at a time →
invest in leverage points (interfaces, stateful systems, **data models**) → align team direction
via design review → measure quality → quality team → org-wide programme.

## How to answer

The user wants the answer first, in one line, in plain English. For "what should my priority be":
give **the one thing**, why it beats the alternatives in a sentence (tie it to the dimensions
above), and what to drop or defer. Expand only if they ask. If the live context from Step 1 is
missing, say what's missing and recommend getting it — don't invent the company's priorities.

## Sources

Will Larson,
staffeng.com and *Staff Engineer*; Tanya Reilly, *The Staff Engineer's Path* and "Being Glue";
Keavy McMinn on starting as a staff engineer; public Dropbox / GitLab / CircleCI / Carta ladders.
