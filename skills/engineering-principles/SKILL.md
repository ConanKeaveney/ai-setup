---
name: "engineering-principles"
description: "The user's knowledge base of lessons and rules for technical judgement — simplicity, system design, reliability, incidents, performance, code quality and engineering with AI — use when they're making a technical or architecture decision, reviewing a design or code, dealing with an incident, or asks to add new lessons to it. Triggers: \"is this over-engineered\", \"build or buy\", \"should we use a cache\", \"how should I design this\", \"architecture trade-off\", \"postmortem\", \"incident review\", \"cascading failure\", \"why is this slow\", \"performance\", \"code review\", \"how strict should review be\", \"refactor\", \"tech debt\", \"AI coding\", \"agents\", \"verification\"."
---

# Engineering Principles Playbook

A growing set of lessons the user has collected on technical judgement and building good systems. Use it as a lens for decisions, not a script.

## How to use this

- When the user brings a technical decision (a design, a trade-off, an incident, a review, how to use AI tools), find the lessons below that apply and use them to shape the advice. Name the lesson briefly (e.g. "Caches have two states") so they can see where it comes from.
- When a decision touches a tradeoff (see Tradeoffs below), present both sides and say which fits their situation, rather than picking one silently.
- If nothing here applies, say so and answer from general good judgement — don't force a fit.
- When they are writing or reviewing a design doc, load the `design-doc` skill alongside this one.
- Keep answers concise and in plain English.

## Adding new content

When the user shares new material (an article, talk, book notes) and asks to add it:
1. Pull out only the lessons that are actionable and worth remembering — skip filler and restated points.
2. Write each as a short bold rule plus one or two sentences on why / how to apply it, in your own words, ending with the source's name in brackets, e.g. "(Marc Brooker)".
3. Put it under the best-fitting section below (add a new section only if none fits); merge with an existing lesson if it says the same thing, adding the new name to its brackets. Team and management lessons go to `engineering-leadership` and career ones to `career-growth`.
4. If a new lesson contradicts an existing one, keep both and add or extend an entry under Tradeoffs.
5. Add the source to the Sources list, once per person.

---

## 1. Judgement & choosing problems

- **Picking the problem is most of the work.** Finding, scoping and validating the right problem matters more than execution; aim at validated customer needs, not extra features. (Nimit Sohoni, Ethan Evans)
- **Find big problems from both ends.** Look top-down at where customers waste time or suffer operational pain, and bottom-up at shifts in hardware and infrastructure that make a new design possible. (Marc Brooker)
- **The simplest thing that solves it wins.** Impact is rewarded, not complexity; a simple fix with the same result beats an impressive system. (Evan King, James Cowling, Simon Kindström)
- **Instrument before you change.** Put the measurement (an A/B test, a metric, a baseline) in place before shipping a fix, so its impact is proven rather than claimed; a one-line fix measured this way showed $2M a year. (Steve Huynh)
- **Check the obvious signal first.** When a sophisticated approach underperforms, step back and look for a cheap, plain input you've ignored before building more machinery. (Evan King)
- **Pragmatism beats dogma.** "Good enough" designs that fit real constraints routinely beat purist ones; don't build for theoretical scale or edge cases you don't have. (Adam Ernst, Ilya Grigorik, Steve Huynh)
- **Prefer proven tools unless it's your edge — but know when defaults break.** Use battle-tested solutions by default; build custom only where it is a core advantage or the vendor default genuinely fails at your scale. (Simon Kindström, Adam Ernst)
- **Match rigour to the phase and the layer.** Early, exploratory work wants speed, light process and tolerance for debt; mature systems and core platforms want slow, careful thought about second-order effects. (Stefan Mai, Ilya Grigorik)
- **Start small, then scale.** In unfamiliar territory, solve a small bounded piece first, and test an unproven idea with the simplest, hackiest experiment before committing a team to it. (Nimit Sohoni, James Everingham)
- **Spot the dead end early.** Seniority is less about running faster than about avoiding wasted motion: read the warning signs and steer away before the team is deep in. (Philip Su)
- **Technology only counts inside a product people love.** Strong engineering creates lasting value when it serves an excellent user experience. (Philip Su)
- **Ask whether it's a technology war or a distribution war.** A better product routinely loses to one with default placement or bundling; know which fight you're in. (James Everingham)
- **Optimise globally, not locally.** Teams resist a shared platform because their own setup "works fine", but consolidation brings org-wide wins in efficiency and shared tooling. (Joakim Recht)
- **Be lazy on purpose.** Refusing to do repetitive manual work, and automating it away for everyone, is how impact scales. (Joakim Recht)
- **Build what should exist, not what's fashionable.** Industry consensus that a field is solved or impossible is often wrong; ignore hype and pessimism alike. (Bryan Cantrill)
- **Own the layer that is your moat.** A thin wrapper over someone else's platform breaks whenever they change; control the core where your advantage lives. (Nimit Sohoni)

