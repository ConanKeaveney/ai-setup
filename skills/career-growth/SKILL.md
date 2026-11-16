---
name: "career-growth"
description: "The user's knowledge base of lessons and rules for growing an engineering career — promotions, levelling, politics, choosing companies and teams, IC vs manager, interviews, offers and salary negotiation, layoffs and long-term fulfilment — use when they're making a career decision about himself, or asks to add new lessons to it. Triggers: \"should I take this job\", \"should I switch teams\", \"how do I get promoted\", \"am I ready for the next level\", \"am I misleveled\", \"promo conversation\", \"corporate politics\", \"my manager\", \"getting credit\", \"visibility\", \"IC or manager\", \"job hopping\", \"startup or big tech\", \"interview prep\", \"behavioural interview\", \"negotiate\", \"salary negotiation\", \"job offer\", \"counter offer\", \"comp\", \"equity\", \"raise\", \"retention offer\", \"layoffs\", \"PIP\", \"burnout\", \"regrets\"."
---

# Career Growth Playbook

A growing set of lessons the user has collected on building an engineering career. Use it as a lens for decisions, not a script.

## How to use this

- When the user brings a career decision (a move, a promotion, a hard manager, an offer, an interview), find the lessons below that apply and use them to shape the advice. Name the lesson briefly (e.g. "Ride the escalator") so they can see where it comes from.
- For "what should I be working on", "is this worth my time", staff-level operating, a new-job 90-day plan or building a promo case, use the `staff-engineer` skill instead; this file covers the career around that work.
- When a decision touches a tradeoff (see Tradeoffs below), present both sides and say which fits their situation, rather than picking one silently.
- If nothing here applies, say so and answer from general good judgement — don't force a fit.
- Keep answers concise and in plain English.

## Adding new content

When the user shares new material (an article, talk, book notes) and asks to add it:
1. Pull out only the lessons that are actionable and worth remembering — skip filler and restated points.
2. Write each as a short bold rule plus one or two sentences on why / how to apply it, in your own words, ending with the source's name in brackets, e.g. "(Ethan Evans)".
3. Put it under the best-fitting section below (add a new section only if none fits); merge with an existing lesson if it says the same thing, adding the new name to its brackets. Team and management lessons go to `engineering-leadership` and technical ones to `engineering-principles`.
4. If a new lesson contradicts an existing one, keep both and add or extend an entry under Tradeoffs.
5. Add the source to the Sources list, once per person.

---

## 1. Promotions & levelling

