# Research project structure (2026-11-14)

The current navigation is Overview, Related, Research, Docs, and Meetings, with Search as a shared tool. The repository contains only the project structure and authoring tools.

- Overview uses a prose layout. Missing project details are marked as placeholders.
- The four journal indexes use expandable folder hierarchies, dotted leaders,
  and right-aligned last updated dates. Folders precede entries; entries sort
  by weight and title within their folder. All folders start expanded.
- The four journals share article trees,
  document tools, paper covers, and reading layouts. Each tree contains only its
  section's published entries.
- `params.journal_sections` selects journal behavior. The `blog` CSS class remains
  an internal layout hook.
- About, tags, categories, and CV pages are removed. The four journals start empty; drafts remain excluded from production, navigation, and search.
- The interface, project pages, and new authoring templates use English. Chinese research notes are supported.
- On narrow screens, the article tree collapses and the navigation wraps. Empty
  journals display “No published entries yet.”
- Changes remain local until deployment is requested.
- Overview uses the same document template, cover, typography, heading numbering,
  contents rail, and document controls as journal articles. Its left article tree
  is omitted because it does not belong to a journal.
- The shared navigation's project name uses 20px type; menu links retain their
  existing size.
- Every current document and template has `draft: true`. The global cascade
  defaults all future page kinds to drafts, including home and group documents.
  Workspace previews include drafts; explicit `draft: false` remains the publish action.
- `title` and `params.author.default` supply the header's project name and byline.
  Document authors use the same default, with a per-document `author` override.
  Creation (`date`) and modification (`lastmod`) are separate icon-labelled fields;
  unrecorded dates show a dash. Search uses an accessible icon link.

Navigation density: sidebar rows use 15px type at 1.3 line-height with 3px vertical padding;
index rows use 16px type at 1.35 line-height with 4px vertical padding. Archive
grids align content to the top so title-to-index spacing does not stretch.

The sidebar, directory index, search interface, and editor controls share
`--site-font`, matching the existing site navigation and page titles. Only source
editing and code use monospace. Article-specific reading typography is preserved.
The local workspace supplies section search, Document/Group creation, and a
CodeMirror editor with preview and direct repository saves. Mutations stay inside
approved content directories, reject stale revisions and symbolic links, and
restore the previous file when a build fails.
