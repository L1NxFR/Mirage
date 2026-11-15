"""Small synthetic documents for Hugo regression checks, never published as content."""


def write_layout_fixtures(content):
    folder = content / 'related-work/group'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / '_index.md').write_text('---\ntitle: Communication\ndraft: false\n---\n')
    (folder / '中文笔记.md').write_text('''---
title: 中文笔记
draft: false
show_toc: true
---
## First
A reference.[^one]
## Second
Another reference.[^two]
## Parent {#parent}
#### Child {#child}
## Last
### One
### Two
[^one]: First note.
[^two]: Second note.
''')
    (folder / 'card-example.md').write_text('''---
title: Card example
draft: false
---
```paper
title: Example Paper
url: https://example.org/paper
abstract: An example abstract.
```
''')
    (folder / 'private-note.md').write_text('---\ntitle: Private note\ndraft: true\n---\n')
    (content / 'related-work/paper-example.md').write_text('''---
title: Paper example
paper_source: https://example.org/paper
draft: false
show_toc: false
disable_sidenotes: true
tldr: Example summary.
---
## Introduction
## Background
## Method
### Protocol {#31-game-protocol}
### Setup
### Algorithm
## Results
## Discussion
### One
### Two
### Three
### Four
### Five
## Conclusion
''')