- **Operate at the next level before asking for it.** Most of it needs no permission: ask how someone one or two levels up would do this work, and do it that way now. Expect to show it consistently for one or two review cycles before the title follows. (Simon Kindström, Steve Huynh)
- **Promotion runs on evidence, not effort.** Excelling at your level only proves you fit your level. Before starting, ask how you'll measure the impact, and set up the measurement before the change: a junior engineer A/B-tested a one-line fix, proved it was worth $2M a year, and was promoted on the spot. (Steve Huynh)
- **Don't let current-level work slip while you stretch.** If baseline duties drop, managers conclude you can't handle more. Know the minimum bar, streamline or delegate at-level work, and turn down optional work to make room. (Steve Huynh)
- **Fewer, bigger things.** Committees compare like with like; one large, visible project with clear scope is far easier to justify than several medium ones or a pile of maintenance. (Steve Huynh)
- **Raise promotion yourself, early and explicitly.** Tell a new team your ambitions on day one, and agree timeline, expectations and the exact gaps with your manager long before review season. (Evan King, Jake Bolam, Simon Kindström, Ethan Evans)
- **Ask "under what circumstances would I be the top candidate?"** It turns a vague promise into concrete criteria you can work against. (Ethan Evans)
- **Flag misleveling early.** Levels are partly a retention tool; if you think you're under-levelled, say so before calibration sets the baseline. (Ryan Olson)
- **Build consensus before calibration.** For senior promotions, line up sponsors and executive alignment months before the committee meets; great work alone isn't enough. (Adrien Friggeri)
- **Own the promotion calendar.** Know the cycle dates and deadlines yourself; managers, especially new ones, miss them. (Ethan Evans)
- **Strike a deal with your manager.** Offer to take on whatever they most need done, in exchange for them making sure you are rewarded for it. (Ethan Evans)
- **Bank early wins.** A quick, visible fix to real pain — a crash, a slow start-up — earns the trust to choose bigger, more autonomous projects later. (Ryan Olson)
- **Top ratings come from creating opportunities, not executing well.** The highest ratings go to people who open up new work for the team, not those who finish their assigned scope perfectly. (Simon Kindström)
- **Take the scary, unpopular projects.** Fast promotions come from the work others call impossible or dull. A failure is recoverable; a success defines your reputation — and most people who do this aren't more talented, just willing to try. (Jake Bolam, Ethan Evans, John White)
- **Overcommunicate when you go off-piste.** Before stepping away from core work to explore something risky, agree it explicitly with your manager so you have a safety net. (Adrien Friggeri)
- **Finish core work fast to buy a time budget.** Speed on the assigned work frees time for initiative, extra problems and relationships, which is what compounds. (Evan King)
- **Know what each level is really asking for.** Mid-level is shipping well-defined work; senior is architecture, mentoring and unblocking; staff and above is finding the ambiguous business problem, setting direction across teams and simplifying shared systems. At the top the difference is qualitative — solving what five more mid-level engineers couldn't — and levels track how many engineers your work affects. (Steve Huynh, Michael Novati, Philip Su, Joakim Recht)
- **Push for promotions early, then let them become a by-product.** Chasing the next title helps at first; later, levels come from solving the organisation's biggest problems, and pinning managers to checklists or gaming committees backfires. (Philip Su, Bryan Cantrill, Simon Kindström, David Singleton, Bobby Holley, Joakim Recht)
- **Become the go-to person on something core.** Being the expert on a key system or workflow gives outsized leverage. (Evan King)
- **Don't let expertise become a shackle.** Stay too long and you become the permanent maintainer of what you built; hand it off before it traps you. (Stefan Mai)
- **Spend some time on work that won't show up in review.** Ad hoc help, mentoring and small fixes build the trust and informal authority that later makes big work possible. (Jake Bolam)

## 2. Visibility, politics & self-advocacy

- **Being right isn't enough.** If the same friction follows you from job to job, you are the common factor. Emotional intelligence and relationships matter as much as technical skill past a certain level. (Ethan Evans)
- **Be warm in tone, firm in substance.** Pressing politely and repeatedly for outcomes works; being abrasive shuts people down, and being passive gets you overlooked — leaders give attention and good work to people who would be costly to lose. (Ethan Evans)
- **Make big asks without ultimatums.** Frame them around shared stakes — "my career matters a lot to me; I need to know how much it matters here" — rather than "promote me or I quit". (Ethan Evans)
- **Know your leverage.** Promotions, role changes and exits are negotiated on leverage: being hard to replace, having outside options, or saving leadership time. (Ethan Evans)
- **Be the colour commentator.** When a PM or leader announces a launch, follow up with the technical story — the trade-offs, the scale it handles — so your part is visible. Treat it as aligning people and crediting others, not bragging. (Ethan Evans, Bobby Holley)
- **Keep your headline simple.** Senior people remember one memorable line about what you built, not the nuance; decide what that line is. Model it on past promotion announcements: one or two sentences of scale and impact. (Ethan Evans, Steve Huynh)
- **Performance is a story — shape yours.** The same facts can be told as quality or as nitpicking, and outcomes depend on business priorities and how well your manager presents the case. Don't wait to be marked like an exam; document and frame your own work. (Ethan Evans, Steve Huynh, Joakim Recht)
- **Solve your leader's worst problem.** Ask your manager what is hurting them most and take it off their plate; scope isn't zero-sum, and relieving a leader's friction earns ownership faster than competing for it. (Ethan Evans, Adrien Friggeri)
- **Put boundaries on low-value work.** Turn down or trade the chores with humour and negotiation, or tie an unappealing task to the good project that follows it. (Ethan Evans)
- **Get comfortable in grey areas.** Code is binary; careers and organisations run on incomplete information and subjective trade-offs. (Ethan Evans)
- **Politics is how people share resources — engage or specialise.** You can't opt out of it unless you become so uniquely skilled in a critical niche that the organisation gives you autonomy. (Ethan Evans)
- **Assume your manager owns the narrative.** HR exists to protect the company, and in a conflict the manager has usually framed things first; act and document early. (Ethan Evans)
- **Use your access to leadership.** Directors and skip-levels are detached from ground truth and want direct feedback from engineers; go to the office hours. (John White)
- **Build your network by giving.** Share tools, run knowledge sessions and help without keeping score; ask a would-be mentor how you can help with their work rather than asking them to mentor you. Relationships, even built mostly in writing, are what sustain a career. (Ethan Evans, James Everingham, 2025 compilation)

