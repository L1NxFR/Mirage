# Research Project Homepage

A Hugo repository for research documentation, with hierarchical journal indexes, paper cards,
progress timelines, and article reading tools.

## Pages

| Page | URL | Content location |
| --- | --- | --- |
| Overview | `/` | `site/content/_index.md` |
| Related | `/related-work/` | `site/content/related-work/` |
| Journey | `/research-journey/` | `site/content/research-journey/` |
| System | `/system-implementation/` | `site/content/system-implementation/` |
| Meetings | `/meetings/` | `site/content/meetings/` |

The four journal indexes show expandable folder hierarchies. Each entry has a
dotted leader and a right-aligned last updated date. Articles retain section
navigation, tables of contents, and Markdown editing and downloads. Search covers
all published records and the Overview. About, tags, categories, and CV pages are
no longer generated.

The Overview and journal articles share the same document cover, body typography,
numbered headings, contents navigation, and editing/download controls.

The four journals start empty. Writing templates live in `site/content/Templates/`.
The Overview and journal group pages are drafts. Edit the Overview to add project
details, and configure the site name and repository URL in `site/hugo.yaml`.

## Local development

Install Hugo and Node.js 22 or newer, then run:

```sh
npm ci --ignore-scripts
npm run dev
npm run build
```

Build output goes to `site/public/` and is excluded from Git. Builds clean stale
output so removed pages do not remain available.

## Editing in the browser

`pnpm dev` (or `npm run dev`) starts a local workspace. On every machine, the
starting port defaults to `23130`; occupied ports are skipped in ascending order
until the server binds successfully. Open the actual URL printed at startup.
Use `pnpm dev --port 24130` (or `npm run dev -- --port 24130`) to choose another
starting port. Hugo's local `baseURL`, allowed hosts, origin validation, and
workspace saves all use the selected port, including after rebuilds. This is a
runtime rule; `site/hugo.yaml` retains the portable publishing URL configuration.
The server listens only on loopback and saves directly into this repository.

`npm run test:workspace` also runs the startup regression checks. These require
Hugo and permission to bind local loopback ports, and use isolated temporary
sites to test occupied ports and saving after port selection.

- Search in the left sidebar filters the current journal's documents by title
  and content. Use **⌘J / Ctrl+J** to focus it.
- The **+** menu offers only **Document** and **Group**. Choose a title and parent
  group; newly created documents open as drafts in the editor. Empty groups remain visible.
  Local workspace navigation includes drafts with a Draft label; production builds
  exclude them. Set `draft: false` in Properties when a document is ready.
- **Edit Markdown** opens a CodeMirror editor with syntax highlighting, line
  numbers, undo/redo, formatting shortcuts, and Write / Split / Preview modes.
  **TL;DR** is an optional Markdown summary above the body editor. It syncs with
  the `tldr` property and appears below the title in the live preview. Existing
  documents need no setup; leave the field empty to hide the summary. Invalid
  YAML disables the summary field until corrected in **Properties**.
  **Properties** contains the page's YAML metadata.
  Formula previews support `$...$`, `\(...\)`, `$$...$$`, `\[...\]`, and fenced
  `math` blocks using local KaTeX assets. Ordinary code stays literal. Incomplete
  formulas show an error in the preview so you can correct them before saving.
- **Save** or **⌘S / Ctrl+S** writes Markdown to the repository, updates `lastmod`,
  and rebuilds the site. Close the editor to see the rebuilt page. Unsaved changes
  prompt before closing or navigating away.
- If a file changed in Obsidian or another editor, saving stops with a conflict
  message. Your unsaved text remains available to copy. Discard it and reopen
  the editor to load the newest file.
- Invalid metadata or a failed Hugo build leaves the prior saved document intact.
  Preview supports standard Markdown; Hugo-specific shortcodes are rendered by
  the site build after saving.

External changes to content, layouts, styles, or configuration rebuild the local
site; reload the browser to view them. Static GitHub Pages deployments remain
read-only. Local write APIs and their session token are not included in builds.

## Adding entries

