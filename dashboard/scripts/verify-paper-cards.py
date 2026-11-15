#!/usr/bin/env python3
"""Build isolated Hugo fixtures; no network or third-party Python packages needed."""

from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
import tempfile


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.text = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def handle_data(self, text):
        self.text.append(text)

    def select(self, tag, **attrs):
        return [a for t, a in self.elements if t == tag and all(a.get(k) == v for k, v in attrs.items())]


repo = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="paper-cards-") as tmp:
    source = Path(tmp) / "site"
    content = source / "content"
    content.mkdir(parents=True)
    shutil.copy(repo / "site/hugo.yaml", source / "hugo.yaml")
    (source / "layouts").symlink_to(repo / "site/layouts", target_is_directory=True)
    (source / "static").symlink_to(repo / "site/static", target_is_directory=True)
    (content / "card.md").write_text('---\ntitle: Example card\ndraft: false\n---\n```paper\ntitle: Example Paper\nurl: https://example.org/paper\nabstract: An example abstract.\n```\n')
    (content / "features.md").write_text('''---
title: Card features
draft: false
---
```paper
title: 'A <script>alert(1)</script> & B'
url: https://example.org/paper
authors: [Alice, Bob]
journal: Nature
year: 2025
volume: 12
issue: 3
pages: 1-9
doi: 10.1000/example
pmid: '1234'
pmcid: PMC1234
status: reading
rating: 4
tags: [systems, gpu]
keywords: 'MoE; Scheduling'
note: 'Check <img src=x onerror=alert(1)>'
abstract: |
  First paragraph.

  Second paragraph.
```
```paper
url: https://example.org/untitled
tags: 'one, #two three'
rating: 99
```
```python
print("ordinary code")
```
''')
    (content / "invalid.md").write_text('''---
title: Invalid cards
draft: false
---
```paper
title: [broken
```
```paper
- not
- a map
```
```paper
abstract: No title or URL
```
''')
    output = Path(tmp) / "public"
    subprocess.run([
        "hugo", "--source", str(source), "--themesDir", str(repo.parent),
        "--theme", repo.name, "--destination", str(output),
    ], check=True, capture_output=True, text=True)
    fast = Page((output / "card/index.html").read_text())
    assert fast.select("article", **{"class": "paper-card"}), "Card still renders as code"
    assert not fast.select("code", **{"class": "language-paper"})
    assert fast.select("a", href="https://example.org/paper")
    assert fast.select("details", **{"class": "paper-card__abstract"}) == [{"class": "paper-card__abstract"}]
    assert fast.select("link", rel="stylesheet", href="/css/paper-card.css")

    features = Page((output / "features/index.html").read_text())
    text = " ".join(features.text)
    assert len(features.select("article", **{"class": "paper-card"})) == 2
    for value in ("Alice, Bob", "Nature", "2025", "12(3):1-9", "Reading", "#systems", "#two", "#three", "MoE", "Scheduling", "Second paragraph."):
        assert value in text, value
    assert features.select("span", **{"aria-label": "Rating: 4 / 5"})
    assert features.select("span", **{"aria-label": "Rating: 5 / 5"})
    for href in ("https://doi.org/10.1000/example", "https://pubmed.ncbi.nlm.nih.gov/1234/", "https://pmc.ncbi.nlm.nih.gov/articles/PMC1234/"):
        assert features.select("a", href=href), href
    assert "<script>alert(1)</script>" in text
    assert not any("onerror" in attrs or (tag == "script" and "src" not in attrs) for tag, attrs in features.elements)
    assert features.select("code", **{"class": "language-python"})

    invalid = Page((output / "invalid/index.html").read_text())
    assert len(invalid.select("code", **{"class": "language-paper"})) == 3
    assert not invalid.select("article", **{"class": "paper-card"})
    assert not invalid.select("link", rel="stylesheet", href="/css/paper-card.css")
    print("PASS: example card, metadata, disclosures, escaping, ordinary code and invalid-data fallback")
