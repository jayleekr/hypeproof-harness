# HypeProof Agent Entry Point

This repository uses shared HypeProof agent guidance.

Read `docs/AGENT-GUIDE.ko.md` first, then follow any repo-specific instructions
in this repository.

Claude Code-specific assets live under `.claude/skills/`. Shared skills are
vendored from `hypeproof-harness`; do not edit vendored files directly in
consumer repos.

<!-- hype-pr-skill:start -->
## Agent PR preparation

For development through PR creation in this repository, read and use
`.claude/skills/hype-pr/SKILL.md` (also discoverable at `.agents/skills/hype-pr/`).
Inspect criteria links at task start; before creating a PR, record the agent's
impact assessment and validation with `scripts/hype-pr/pr.py inspect` / `prepare`.
Create through `scripts/hype-pr/pr.py create --preparation <receipt> --apply`.
Fix stale/missing preparation instead of bypassing it with direct `gh pr create`.
The common contract is `docs/AGENT-GUIDE.ko.md`; commands are in `docs/HYPE-PR.ko.md`.
This adds no GitHub required check and does not grant human approval or merge authority.
<!-- hype-pr-skill:end -->