Create a Markdown file in the relevant journal directory. Subdirectories appear
in the section's article tree. Configure folder labels in
`site/data/journal_navigation.yaml`.

```yaml
---
title: First experiment
date: 2026-11-14
draft: true
show_toc: true
---
```

Local previews use the Markdown file's modification time, including edits in
Obsidian or another editor when `lastmod` is absent or unchanged. Cover, document
information, and index timestamps include seconds. Production builds prefer an
explicit `lastmod`, for example `lastmod: 2026-11-14T16:45:00+01:00`, and otherwise
fall back to the file modification time. This preserves recorded publication
timestamps across copies and checkouts. Creation dates remain the explicit
`date` field; a missing creation date displays a dash. Folders
appear first; entries within each folder sort by weight, then title. Use
`weight: -1` to place an entry before its siblings. Documents default to
`draft: true`, including when the field is omitted on the Overview, a group, or
an article. New documents and groups created in the web editor, Hugo, and Obsidian
use this default. Saving a document with no draft property adds `draft: true`.
Set `draft: false` explicitly to
publish an entry. Local editing previews include drafts at their direct URLs;
production builds and their navigation and search exclude them. Obsidian's `Templates/` directory contains
Research Journey, System & Implementation, and Meetings templates, which are
excluded from publication.

## Automatic note templates in Obsidian

