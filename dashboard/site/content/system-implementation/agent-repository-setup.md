---
title: "[Agent] Repository Setup"
content_lang: en
date: 2026-11-15
lastmod: 2026-11-15
draft: true
---

## Decision

Status: accepted by the user on 2026-11-15.

Track the complete project in a private GitHub repository, starting with a fresh
Git history at the project root. The user requested a clean initial snapshot.
Retaining the existing Git history was considered and rejected by the user.

The repository is [Research-Project-Template](https://github.com/Languisher/Research-Project-Template).
Only the new `main` branch is intended for upload. Dependencies, build output,
local workspace state, and environment secrets are excluded by the root and
dashboard `.gitignore` files. `src/.gitkeep` preserves the empty implementation
directory in fresh clones.

## Consequences

The new repository has no earlier commits, branches, remotes, or reflogs.
Git commands run from either the project root or `dashboard/` use the same root
repository. The optional deployment workflow remains nested and inactive;
creating the private repository does not enable website deployment.

Project-specific links and Timeline plugin identifiers use the current project.
Third-party license notices and attribution remain intact.

## Validation

- `npm run build` in `dashboard/`: passed. All current documents remain drafts,
  so the production build generates no published pages.
- `npm run test:workspace`: 15 tests passed.
- `node --test scripts/test-timeline.cjs`: 7 tests passed after the plugin rename.
- `python3 scripts/verify-navigation-search.py`: passed publication, navigation,
  search, draft defaults, and project-subpath checks.
- Root and dashboard README relative links resolve; examples inside code fences
  are excluded from link validation.
- Upload candidates contain no obsolete project identifiers or repository URLs.
  A targeted scan for common credential formats found no matches; this is not
  a comprehensive security audit.
- `dashboard/.git` is absent, and both directories resolve to the root repository.
  Ignore rules exclude dependencies, generated site/editor output, local workspace
  state, and environment files.
- The GitHub repository was created with `--private`; `gh repo view` confirmed
  `isPrivate: true` and `visibility: PRIVATE` before upload.
- Task-modified files pass the Git whitespace check. The snapshot-wide check
  reports existing whitespace in bundled assets, templates, and a layout;
  those unrelated files were not reformatted.

After upload, compare remote `refs/heads/main` with local `HEAD` and confirm that
the new history contains only its initial root commit.