## 2. System design & architecture

- **Performance is an architecture decision.** You can defer micro-tuning, but not the structure: serial network calls or opaque data layouts can't be profiled away later. (Casey Muratori)
- **Let abstractions come from working code.** Prototype against real constraints before drawing boxes in a design doc, and test proposed interfaces with experiments. (Casey Muratori)
- **Organise around data, not deep class hierarchies.** Cross-cutting features break inheritance trees; composing behaviour over shared data stays flexible. (Casey Muratori)
- **Scale by removing coordination.** Throughput at scale comes from eliminating contention points between nodes more than from faster hardware. (James Cowling)
- **Make failure understandable.** Real simplicity means that when the system breaks it is still easy to reason about and debug; that is what lasts. (James Cowling)
- **Take on multi-region complexity only if the product demands it.** Active-active setups carry heavy latency and operational cost; most products are better off without them. (James Cowling)
- **Understand the layer below.** Designing software with real knowledge of the hardware and runtime beneath it produces better systems than treating them as a black box. (Bryan Cantrill, Casey Muratori)
- **Declare the goal state and let the system reconcile.** Replace procedural runbooks and scripts with declared intent and an orchestrator that closes the gap automatically. (Joakim Recht)
- **Make the right way the easy way.** Design frameworks with minimal setup and no boilerplate so best practice is the path of least resistance. (Adrien Friggeri)
- **Fit the design to the data.** Choose structures based on the data's real shape and redundancy, and combine approaches when each has a blind spot the other covers. (Nimit Sohoni)
- **Know where your paradigm stops working.** Every model has a sweet spot — declarative UI suits nested scrolling feeds, not heavy drag-and-drop — so drop down a level outside it. (Adam Ernst)
- **A platform needs product-market fit with its developers.** Technical elegance doesn't drive adoption; know exactly who the users are and meet them in the tools they already use. (Adam Ernst)
- **Write down why, not just what.** Recording the reasoning lets future maintainers tell deliberate constraints from guesses they can safely change. (Marc Brooker)

## 3. Reliability, incidents & operations

- **Caches have two states.** A cache gives you a warm fast mode and a cold broken mode; under load a cold cache can overload the backend so it never refills. Prefer complete materialised views, backends that scale on their own, or push-based warming. (Marc Brooker)
- **Design against congestion collapse.** When one node fails and others absorb its work, load can spiral; find and break those positive feedback loops before they cascade. (James Cowling, Marc Brooker)
- **Postmortems go past the line of code.** Ask why tests missed it, why validation was built that way, and what tooling or org gap let it through. (Marc Brooker)
- **Fix the architecture, not the symptom.** When the same class of incident or vulnerability keeps returning, patching each one is wallpaper; change the platform or the design. (Marc Brooker, Bobby Holley)
- **Layer your defences.** Assume any one control will fail: combine sandboxing, process isolation and continuous fuzzing. (Bobby Holley)
- **Heroics are a smell.** Teams that keep systems alive through heroic effort are stuck in break-fix and never improve the architecture. (Marc Brooker)
- **Stay close to on-call.** Production failures teach what theory can't; senior engineers learn most from staying on the pager. (Marc Brooker)
- **Build operational hygiene in, not on.** Telemetry, alarms, canary rollouts, automated rollback and blameless reviews let people ship fast without fear. (Steve Huynh, David Singleton)
- **Find the edge of your velocity.** Push rollout speed until you see negative signals; if nothing ever breaks, you're probably moving too slowly. (Jake Bolam)
- **Ship early and iterate.** Simple running code in users' hands beats polished code held back or stuck in long refactors; real feedback earns more credibility. (Ethan Evans, Simon Kindström, Joakim Recht)
- **Use feature flags, not long-lived branches.** Keep everyone on trunk with continuous integration and flag unfinished work so the codebase stays stable and testable. (Ryan Olson)

## 4. Performance

- **"Premature optimisation" doesn't mean ignore performance.** The warning was against micro-tuning non-critical paths at the cost of clarity, not against designing for speed. (Casey Muratori)
- **Slow software is doing work it doesn't need to.** Look for hidden overhead first, especially dynamic-language checks and indirection that run on every operation. (John White)
- **Keep types visible to the compiler.** Tiny functions behind dynamic dispatch block inlining and vectorisation; small functions are only cheap when the compiler can see through them. (Casey Muratori)
- **Prove invariants once, not every call.** Strong guarantees checked at compile time beat runtime checks and human vigilance, for speed and for safety — a memory-safe language removes whole classes of bugs. (John White, Bobby Holley)
- **Compete on shared benchmarks.** Private benchmarks invite narrow tuning; a shared, agreed benchmark aligns everyone on real-world speed. (Bobby Holley)

