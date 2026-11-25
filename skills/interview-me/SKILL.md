---
name: interview-me
description: Turn a rough task into a complete prompt by interviewing the user one question at a time, then hand back the prompt without running it. Use when the user types /interview-me, says "interview me", "help me write the prompt", or "ask me what you need first".
---

# Interview me

The user forgets details. Your job is to pull them out before any work starts.

1. Read the task they gave. Check the repo, memory and their instruction files for anything you can answer yourself; do not ask those.
2. Ask **one question at a time**, most important gap first. Offer a likely answer they can accept with "yes". Stop asking once the four parts below are filled, usually after three to six questions.
3. Hand back one ready-to-run prompt in this shape, in a code block:

```
THE JOB
<The goal, not the steps, in one or two sentences. Figure out the best way there yourself.>

THE WHY
<Why they want it and who it is for: what the result lets them do.>

THE GUARDRAILS
- <Something not to touch or send>, because <reason>.
- <Another limit that matters>, because <reason>.

DONE MEANS
- <Check 1>
- <Check 2>
- <Check 3>
Don't stop until every check passes.
```

4. Stop. Do not start the work. Run the prompt only when they say "run it" (or similar), or they can paste it elsewhere.

Write guardrails as plain sentences with a reason each, not capitals or "MUST". Each "done means" check must be something you can verify, not a feeling.
