---
name: "engineering-leadership"
description: "The user's knowledge base of lessons and rules for being a strong engineer and engineering leader — use when they're making an engineering, team, management or leadership decision, or asks to add new lessons to it. Triggers: \"how should I handle this person\", \"underperformer\", \"PIP\", \"team culture\", \"reorg\", \"org design\", \"team size\", \"skip-level\", \"managing managers\", \"delegation\", \"influence without authority\", \"get another team to adopt this\", \"working with execs\", \"managing up\", \"hiring\", \"mentoring\"."
---

# Engineering & Leadership Playbook

A growing set of lessons the user has collected on being a strong engineer and engineering leader. Use it as a lens for decisions, not a script.

## How to use this

- When the user brings a decision (team, process, career, technical trade-off, communication), find the lessons below that apply and use them to shape the advice. Name the lesson briefly (e.g. "Culture is the behaviours you accept") so they can see where it comes from.
- When a decision touches a tradeoff (see Tradeoffs below), present both sides and say which fits their situation, rather than picking one silently.
- If nothing here applies, say so and answer from general good judgement — don't force a fit.
- Keep answers concise and in plain English.
- Sibling skills: `career-growth` for their own promotions, moves and politics; `engineering-principles` for technical judgement; `staff-engineer` for what they should be working on right now.

## Adding new content

When the user shares new material (an article, talk, book notes) and asks to add it:
1. Pull out only the lessons that are actionable and worth remembering — skip filler and restated points.
2. Write each as a short bold rule plus one or two sentences on why / how to apply it, in your own words, ending with the source's name in brackets, e.g. "(Ethan Evans)".
3. Put it under the best-fitting section below (add a new section only if none fits); merge with an existing lesson if it says the same thing, adding the new name to its brackets. Career lessons go to `career-growth` and technical ones to `engineering-principles`.
4. If a new lesson contradicts an existing one, keep both and add or extend an entry under Tradeoffs.
5. Add the source to the Sources list, once per person.

---

## 1. Stay close to the work

- **Take regular "engineer-cations".** However senior you get, spend 2–3 days a quarter doing a small, real ticket in the codebase. It gives first-hand feel for tooling, build times and developer pain. (David Singleton)
- **Keep a friction log.** While doing real work (or onboarding onto a new platform), write down every point of friction — what you tried, what got in the way, what would fix it. It turns vague "dev experience" complaints into concrete improvements. (David Singleton)
- **Know the work at ground level.** Leaders who understand the day-to-day toolchain ask much sharper strategic questions. If "engineer" is in your title, keep writing code: architects who stop coding propose designs that don't work. (David Singleton, Jake Bolam, Joakim Recht, Ryan Olson)
- **Lead from the front when it counts.** In high-stakes pushes, step into reviewing diffs, fixing bugs and writing code rather than standing above execution; it earns more trust than authority does. (Ryan Olson, Joakim Recht)
- **Shadow partner teams.** Sit with sales, support, design etc. Seeing their friction shows which engineering work actually helps the business. (David Singleton)
- **Keep a rough 75/25 split between doing and talking.** Spend most of your time practising the craft and the rest teaching and communicating. Pure talkers go shallow; pure doers have no leverage. (Marc Brooker)

## 2. Managing vs. building

- **Avoid being IC and manager on the same project.** You'll get swallowed by your own tasks and stop unblocking your team. If you code, pick work off the critical path. (David Singleton)
- **Step onto the balcony.** Regularly step back from the day-to-day and look at how the whole team and system are working together — incentives, structure, bottlenecks. (David Singleton)
- **Choose management for the right reasons.** Not because it feels like the next rung — only if you genuinely get energy from helping others achieve more together than alone. (David Singleton)
- **Lead only where the team would pick you.** You're ready to lead when the team would elect you; engineers quickly see through a nominal leader they don't trust or respect. (Philip Su)
- **Give accountability, not oversight.** "Leading by example" often means the lead grabs every visible or firefighting task and the team goes passive. Hand over full ownership with clear expectations and check-ins instead of reviewing line by line. (James Cowling)
- **Give away the hard design problems; take the grunt work yourself.** Hand challenging architecture to growing engineers with support, and pick up the maintenance and operational chores yourself. (Joakim Recht)
- **Use micromanagement only as a short-term repair.** It can rescue a struggling team, but as a default it smothers good engineers; set the outcome, clear obstacles and give autonomy. (James Everingham)
- **Scale by delegating, not by out-working everyone.** Past senior level the job shifts from being the workhorse to setting others up to execute; what got you here won't get you there. (Evan King, Ethan Evans)
- **Measure yourself by how little the team needs you.** The best sign of senior leadership is a team that keeps executing well after you quietly step back, because you spent your effort multiplying them. (Ilya Grigorik, Adrien Friggeri)
- **Don't be territorial about scope.** Welcome stronger or more senior people onto your area; enabling teammates beats competing with them. (Evan King)
- **Mentor across org lines.** Mentoring people well outside your team breaks silos and spreads good practice further than formal programmes. (Joakim Recht)
- **Expect senior roles to be mostly people work, under scrutiny.** Beyond staff, the hard bottleneck is friction between teams, feedback and politics rather than code; meetings grow and so does the attention on you. Decide you want that before you chase the role. (Philip Su)