## 5. Code quality, review & ownership

- **Scale review rigour to blast radius.** Inspect core and shared infrastructure hard; review leaf or feature-flagged code quickly and with trust. (Jake Bolam)
- **Default to "accept with nits".** Don't block on style; flag the risk, approve, and trust the author to fix it before landing. (Jake Bolam)
- **Deleting code is high-value work.** Removing dead code and needless abstraction and unifying duplicate systems often takes more skill than adding features. (Michael Novati)
- **Every line you add is yours to own.** New code is ongoing maintenance; be ready to chase its bugs across team boundaries. (Michael Novati)
- **Taste comes from repetitions.** Good API, data-model and refactoring judgement takes thousands of reps with tight feedback; there is no shortcut. (Michael Novati)
- **Debug through other teams' layers.** Rather than throwing a bug over the wall, follow it deep into the framework or build system yourself; the ability to drop into an unfamiliar codebase cold and find the real flaw is what marks the strongest engineers. (Adam Ernst, Evan King, Philip Su)
- **Search before you build.** In a large codebase someone has usually solved it already; strong code search beats typing speed. (Evan King)
- **Senior work makes complexity disappear.** Staff-level engineering is simplifying the architecture so others can execute, and breaking big ambiguous goals into clear, owned milestones. (Simon Kindström)

## 6. Engineering with AI

- **Value moves to judgement and taste.** As generation gets cheap, the scarce skills are problem definition, system design, trade-offs and checking output — technical depth matters more, not less. (Ethan Evans, Thariq Shihipar, James Cowling, Michael Novati)
- **Build the system that builds the system.** Put effort into the harness — sandbox, tests, environment, permissions — that lets models work autonomously, rather than into the code itself. (Thariq Shihipar)
- **Invest in verification over prompt tweaking.** Reliability comes from far more automated tests, fixtures, UI checks and runtime assertions than you'd write by hand, to match the higher code velocity. (Thariq Shihipar)
- **Keep instructions minimal, context rich.** Give a capable model clear intent, the right permissions and clean interfaces rather than long rules, and feed it real structure (source files, schemas, design components) instead of lossy screenshots. (Thariq Shihipar)
- **Let agents use their tools.** Explicitly allow sub-agents, iterative loops and compute on hard problems. (Thariq Shihipar)
- **Show your working on generated code.** Share the prompts, alternatives tried and failed attempts with reviewers so they can trust a large diff. (Thariq Shihipar)
- **Redefine quality.** Care less about naming and formatting, more about architectural cohesion, clear boundaries, iteration speed and how quickly you can recover or undo. (Thariq Shihipar)
- **Plan in short value cycles.** Aim for value in one to two months, and defer non-critical refactors that the next model may make cheap. (Thariq Shihipar)
- **Wrap agents in a deterministic control plane.** Non-deterministic agents need hard limits around them — circuit breakers, rate limits, access policies and observability — before they run in serious workflows. (James Everingham)
- **Adopt AI on measured results, not fear.** Bring tools in when they demonstrably improve speed and quality, and don't put generated code into production without the domain knowledge to judge it. (Casey Muratori)
- **Stay hands-on with agentic tools.** You can't direct work you haven't done yourself; senior engineers who don't experiment soon hold an outdated picture of what works. (Marc Brooker)

## Tradeoffs

- **Move fast vs. protect the core.**
  - Fast: ship early, push rollout speed until something breaks, plan in short value cycles. (Ethan Evans, Simon Kindström, Joakim Recht, Jake Bolam, Thariq Shihipar)
  - Careful: think slowly about core platforms, and on cross-team changes be certain of edge cases, because one bad break costs more trust than many wins earn (see `engineering-leadership`). (Ilya Grigorik, Stefan Mai, Michael Novati)
  - When each wins: blast radius decides — leaf, flagged or exploratory work goes fast; shared infrastructure, public APIs and mature systems get the careful path.
- **Design for performance vs. don't over-engineer.**
  - Up front: performance is architectural, and some structures can't be profiled away later. (Casey Muratori)
  - Pragmatic: the simplest thing wins; don't build for scale you don't have. (Evan King, James Cowling, Steve Huynh, Ilya Grigorik, Adam Ernst)
  - When each wins: keep a structural path to speed on hot paths and data layouts from day one; leave scale machinery (sharding, multi-region, caches) until the load is real.
- **Prototype first vs. design doc first.**
  - Code first: let abstractions come out of working code. (Casey Muratori)
  - Doc first: writing a design doc sharpens reasoning even if it's abandoned. (Marc Brooker, Steve Huynh)
  - When each wins: in unfamiliar or performance-sensitive territory, spike first and let the doc record what the prototype proved; for cross-team or well-understood work, write first to align.
