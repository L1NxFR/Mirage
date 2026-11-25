# Working in src

The repository's root AGENTS.md applies here. For implementation work in this
directory, use the project-local pstack workflow.

## Getting started

- Read `.claude/skills/poteto-mode/SKILL.md` and select a playbook for the task.
  In Codex, also read `.agents/skills/poteto-mode/references/codex-tools.md`.
  Both paths are relative to the repository root.
- A mechanical change to one file can proceed directly. Use poteto-mode for
  changes spanning multiple files, interface or architecture decisions,
  performance issues, and bugs with an unknown cause. Follow any workflow
  the user explicitly requests.
- Start the session from the repository root. If a skill is missing from the
  menu, read its local SKILL.md directly. Use the version in this repository.
- Skills live in `.claude/skills/`. Codex discovers the same files through the
  relative symlink `.agents/skills`. Preserve the link, the sibling skill
  directories, and their references, playbooks, and scripts.
- Upstream revisions and file checksums are in `.agents/pstack/upstream.json`.
  Keep the upstream skill files intact.

## Running a playbook in Codex

- Use the tools and models available in the session. Consult the Codex mapping
  for Claude tool and model names, and respect the host's concurrency limit.
- This installation has no SessionStart hook. This file selects the default
  workflow independently of the hook setting in setup-pstack.
- In Codex, setup-pstack writes user-level configuration by default. The local
  workflow already works without setup. Establish the intended scope before
  changing any user-level model settings.
- Use subagents when the selected skill requires them. If an independent
  reviewer is required and unavailable, report the review as blocked.
- Commits, pushes, pull requests, merges, deployments, and external messages
  must stay within the user's authorization.
- Document commands and performance results only for runnable components.
  Create a project verification skill at `.claude/skills/verify/` only when
  there is an implementation to verify, and run it against that implementation.
- Follow the root instructions for experiment records and Dashboard document
  ownership. Credit the actual contributors to each document.

See the [project workflow guide](../dashboard/site/content/other/project-guide/agent-pstack-guide.md).