## 3. Performance, culture & teams

- **Happy ≠ high-performing.** A team that's 100% content is rarely at its best. Good teams have "Type 2 fun": hard in the moment, rewarding looking back. (David Singleton)
- **Deal with underperformance directly and quickly.** High performers need to see peers pulling their weight, and keeping a bad manager or a poor fit drains morale faster than replacing them. Act early and humanely. (David Singleton, Ethan Evans)
- **Don't let a ranking system have your hard conversations for you.** Forced curves turn teammates into rivals and tempt managers to keep weak people as cover; yet without any forcing function many managers simply stop giving tough feedback. Have the conversations regardless of the system. (Bryan Cantrill, Ethan Evans)
- **Only start a PIP you believe can be passed.** Most PIPs are written as exits and the manager's mind is already made up. If it is a real path back, make the bar concrete and reachable; if it isn't, be honest and handle the exit well. (Ethan Evans, Stefan Mai)
- **Culture is the behaviours you accept.** What a leader tolerates or models becomes the standard. Stepping over a problem (tech debt, sloppy code) sets it as the new baseline. (David Singleton)
- **Care about craft.** Small polish — like error messages that tell the user how to fix the problem — compounds into quality people remember. (David Singleton)
- **Tell a winning story.** Teams run on momentum: define what winning looks like, keep repeating the wins so far and where you're heading. (Stefan Mai)
- **Build heist-movie teams.** Aim for complementary specialists who together solve what no one could alone, not a room of the same profile. (Bryan Cantrill)
- **Hire for values and motivation, not just skill.** Technically strong hires who don't share the team's values are the most damaging mistakes; make the process rigorous and writing-heavy. (Bryan Cantrill)
- **Interview on real work, not puzzles.** Pair on a real toolchain or debug realistic code instead of abstract algorithm questions. (David Singleton)
- **Leadership owns failure.** Success belongs to the team; when an organisation fails, look first at leadership's decisions. (Bryan Cantrill)
- **Cross-train away single points of failure.** One irreplaceable expert is a fragility, however convenient day to day. (Ethan Evans)
- **Goals are proxies — check what they make people do.** Teams can hit every goal and still miss the actual strategy, and promotion-driven cultures build things to clear a bar or delay good changes to land in the right half. Regularly check the goals still point at the outcome. (Ethan Evans, John White)
- **Judge leaders by outcomes, not headcount.** Empire building happens because heads are easy to count and impact is hard to defend; insist on measuring the business result. (Ethan Evans)
- **Give direction without killing bottom-up initiative.** High-autonomy teams need a clear strategy from leaders, or energy goes into low-impact work. (Bobby Holley)
- **Let engineers push back.** Strong orgs give developers room to challenge product assumptions, cut scope and build their own tooling to remove friction. (Michael Novati)
- **Don't force a technical pivot on enthusiasm.** Adopting a new technology on vibes, without buy-in from the engineers closest to the problem, creates friction and risk. (Bobby Holley)
- **Kill failing projects early and clean up fully.** Trust your gut sooner instead of pouring more in. Help users migrate off, delete the code, and write a candid public postmortem; owning the failure earns more credibility than hiding it. (Adam Ernst)
- **Protect customer trust over short-term gain.** Lock-in and broken promises may lift a quarter but corrode the culture and the business; keep the long-term mission ahead of pure value capture. (Bryan Cantrill, Bobby Holley)

## 4. Org design & operations

