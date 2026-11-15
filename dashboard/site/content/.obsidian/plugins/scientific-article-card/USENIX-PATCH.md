# Local USENIX support

The installed Scientific Article Card 1.11.2 has a local patch:

- `usenix.org` is included in the default and saved Publisher domains.
- Conference citation titles have their BibTeX braces removed.
- The abstract falls back to USENIX's paper-description field.
- Conference metadata produces the Conference Paper badge.

Paste a USENIX presentation URL into an empty line to create a card. For a link
already in a note, select it and run **Scientific Article Card: Convert selection
(or identifier under cursor) to article card** from the command palette.

Updating the community plugin can overwrite `main.js`. To restore this fix, run
`node scripts/patch-scientific-article-card.mjs` from the repository root, then
turn Scientific Article Card off and on in Obsidian's Community plugins settings.
The script can be run repeatedly. If a newer plugin has changed the relevant
code, it stops for review before writing any files.

Verified with the live NSDI 2026 HeteCCL page and Obsidian 1.14.5 on 2026-11-01.
The generated `paper` block is also supported by this site's Hugo renderer.
