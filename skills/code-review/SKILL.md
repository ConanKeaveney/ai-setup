---
name: code-review
description: Review a pull request for concrete defects and applicable repository instructions. Use for code-review requests, including a repository instruction to invoke the code-review plugin workflow.
---

# Pull request review

Read the pull request description and comment thread before inspecting code. Use the connected GitHub tools or authenticated gh CLI. Reviewing does not itself authorize posting a comment.

- Confirm the pull request is open and identify its head commits and intended scope. Explain when it is a draft, already reviewed, or unsuitable for another review; do not silently abandon an explicitly requested review.
- Read applicable AGENTS.md guidance and any CLAUDE.md instructions the repository adopts. Establish the correct base so unrelated merged work is excluded.
- Use one reviewer for the pull request, following repository rules about independence. Review changed code and the callers needed to assess behavior; inspect relevant history when it resolves an uncertainty.
- Prioritize observable correctness, missing requirements, and violations of explicit instructions. Exclude pre-existing issues, speculative warnings, and style preferences already covered by formatters or linters.
- For every finding, state the trigger, resulting behavior, and concrete source location. Validate the causal path and discard findings that do not survive inspection.
- Follow the repository's test tier. When a reviewer must rerun author negative controls, predict which checks should fail and run only those controls; do not rerun the author's suite.
- Report findings in severity order with file and line references. If no findings remain, state that and identify material validation limits. Post a review only when authorized, using the repository's required submission entry point and format.

Use the tools and agent types the current runtime exposes; no review swarm. Existing authorization and repository review rules take precedence over an imported workflow.