- **Refactor now vs. defer.**
  - Now: deleting code and fixing the architecture rather than the symptom is high-value work. (Michael Novati, Marc Brooker, Bobby Holley)
  - Defer: aim for value within one to two months and skip non-critical refactors the next model may make cheap. (Thariq Shihipar)
  - When each wins: do the refactors that remove recurring failures or real complexity now; defer cosmetic or speculative clean-up.
- **Shared platform vs. autonomous teams.**
  - Consolidate: a shared platform delivers org-wide wins over each team's local "works fine". (Joakim Recht)
  - Decouple: small teams with few dependencies ship fastest (see `engineering-leadership`). (James Everingham, Ryan Olson)
  - When each wins: consolidate stable, commodity layers such as storage, deploys and hosts; keep fast-moving product bets free of platform dependencies until they have proven themselves.

---

## Sources

- Ethan Evans (former VP, Amazon) — "Amazon VP: Questions On Corporate Politics But They Get Increasingly Darker"
- Philip Su (ex-Distinguished Engineer IC9, Meta and OpenAI) — "OpenAI & Meta Distinguished Engineer (IC9): Working With Zuck, Carmack & Career Growth"
- Steve Huynh (ex-Principal Engineer L7, Amazon) — "Amazon Principal Engineer (L7): Layoffs, Interviewing & Career Growth"; A Life Engineered — "Want To Get Promoted? Don't Wait to Act Senior Level"
- Jake Bolam (Principal Engineer IC8, Instagram) — "Instagram Principal Engineer (IC8): Promotions, Breaking Prod, Tech Leading"
- Stefan Mai (co-founder Hello Interview, ex-Senior EM Meta, ex-SDM Amazon) — "Meta Senior Manager (M2): Manager Career Growth, PIPs, Amazon vs Meta"
- Casey Muratori (game and systems programmer) — "Casey Muratori: The Anatomy of a 35-Year Mistake, "Clean Code" Horrible Performance"
- Marc Brooker (Distinguished Engineer, AWS) — "AWS Distinguished Eng: Learning From 3000 Incidents And How Engineering Is Changing"
- Evan King (ex-Staff Engineer IC6, Meta; startup founder) — "25 Year Old Staff Eng @ Meta (Promotion Story)"
- Ilya Grigorik (Distinguished Engineer L10, Shopify; ex-Google) — "Shopify Distinguished Eng (L10): Principal+ Engineering, Career Story, Regrets"
- David Singleton (ex-Stripe CTO, ex-Google VP) — "Ex-Stripe CTO: Hiring Without Leetcode, Career Growth, Coding as a Leader (Career Story)"
- Adam Ernst (Distinguished Engineer IC9, Meta) — "Meta Distinguished Eng (IC9): Influencing Engs, Failures, and Learnings"
- Bryan Cantrill (co-founder and CTO, Oxide; ex-Sun Distinguished Engineer) — "Distinguished Eng: Stack Ranking, Competing with Bezos, Regrets"
- Nimit Sohoni (AI researcher, ex-Citadel Securities quant, Stanford PhD) — "Ex-Citadel Quant and AI Researcher: Breaking In, Tech vs Finance Careers"
- Simon Kindström (Staff Engineer IC6, Instagram) — "26 Year Old Meta Staff Eng (IC6): Promotions, Redefining Expectations, Secret Equity Bonuses"
- Michael Novati (ex-Senior Staff Engineer IC7, Facebook; co-founder Formation) — "Meta Senior Staff Eng (IC7): Zuck Stories, Rapid Career Growth, Code Machine Archetype"
- Thariq Shihipar (engineer on Claude Code, Anthropic) — "How Anthropic Builds And How Engineering Will Change Soon"
- James Cowling (ex-Principal Engineer, Dropbox; CTO and co-founder, Convex) — "Dropbox's Former Most Senior Eng: Building Great Systems and Advice for the AI Era"
- John White (ex-Director of Engineering, PyTorch / Meta Superintelligence Labs) — "Meta Superintelligence Labs (MSL) Eng Director: Promo Hacking, Industry Shifts, Regrets"
- Joakim Recht (ex-Distinguished Engineer, Uber) — "Uber Distinguished Eng: Unfair Promos, Influence, Engineering Regrets"
- Adrien Friggeri (Principal Engineer IC8, Meta) — "New Grad to Principal Engineer (IC8) at Meta (Career Story)"
- Bobby Holley (CTO, Mozilla Firefox) — "Mozilla Firefox CTO: Chrome vs Firefox and Distinguished Eng Promos"
- Ryan Olson (ex-Principal Engineer IC8, Instagram; co-founder Retro) — "Instagram iOS Principal Eng (IC8): Building IG Stories, 1 Promo Per Half, Small Teams"
- James Everingham (ex-Head of Engineering, Instagram; ex-Netscape; founder Guild) — "Ex-Head of Eng at Instagram: Career Regrets and Learnings"