Open `site/content/` as the vault. After reviewing and trusting the included
plugins, enable community plugins for this vault and enable **Templater** in
Settings. [Restricted mode disables community plugins](https://obsidian.md/help/plugin-security),
so copying `.obsidian/` settings alone does not activate automatic templates.
This trust choice must be made for each new vault on each machine.

Templater is configured to apply folder templates to new empty Markdown notes:
`related-work/` uses `Templates/Related Work.md`; Journey, System and Meetings
use their corresponding templates. Subfolders inherit their nearest configured
parent; `/` uses `Templates/New Note.md` as the fallback. Keep **Trigger Templater
on new file creation** and **Enable folder templates** enabled. The related-work
template supplies YAML defaults, takes the initial title from the filename,
and uses the note's creation day instead of a fixed example date.

Automatic insertion applies when a note is created empty. Existing notes and
files created with body text are not rewritten. Reload the vault after editing
plugin settings outside Obsidian. `node --test scripts/test-obsidian-templates.mjs`
checks the folder bindings and metadata defaults; it does not verify the vault's
runtime Restricted mode setting.

## Project title, author, and document dates

Set `title` and `params.author.default` in `site/hugo.yaml` to configure the header,
for example `Research Project by Nan Lin`. The same author setting supplies the
byline for documents whose `author` field is empty or absent. A document's own
`author` overrides it; imported paper author lists retain their existing display.

The document metadata row uses separate author, calendar, and clock icons.
`date` records creation and `lastmod` records the last edit; the web editor updates
only `lastmod` when saving. The workspace's file-time policy lives in
`site/config/workspace/hugo.yaml`; rebuilding does not rewrite document metadata.
Refresh the page after an external edit to see the updated time. The header's search icon
opens the same search dialog as ⌘K / Ctrl+K.

## Deployment

The optional workflow at `dashboard/.github/workflows/deploy.yml`, relative to the
project root, is inactive in its nested location. Before enabling GitHub Pages,
move it to the root `.github/workflows/` and adapt its paths for `dashboard/`.
Local edits do not push or publish.

This project uses the [Hugo Paged](https://github.com/yihui/hugo-paged) theme.

## Progress timelines in Obsidian

The vault includes the local **Timeline** plugin. In Obsidian, run
the Timeline plugin's insert command from the command palette or the editor context menu. Fill in steps, statuses and optional Markdown details;
the preview updates while typing. Save to insert the timeline. Hover a rendered
timeline and click its pencil to edit it again.

The backing Markdown is a task list, shared by Obsidian Live Preview, Reading
view and the Hugo site:

````text
```timeline
# Progress
- [x] Complete the literature review
- [x] Define the research direction
- [/] Analyze research gaps
  Write Markdown details here.
- [ ] Write the final report
```
````

`[x]` = done, `[/]` = running, `[ ]` = pending, `[!]` = error. Details are
indented by two spaces. Append `{open}` to a step title to start its details
expanded. A `collapse: 2` line before the steps folds the first two steps.
The title is optional. Existing YAML shortcodes remain supported.

For development, run `node --test scripts/test-timeline.cjs` and
`python3 scripts/verify-timeline.py`. After changing `plugin.js`, `source.js`, `editor.css` or the shared timeline CSS,
run `node scripts/sync-timeline-plugin.mjs` to refresh the bundled plugin, styles,
font and license files. Bundled files are ready to use; no npm installation is needed.

## Document covers and TL;DR

Every journal article uses the gray paper-style cover by default. Its title, subtitle, author, date and tags come from front matter.
Add `tldr` to show a Markdown summary inside the cover; omit it or leave it
empty to hide the TL;DR block. No correspondence, project link or institution
logo is inserted.

```yaml
---
title: Collective Communication
subtitle: Concepts and Implementations
date: 2026-10-27
tldr: |
  **Key takeaway:** Communication semantics, algorithms, and scheduling address different aspects of the problem.

  - Semantics define the expected result.
  - Algorithms and scheduling determine how communication is performed.
---
```

The page title is rendered automatically. In the body, use `##` for main
sections and `###` for subsections. Markdown `#`, `##` and `###` retain their
HTML heading levels and use distinct 28px, 22px and 18px sizes. The contents
navigation includes all six Markdown heading levels and preserves their anchors.

## Pasted images and attachments in Obsidian

Open `site/content` as the Obsidian vault. **Files and links → Default location
for new attachments** is set to **In the folder specified below**, with
`Attachments` as the folder. Pasted or dragged files are stored in
`site/content/Attachments/`. Keep **New link format → Path from current file**,
Markdown links enabled, and automatic link updates enabled.

For a note in `related-work/communication/`, Obsidian inserts links such as:

```md
![](../../Attachments/screenshot.png)
[PDF](../../Attachments/paper.pdf)
```

Hugo publishes the same files at `/attachments/` and translates these relative
links during the build, including filenames with spaces or Chinese characters.
PDF embeds become download links. After changing Obsidian settings outside the
app, reload the vault. Move existing attachments inside Obsidian so its link
updates keep references in sync.

All non-Markdown files in `Attachments` are copied into the website, including
files referenced only by drafts. Run `python3 scripts/verify-attachments.py` to
check the publishing paths and attachment links.

## Excalidraw drawings

Open `site/content` as an Obsidian vault. Excalidraw stores drawings in its
`Excalidraw` folder and automatically exports an SVG beside each drawing. Use
the Excalidraw command **Create a new drawing and embed into active document**
to insert a relative Markdown link to the SVG. Open the corresponding
`.excalidraw.md` file to edit it; saving updates the SVG. The plugin also keeps
export names in sync when a drawing is renamed or deleted.

Hugo publishes SVGs from this folder at `/excalidraw/` and excludes drawing
source files from pages. All SVGs in that folder are included in a site build,
including drawings used only by drafts, so do not put private images there.
For a new checkout, keep the vault's Excalidraw settings and its relative-link
setting; reload Obsidian after editing those settings outside the app.

## Content language and typography

The interface defaults to English (`locale: en-US`, `defaultContentLanguage: en`).
Documents and groups default to `content_lang: en`, including web editor creations,
Hugo archetypes, and Obsidian templates. Saving a document without a language adds
this default; explicit language settings are preserved.
Chinese research notes are supported through UTF-8 Markdown and
`hasCJKLanguage: true`. Set `content_lang: zh-CN` in a note's front matter to use
Chinese typography.

`site/static/css/fonts.css` preserves the theme's serif typography and Chinese
font fallbacks. The page language is set by `site/layouts/_partials/html_open.html`.

English document prose uses serif text; `strong` and `b` emphasis in the body and
summary use sans-serif text, including nested bold italics. Inline code retains
its monospace family. This also applies to `en-US` documents.

Run `python3 scripts/verify-document-updates.py` to check external-edit timestamps,
second precision, creation-date separation, and stable explicit publication dates.