## 3. Choosing companies, teams & moves

- **Ride the escalator.** Fast-growing companies and areas lift your career while you climb, and a static org stalls you whatever your effort. Build skills somewhere reputable, then take that experience to a smaller, high-growth place once growth stalls. (Ethan Evans, 2025 compilation)
- **Pick companies like an investor.** Judge the market, the business model and the competition, not just the tech stack; market leaders can afford creative bets while followers tend to run fast-follow checklists. (James Everingham, Philip Su)
- **Optimise early for people and problems, not pay.** Work with the best people on the hardest problems, cluster where talent is dense, and pick fit and trajectory over small salary or equity differences; that early network compounds for decades. (James Cowling, Michael Novati, James Everingham)
- **Stay long enough to see your decisions play out.** Hopping helps early on, but at senior levels a move every 18–24 months reads as a red flag, and you never learn whether your designs were good. (Stefan Mai, James Cowling)
- **Move when the learning curve flattens.** Following genuine curiosity to new problem spaces gives the best long-run growth. (Marc Brooker, Ilya Grigorik)
- **Go where your work is valued.** Hard work in an area leadership doesn't prioritise earns little recognition; if your strengths (say, infrastructure over product) aren't rewarded, move to a team that does reward them. (Jake Bolam, 2025 compilation)
- **Pick craft-focused, why-driven teams.** Avoid orgs where promotion is the real product; teams that care about quality and explain why the work exists grow you faster. (John White, James Cowling)
- **Choose the day-to-day you'd enjoy.** Decide between big company, startup and specialist niche by what you want an ordinary day to look like, not by fear or others' expectations. (Casey Muratori, Adam Ernst)
- **Big tech for depth, startups for breadth.** Large companies need and grow deep specialists; small teams can't justify specialist roles, so they need generalists who touch everything from ops to vendors. (Evan King, Philip Su)
- **Bet early on emerging tools.** Becoming an early expert in a new platform lets a junior engineer skip the usual experience queue. (Ryan Olson)
- **Build a base, then take the risk.** A stable, well-paid start makes it easier to join an early-stage company later during a big technology shift. Startups also make it easier to switch into a new discipline such as research, which otherwise needs a degree or proof of work. (Nimit Sohoni)

## 4. Archetypes, IC vs manager & identity