- **Senior leaders build systems, not just routines.** Line managers run 1:1s and project goals; managers of managers design the operating system — rituals, nested review cadences that connect strategy to projects, ops reviews, deploy pipelines. (David Singleton)
- **Shift left so you don't have to trade speed for safety.** Strong automated testing and gradual (canary) rollouts let teams ship daily and still stay highly reliable. (David Singleton)
- **Give remote teams whole missions.** Each site should own something end to end so it can work a full day without waiting on other time zones. Seed a new site with people who commit for years, not a short rotation, so the culture takes root. (David Singleton, Philip Su)
- **Keep teams small when speed matters.** A small, talent-dense team with end-to-end ownership and few dependencies ships fastest; extra headcount adds communication drag, boundary disputes and code bloat. (Ryan Olson, James Everingham)
- **Add explicit structure past about 150 people.** Informal coordination breaks down at that size; clear charters, ownership and communication channels become necessary. (James Everingham)
- **Protect pockets of agility as you grow.** Deliberately create small low-bureaucracy groups where engineers can still build quickly. (Ryan Olson)
- **Split the CTO and VP Engineering jobs.** The CTO owns technical vision, experiments and the external developer brand; the VP Engineering owns execution, structure, staffing, process and reviews. (James Everingham)
- **Name teams after missions, not systems.** A team named after its system will defend that system even when it should be replaced; a team named after the problem won't feel threatened by a better answer. (James Cowling)
- **Shape the org like the architecture you want.** Module boundaries end up mirroring team boundaries because talking across teams is costly, so design the teams first. (Casey Muratori)
- **Review incidents weekly with leaders in the room.** A standing postmortem review keeps senior attention on systemic reliability and spreads the learning. (Marc Brooker)
- **Cut low-value recurring meetings.** Drop tiered status syncs and oversight committees; keep alignment direct and ad hoc so people spend their time building. (Jake Bolam)
- **Build a champions network for rollouts.** A working group of product engineers on the receiving end gives feedback within hours rather than waiting for org-wide complaints. (Jake Bolam)
- **Never go around your managers.** When managing managers, skip-levels must not turn into leading questions or fixing their team's issues directly — it undermines them and erodes trust. (Stefan Mai)
- **Read reorgs as several moves at once.** A reorg usually shifts scope, retains key people, handles underperformers and consolidates power simultaneously; understand all the motives before reacting or designing one. (Ethan Evans)
- **Ring-fence a little room for long shots.** Keep most effort tied to current goals but reserve a small slice for prototypes with large upside. (Ethan Evans)

## 5. Influence & working with executives

- **Lead through influence, not title.** Pulling rank gets compliance at best. Earn respect daily with competence and clear reasoning, and explain the context, market and architecture behind each decision. (James Cowling, Evan King, Simon Kindström, Steve Huynh, Ethan Evans)
- **Agree the why before arguing the how.** Most team friction is a disagreement about why the work exists (speed vs stability, say); once that is settled, implementation choices tend to follow. (James Cowling)
- **Take 98% alignment over 100% correctness.** A team pulling together on a near-right answer achieves far more than one split over the last details. (Philip Su)
- **Do the migration for them.** Instead of an RFC asking other teams to do tedious work, build the scaffolding, make the change yourself and hand them something to sign off. (Adam Ernst)
- **Prove adoption small before mandating it.** Make it work for your own team or a few modules, show it's reliable, then spread to willing neighbours before making it the standard. (Jake Bolam, Joakim Recht)
- **Seed new tools through onboarding.** New hires have no legacy habits, so bootcamps and onboarding are the cheapest place to introduce a tool; then support existing users to earn their trust. (Adrien Friggeri)
- **Plant ideas early and let others own them.** Introduce an idea gently and repeatedly so people adopt it and champion it as their own. (Joakim Recht)
- **Persuade with data, documents and prototypes.** A working prototype and a clear written proposal move multiple teams faster than argument. (Steve Huynh)
- **Speak each function's language.** Frame technical work in the other side's incentives — latency as conversion, refactors as lower cost — and learn the context and jargon of product, legal, marketing and PR with some humility. (Ilya Grigorik, Steve Huynh, Bobby Holley)
- **When parachuted into ambiguity, ask before you prescribe.** Build cross-functional relationships fast, ask experts open questions to build your mental model, then set a clear direction. (Ilya Grigorik)
- **Take disagreements to a call.** Resolve technical disputes face to face or on video rather than in long threads; tone and shared intent come through. (Adam Ernst)
- **Win through allies and compromise.** Recruit respected peers who can argue for the idea in their own style, and adopt the good parts of competing proposals so everyone has a stake. (Adam Ernst)
- **Use code review to spread standards.** Explain why a pattern should change rather than demanding nits, never shame people in public, and stay open to context you lack. (Adam Ernst, Philip Su)
- **Spend credibility carefully on cross-cutting changes.** Wide refactors need trust from every team they touch; be certain about edge cases, because one bad break costs more trust than many good changes earn. (Michael Novati)
- **See distant teams' work up close before judging it.** The further away a team is, the simpler its problems look; go and learn the edge cases first. (Ethan Evans)
- **Bring your boss options, not raw problems.** Lay out choices with clear trade-offs so the decision is easy. (Ethan Evans)
- **Pitch to the kind of executive in front of you.** Founders can take existential bets and back people on conviction; professional CEOs probe the numbers and hold you to execution. Shape the ask accordingly. (Ethan Evans)
- **Build executive presence.** It comes from composure, decisiveness and clear communication, and shows when people seek your judgement outside your own area. (Ethan Evans)

## 6. Communication & personal effectiveness

