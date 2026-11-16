---
name: feature-dev
description: Develop a substantial feature with focused codebase exploration, an explicit design, implementation, and review. Use when the user requests the feature-dev workflow or a feature needs coordinated investigation and implementation.
---

# Feature development

Read the applicable AGENTS.md and project workflow skills first. Use the user's existing plan and authorization when supplied.

- Establish the requested behavior and acceptance criteria. Inspect the relevant implementation and callers before asking about facts the code can answer.
- Use the available explorer or specialist agents for independent investigations when delegation is authorized. Give each a specific question and request relevant source locations. Read the code needed to resolve the design.
- Ask only about material choices that remain unresolved. A supplied plan or instruction to implement is authorization to execute its scope.
- Choose the smallest approach consistent with the repository. Explain a significant tradeoff briefly and use the repository's decision rules.
- Give each implementing agent explicit file ownership, testing expectations, and a time cap. Tell agents they share the codebase and must preserve others' edits. Follow the repository's issue, lane, build, and review requirements.
- Reproduce a defect before fixing it. Exercise only the changed behavior and required controls, then run the applicable formatter and linter. Do not broaden tests without a concrete reason.
- Use one independent reviewer per pull request where required; fix actionable findings within the authorized scope. Posting reviews or messages externally requires authorization from the user or the applicable workflow.
- Report the resulting behavior, validation outcome, and any remaining limitation using the user's communication preferences.

Use the tools and agent types the current runtime exposes.