- **Be the only, not the best.** Stacking several skills at a strong level (engineering, writing, data, design, business sense) is more durable than chasing the top 1% of one narrow specialty, and lets you bridge silos. (Ilya Grigorik, Adrien Friggeri, 2025 compilation)
- **Treat IC and manager as a seesaw, not a ladder.** A tour as a manager makes you a far better senior IC partner to executives, and stepping back to IC isn't a demotion. (Ilya Grigorik, Simon Kindström)
- **Keep the way back open.** Don't let lifestyle or ego inflate with title and pay, or you lose the freedom to step down; thriving at a lower level beats barely treading water at a higher one. (Philip Su)
- **Stay IC if the craft is what you love.** If coding and debugging energise you more than alignment and people work, that is a valid long-term path. (Adam Ernst)
- **Senior IC comes in several shapes.** Top ICs can be codebase stewards, industry standard-setters or ecosystem builders; pick the shape that fits you. (Bobby Holley)
- **Decouple identity from level.** At the top levels, stop asking whether each piece of work is "worthy" of your level; work on what matters and check in with leadership. (Adam Ernst)
- **Expect a ceiling.** Everyone eventually runs out of skill, energy or organisational room for the next level; higher levels need matching opportunity, not just talent. (Philip Su)
- **Ship rough work in public.** Seniority breeds over-filtering of ideas for fear of not meeting expectations; publishing real work early, and keeping in touch with past collaborators, widens your luck surface area. (Ilya Grigorik, Thariq Shihipar, Adrien Friggeri)

## 5. Motivation, regrets & the long game

- **Know why before you climb.** Settle your values and what you want the next decades to look like; reaching a target level or money number with nothing beyond it leaves a void — the dog that caught the car. (Philip Su, Bryan Cantrill, 2025 compilation)
- **Climb your own ladder.** Chasing a path because it was put in front of you, or to match peers, leads to burnout; the career has to satisfy you. (2025 compilation)
- **Speedrunning has a cost.** Hitting a top level young can leave decades with nowhere higher to go; pace growth deliberately. (Philip Su)
- **Invest in life outside work.** Relationships and health pay off more over a lifetime than squeezing every hour into the career; tell a short crunch apart from chronic overload. (Evan King, Philip Su, 2025 compilation)
- **Follow genuine interest.** Sustained high output, and the intense stretches fast growth needs, come from real enthusiasm for the problems, which can't be faked for decades. (Adam Ernst, Bryan Cantrill, Ryan Olson)
- **Treat mistakes as load-bearing and move on.** Setbacks and bad calls teach what later success depends on; dwelling on them is wasted energy. (Bryan Cantrill, Nimit Sohoni)
- **Don't underestimate yourself.** A common regret is assuming you weren't capable; ambitious bets are mostly about willingness, not innate talent, so act without waiting for permission or certainty. (John White, 2025 compilation)

## 6. Learning & personal effectiveness

- **Build fundamentals early.** Deep technical and mathematical foundations, and an understanding of the layers below your code, open doors without posturing and remove fear of hard debugging. (Nimit Sohoni, Casey Muratori)
- **Ask early and speak up.** Don't stay stuck or silent to look competent; time-box struggling, go straight to the expert, and write the answer down. Complex systems are just logic and yield to steady curiosity. (Casey Muratori, Evan King, James Everingham, 2025 compilation)
- **Learn a new domain by doing.** Ask direct questions, read the code, ship small changes and then own one problem end to end. (Adrien Friggeri)
- **Treat feedback as data, not a grade.** Code review and manager feedback are inputs to sharpen judgement, not pass/fail verdicts. (Michael Novati)
- **Read primary sources.** Original papers and proceedings build deeper intuition than summaries and blogs. (Casey Muratori)
- **Guard focus time.** Block mornings, keep meeting-free days, drop low-value meetings and say no or delegate the rest; it's how big-scope people still keep sane hours. (Jake Bolam, Michael Novati, Simon Kindström)
- **Don't fill slack with a second project.** Focus follows a power law: split across two projects, each gets far less than half. Use waiting time to plan ahead on the main one. (Steve Huynh)
- **Work hard, but rest before judgement degrades.** Of luck, talent and effort, effort is the one you control, and extra hours compound early; past a point fatigue produces bugs and bad calls. (Michael Novati, Philip Su)
- **Don't let the AI lift all the weights.** Leaning on agents for every hard problem stops your own thinking growing; skip the AI hype news and keep solving hard things yourself. (James Cowling)
- **Learn business and customer context earlier.** As code generation gets cheap, value moves to knowing the customer, the domain and the architecture. (Marc Brooker, Ethan Evans)

## 7. Interviewing, PIPs & layoffs