- **Prepare to align, don't wing it.** Spend about twice the meeting length preparing when you're addressing a team or org, so you bring useful context and a clear story. (David Singleton)
- **Give context before the answer.** When asked something, briefly explain the bigger picture first — it grounds people and turns answers into learning. (David Singleton)
- **Own your week with a priorities doc.** Each Sunday, write what a successful week looks like and use it as your reference point, rather than letting inbox and calendar set the agenda. (David Singleton)
- **Write to think, and to scale.** Writing forces rigour and aligns large groups without endless meetings; even an abandoned design doc sharpens your reasoning. Keep it concise, read good prose, edit hard, and read others' specs like a critic. (Steve Huynh, Marc Brooker, Stefan Mai, Philip Su, Bobby Holley)
- **Let AI write the routine updates, not the reasoning.** Automate status summaries; draft your own strategy, key decisions and pitches, because the drafting is where the thinking happens. (Thariq Shihipar, Bobby Holley)

## Tradeoffs

- **Stay hands-on vs. get out of the team's way.**
  - Hands-on: keep coding and lead from the front in crunches. (David Singleton, Jake Bolam, Joakim Recht, Ryan Olson)
  - Step back: don't be IC and manager on the same project; leading by example can leave the team passive, so delegate. (David Singleton, James Cowling, Evan King, Ethan Evans)
  - When each wins: code off the critical path and step in during real crunches; on the core work, hand over ownership and hold people accountable.
- **Light process vs. operating structure.**
  - Light: cut recurring status meetings and keep alignment ad hoc. (Jake Bolam)
  - Structure: nested reviews, weekly incident reviews and explicit charters past about 150 people. (David Singleton, Marc Brooker, James Everingham)
  - When each wins: small, high-trust teams stay light; as the org grows or reliability is at stake, add mechanisms that replace lost informal contact, but never pure status meetings.
- **Forced ranking vs. no forcing function.**
  - Against: stack ranking turns teammates into rivals and tempts managers to keep weak people as cover. (Bryan Cantrill)
  - For: without one, many managers stop having hard performance conversations. (Ethan Evans, Stefan Mai)
  - When each wins: avoid forced quotas where you have the choice, but replace them with a firm habit of honest conversations; inside a ranking system, don't let it make the decisions for you.
- **Talk it through vs. write it down.**
  - Talk: resolve disagreements face to face or on video. (Adam Ernst)
  - Write: writing forces rigour and scales alignment. (Steve Huynh, Marc Brooker, Stefan Mai, Philip Su, Bobby Holley)
  - When each wins: talk when there is tension or views are far apart; write when the decision needs rigour, many readers or a record — often talk first, then write it up.

---

## Sources

- David Singleton (ex-Stripe CTO, ex-Google VP) — "Ex-Stripe CTO: Hiring Without Leetcode, Career Growth, Coding as a Leader (Career Story)"
- Ethan Evans (former VP, Amazon) — "Amazon VP: Stack Ranking & PIPs, Working With Bezos, His Promotions"; "Amazon VP: How Corporate Politics Work And How To Win"; "Amazon VP: Questions On Corporate Politics But They Get Increasingly Darker"
- Steve Huynh (ex-Principal Engineer L7, Amazon) — "Amazon Principal Engineer (L7): Layoffs, Interviewing & Career Growth"
- Jake Bolam (Principal Engineer IC8, Instagram) — "Instagram Principal Engineer (IC8): Promotions, Breaking Prod, Tech Leading"
- Stefan Mai (co-founder Hello Interview, ex-Senior EM Meta, ex-SDM Amazon) — "Meta Senior Manager (M2): Manager Career Growth, PIPs, Amazon vs Meta"
- Casey Muratori (game and systems programmer) — "Casey Muratori: The Anatomy of a 35-Year Mistake, "Clean Code" Horrible Performance"
- Marc Brooker (Distinguished Engineer, AWS) — "AWS Distinguished Eng: Learning From 3000 Incidents And How Engineering Is Changing"
- Evan King (ex-Staff Engineer IC6, Meta; startup founder) — "25 Year Old Staff Eng @ Meta (Promotion Story)"
- Ilya Grigorik (Distinguished Engineer L10, Shopify; ex-Google) — "Shopify Distinguished Eng (L10): Principal+ Engineering, Career Story, Regrets"
- Adam Ernst (Distinguished Engineer IC9, Meta) — "Meta Distinguished Eng (IC9): Influencing Engs, Failures, and Learnings"
- Philip Su (ex-Distinguished Engineer IC9, Meta and OpenAI) — "OpenAI & Meta Distinguished Engineer (IC9): Working With Zuck, Carmack & Career Growth"; "OpenAI & Meta Distinguished Eng (IC9): The Psychology Behind Tech Career Peaks"
- Bryan Cantrill (co-founder and CTO, Oxide; ex-Sun Distinguished Engineer) — "Distinguished Eng: Stack Ranking, Competing with Bezos, Regrets"
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