- **Answer behavioural questions with real stories and numbers.** Interviewers want past behaviour, not hypotheticals; use Situation, Task, Action, Result with concrete metrics. (Steve Huynh)
- **Say "I", not "we".** Interviewers need to know what you personally owned, decided and did. (Steve Huynh)
- **If you're put on a PIP, start looking.** Most are written to exit someone and the decision is already made; only stay focused on passing it if the bar is concrete and genuinely reachable. (Ethan Evans, Stefan Mai)
- **Separate your worth from your title.** Layoffs and rating swings usually reflect business shifts, not your competence; keep a network, keep learning and stay interview-ready. (Steve Huynh)
- **Know which market you're in.** In an oversupplied job market employees have less leverage and companies tolerate less friction; keep outside options warm. (John White)

## 8. Negotiation & compensation

- **Pay tracks positioning, not performance.** Performance gets you through the interview loop; pay is set by the company's pay philosophy, timing and how well you advocate for yourself. The worst performer on a team can out-earn the best by $120K. (Colin Lernell)
- **Pick the pay tier, not just the job.** Companies pay around the 25th–50th percentile, big tech around the 80th, and hot pockets (AI teams and labs) 2–4x the normal band for the same level. Moving tier beats grinding for a 5–10% internal raise. (Colin Lernell)
- **Turn the offer into due-diligence calls.** After the first numbers, ask to talk to the hiring manager and skip-level about scope, priorities and success measures. It makes you a future colleague rather than a candidate number, and builds a champion who can unlock comp or a level the recruiter can't. (Colin Lernell)
- **"Final offer" means the recruiter's ceiling.** Going past it needs the hiring manager to take a business case to the comp committee or leadership, so give them one. (Colin Lernell)
- **You don't need a competing offer.** Create options by talking to recruiters and contacts at similar companies, say you're in other conversations, and name the exact number at which you'd stop interviewing and sign. (Colin Lernell)
- **Never react on the call.** Act as your own assistant: thank them, collect every number and term, and take two or three days. Counter with one specific number, never a range; they anchor to the bottom of a range. (Colin Lernell)
- **When cash is capped, move other levers.** Ask for sign-on or year-two bonuses to cover forfeited equity or bonus, or an up-level by showing your scope matches the next level. (Colin Lernell)
- **Negotiate the exit terms on the way in.** At startups, push for a long option exercise window (3–10 years rather than 90 days) and accelerated vesting if an acquisition ends or changes your role; you only have that leverage before you sign. (Colin Lernell)
- **A retention offer tests your manager.** Tell your manager about an outside offer: a manager who fights for a raise or up-level makes staying viable; vague promises mean go. (Colin Lernell)
- **Negotiate early, even for small amounts.** A $10–20K gain early compounds, and the practice builds the confidence for six-figure negotiations later. (Colin Lernell)

## Tradeoffs

- **Clear promo criteria vs. checklist-chasing.**
  - Pin it down: raise promotion early, ask "under what circumstances would I be the top candidate?" and agree the exact gaps. (Ethan Evans, Evan King, Simon Kindström, Jake Bolam)
  - Let it follow: work on the organisation's biggest problems; pinning managers to checklists or gaming committees backfires. (Bobby Holley, Philip Su, Joakim Recht, Bryan Cantrill)
  - When each wins: get explicit criteria when expectations are unclear (new team, new manager, a cycle approaching); once you know them, stop optimising to the list and go after the biggest problem.
- **Climb fast vs. pace yourself.**
  - Fast: take the scary projects, finish core work quickly and push for promotions early, because growth compounds. (Ethan Evans, Jake Bolam, Evan King, Philip Su)
  - Pace: speedrunning can leave decades with nowhere higher to go and no purpose beyond the next level. (Philip Su, Bryan Cantrill, 2025 compilation)
  - When each wins: push hard while each level brings real new learning; slow down when the next step is mostly title and you don't yet know what comes after it.
- **Stay to see consequences vs. move for growth.**
  - Stay: at senior levels, moving every 18–24 months is a red flag and hides whether your designs worked. (Stefan Mai, James Cowling)
  - Move: leave when the learning curve flattens or the org stops growing. (Marc Brooker, Ilya Grigorik, Ethan Evans)
  - When each wins: stay long enough to see the results of your big decisions; after that, a flat learning curve or a static org is the signal to go.
- **Deep expertise vs. getting trapped by it.**
  - Go deep: being the go-to person on a core system is leverage. (Evan King)
  - Get out: stay too long and you become its permanent maintainer. (Stefan Mai)
  - When each wins: build the expertise while it is earning you scope; hand it off once it only earns you maintenance.
- **Talent stack vs. deep specialism.**
  - Stack: be the only, not the best — combine several strong skills. (Ilya Grigorik, Adrien Friggeri, 2025 compilation)
  - Specialise: large orgs need deep experts, and rare niche depth buys autonomy from politics. (Philip Su, Evan King, Ethan Evans)
  - When each wins: depth wins in large companies and hard technical domains; the stack wins in small teams and senior roles that bridge functions.
- **Outwork everyone vs. protect rest and life.**
  - Push: effort is the lever you control, and extra hours compound early. (Michael Novati, Philip Su, Ryan Olson)
  - Protect: fatigue produces bugs and bad judgement, and relationships and health pay off more over a lifetime. (Philip Su, Evan King, 2025 compilation)
  - When each wins: short, chosen crunches on work you care about pay off; chronic overload doesn't.
- **Lean on AI vs. keep your own muscles.**
  - Lean in: early mastery of new tools skips the experience queue, and seniors who don't experiment fall behind (see `engineering-principles`). (Ryan Olson, Marc Brooker)
  - Hold back: letting agents solve every hard problem, or draft your reasoning, stops your own thinking growing. (James Cowling, Bobby Holley)
  - When each wins: use AI heavily for throughput and to learn the tools; do the reasoning yourself on problems that build judgement.
- **Say yes to unglamorous help vs. say no to protect focus.**
  - Yes: ad hoc help, mentoring and small fixes build the trust and informal authority that make big work possible. (Jake Bolam)
  - No: turn down optional work and don't fill slack with side projects; one big, measurable project is what gets promoted. (Steve Huynh)
  - When each wins: say yes early on a new team, while you're still earning trust; once you have a big project, protect it and decline the rest.
- **Optimise for people and problems vs. chase the pay tier.**
  - People and problems: early on, pick the best people and hardest problems over small salary or equity differences; the network compounds. (James Cowling, Michael Novati, James Everingham)
  - Pay tier: pay is set by where you sit, not how well you work, so moving to a higher-paying company or team beats grinding for internal raises. (Colin Lernell)
  - When each wins: when the gap is small or you're early in your career, take the better people and problems; when another tier pays multiples for the same level, the money is the bigger lever. Either way, negotiate the offer you take.

---

## Sources

- Ethan Evans (former VP, Amazon) — "Amazon VP: Stack Ranking & PIPs, Working With Bezos, His Promotions"; "Amazon VP: How Corporate Politics Work And How To Win"; "Amazon VP: Questions On Corporate Politics But They Get Increasingly Darker"
- Philip Su (ex-Distinguished Engineer IC9, Meta and OpenAI) — "OpenAI & Meta Distinguished Engineer (IC9): Working With Zuck, Carmack & Career Growth"; "OpenAI & Meta Distinguished Eng (IC9): The Psychology Behind Tech Career Peaks"
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
- Colin Lernell (tech salary negotiation coach, Top Tech Newsletter) — A Life Engineered — "Negotiation Expert: How To 3X Your Tech Salary"
- 2025 compilation (clips from Philip Su, Steve Huynh, Ricky Lee, Evan King, Ilya Grigorik, Ethan Evans, Dwayne Reeves, Brian Attwell, Jake Bolam, Joakim Recht, Boris Cherny; the summary doesn't say who said which point) — "Best Software Engineering Career Advice of 2025"
