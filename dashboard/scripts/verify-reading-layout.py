"""Regression checks for skipped heading levels and real footnote anchors."""
from pathlib import Path
from urllib.parse import unquote
import subprocess
import tempfile
import shutil
from bs4 import BeautifulSoup

import runpy
import os
import re
from datetime import datetime

write_layout_fixtures = runpy.run_path(str(Path(__file__).with_name('layout-fixtures.py')))['write_layout_fixtures']
repo = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='reading-layout-') as directory:
    output = Path(directory) / 'public'
    content = Path(directory) / 'content'
    shutil.copytree(repo / 'site/content', content, ignore=shutil.ignore_patterns('.obsidian', '.git'))
    write_layout_fixtures(content)
    (content / '_index.md').write_text('---\ntitle: Overview\ndraft: false\nshow_toc: true\n---\n\n## Context\n\nLayout fixture.\n\n## Goals\n\n## Progress\n')
    undated_group = content / 'meetings/undated'
    undated_group.mkdir(parents=True)
    (undated_group / '_index.md').write_text('---\ntitle: Undated group\n---\n')
    (undated_group / 'dated-child.md').write_text('---\ntitle: Dated child\ndate: 2026-11-14\n---\n')
    (content / 'related-work/format-regression.md').write_text('''---
title: Cover regression
author: Fixture Writer
date: 2026-10-01
lastmod: 2026-11-14T18:25:00+01:00
draft: false
show_toc: true
tldr: |
  **Key result** with *emphasis* and a [link](/related-work/).

  - First finding
  - Second finding
---

# Level One {#level-one}

Paragraph.

## Level Two {#level-two}

Paragraph.

### Level Three {#level-three}

Paragraph.
''')
    (content / 'system-implementation/numbering-regression.md').write_text('''---
title: Numbering regression
draft: false
show_toc: true
---

## *Opening* {#opening .numbering-test}

#### Skipped level {#skipped}

###### Deep level {#deep}

#### Sibling {#sibling}

## Second {#second}

### Repeated

### Repeated

## 2026 outlook {#year}

## <span class="section-number">99</span>Legacy {#legacy}
''')
    (content / 'system-implementation/numbering-disabled.md').write_text('''---
title: No numbering
draft: false
number_headings: false
show_toc: true
---

## Opening

### Child
''')
    # These fixtures represent historical files, rather than edits made just now.
    for path in content.rglob('*.md'):
        if match := re.search(r'^lastmod: (.+)$', path.read_text(), re.M):
            timestamp = datetime.fromisoformat(match[1].replace('Z', '+00:00')).timestamp()
            os.utime(path, (timestamp, timestamp))
    subprocess.run(['hugo', '--source', str(repo / 'site'), '--themesDir', str(repo.parent),
                    '--theme', repo.name, '--contentDir', str(content), '--destination', str(output),
                    '--environment', 'workspace', '--buildDrafts'], check=True,
                   capture_output=True, text=True)
    article = BeautifulSoup((output / 'related-work/group/中文笔记/index.html').read_text(), 'html.parser')
    toc = article.select_one('#TableOfContents')
    headings = article.select('.article-body > h2, .article-body > h3, .article-body > h4, .article-body > h5, .article-body > h6')
    assert [unquote(a['href'][1:]) for a in toc.select('a')] == [h['id'] for h in headings]
    assert len(headings) == 7, 'Collective Communication should include both h4 headings'
    assert all(li.find('a', recursive=False) for li in toc.select('li')), 'empty TOC entries'
    parent = toc.select_one('a[href="#child"]').find_parent('ul').find_parent('li')
    assert unquote(parent.find('a')['href']) == '#parent'
    assert len(article.select('.footnotes > ol > li')) == 2
    for link in article.select('.footnote-ref, .footnote-backref'):
        assert article.find(id=unquote(link['href'][1:])), f'Broken footnote anchor: {link}'
    scripts = [s.get('src', '') for s in article.select('script[src]')]
    assert any(src.startswith('/js/sidenotes.js?') for src in scripts), 'Blog footnotes must load the responsive sidenote enhancement'
    assert any(src.startswith('/js/toc.js?') for src in scripts)
    assert not any(name in src for src in scripts for name in ('fix-footnote', 'fix-toc', 'fullwidth', 'sidenotes.min.js'))
    assert 'reading-page' in article.body['class']
    specimen = BeautifulSoup((output / 'related-work/paper-example/index.html').read_text(), 'html.parser')
    assert 'reading-page' not in specimen.body['class']
    assert not specimen.select('#TableOfContents')
    assert not any('/js/sidenotes.js' in s.get('src', '') for s in specimen.select('script'))
    # Every route uses one navigation component and the same independent CSS.
    nav_labels = None
    for route in ['index.html', 'related-work/index.html', 'research-journey/index.html', 'meetings/index.html',
                  'related-work/group/中文笔记/index.html', 'related-work/paper-example/index.html']:
        page = BeautifulSoup((output / route).read_text(), 'html.parser')
        assert 'site-page' in page.body['class']
        nav = page.select_one('nav.site-header')
        assert nav and nav.get('aria-label') == 'Main navigation'
        labels = [(a.get_text(), a['href']) for a in nav.select('a')]
        if nav_labels is None:
            nav_labels = labels
        assert labels == nav_labels, f'Navigation differs on {route}'
        css = [link['href'] for link in page.select('link[rel="stylesheet"]')]
        assert any(href.startswith('/css/site-header.css?') for href in css), f'Missing shared header styles on {route}'
    for route in ['related-work/index.html', 'research-journey/index.html', 'meetings/index.html', 'search/index.html',
                  'system-implementation/index.html']:
        page = BeautifulSoup((output / route).read_text(), 'html.parser')
        title = page.select('header.page-title > h1.title')
        assert len(title) == 1, f'Missing or duplicate shared title on {route}'
        assert len(page.select('h1.title')) == 1
        assert any(link['href'].startswith('/css/page-title.css?')
                   for link in page.select('link[rel="stylesheet"]'))
    for page in [article, specimen]:
        assert page.select_one('header.blog-cover > h1.title')
        assert not page.select('header.page-title')
        assert not page.select('.paper-contact, .paper-logos')
    assert not article.select('.blog-tldr'), 'Absent tldr must not create an empty block'
    assert not specimen.select('.blog-tldr-label'), 'Summary displays content without a TL;DR heading'
    assert specimen.select_one('.blog-tldr-content').get_text(strip=True).startswith('Example summary')
    assert specimen.select_one('header.paper-cover > h1.title')
    assert not specimen.select('header.page-title'), 'Paper cover should remain independent'
    fixture = BeautifulSoup((output / 'related-work/format-regression/index.html').read_text(), 'html.parser')
    assert fixture.select_one('.blog-cover h1.title').get_text() == 'Cover regression'
    assert fixture.select_one('.document-meta-author .author').get_text() == 'Fixture Writer'
    assert fixture.select_one('.document-meta-created time')['datetime'].startswith('2026-10-01T')
    assert datetime.fromisoformat(fixture.select_one('.document-meta-modified time')['datetime']) == datetime.fromisoformat('2026-11-14T18:25:00+01:00')
    assert not fixture.select('.document-meta-created .document-meta-modified'), 'Creation and modification are separate fields'
    assert len(fixture.select('.document-meta > .document-meta-item > svg[aria-hidden="true"]')) == 3
    assert {'Created', 'Last modified'} <= {node.get_text() for node in fixture.select('.article-info dt')}
    search_link = fixture.select_one('.site-header a[data-search-open]')
    assert search_link['aria-label'] == 'Search' and search_link.select_one('svg[aria-hidden="true"]')
    assert search_link.select_one('.visually-hidden').get_text() == 'Search'
    undated = BeautifulSoup((output / 'meetings/undated/index.html').read_text(), 'html.parser')
    assert not undated.select('.document-meta-created time'), 'Child dates must not become group creation dates'
    assert undated.select_one('.document-meta-modified time'), 'Groups use their own source modification time'
    assert len(undated.select('.document-meta [aria-label="Not recorded"]')) == 1
    summary = fixture.select_one('.blog-tldr-content')
    assert summary.select_one('strong').get_text() == 'Key result'
    assert summary.select_one('em').get_text() == 'emphasis'
    assert summary.select_one('a')['href'] == '/related-work/'
    assert len(summary.select('li')) == 2
    assert not fixture.select('.paper-authors, .paper-affiliations, .paper-equal, .paper-logos, .paper-contact')
    assert [h.name for h in fixture.select('.article-body > :is(h1,h2,h3)')] == ['h1','h2','h3']
    assert [a['href'] for a in fixture.select('#TableOfContents a')] == ['#level-one','#level-two','#level-three']
    def numbers(page, selector):
        return [node.get_text() for node in page.select(selector + ' .section-number')]

    assert numbers(fixture, '.article-body > :is(h1,h2,h3)') == ['1', '1.1', '1.1.1']
    assert numbers(article, '.article-body > :is(h2,h3,h4,h5,h6)') == ['1','2','3','3.1','4','4.1','4.2']
    assert numbers(specimen, '.article-body > :is(h2,h3)') == ['1','2','3','3.1','3.2','3.3','4','5','5.1','5.2','5.3','5.4','5.5','6']
    assert specimen.find(id='31-game-protocol'), 'Existing numbered deep links must survive migration'
    assert not specimen.select('.paper-cover .section-number'), 'Cover title, authors and TL;DR are not outline sections'
    numbering = BeautifulSoup((output / 'system-implementation/numbering-regression/index.html').read_text(), 'html.parser')
    outline = numbering.select('.article-body > :is(h1,h2,h3,h4,h5,h6)')
    expected = ['1','1.1','1.1.1','1.2','2','2.1','2.2','3','4']
    assert numbers(numbering, '.article-body > :is(h1,h2,h3,h4,h5,h6)') == expected
    assert numbers(numbering, '#TableOfContents a') == expected
    assert all(len(h.select('.section-number')) == 1 for h in outline), 'Manual legacy numbers must not duplicate generated numbers'
    assert numbering.select_one('h2#opening.numbering-test em').get_text() == 'Opening', 'Heading attributes/inline formatting must survive'
    assert numbering.select_one('#year').get_text(strip=True).endswith('2026 outlook'), 'Do not strip meaningful leading digits'
    assert '99' not in numbering.select_one('#legacy').get_text()
    assert [unquote(a['href'][1:]) for a in numbering.select('#TableOfContents a')] == [h['id'] for h in outline]
    assert len({h['id'] for h in outline}) == len(outline), 'Repeated titles retain unique Hugo anchors'
    disabled = BeautifulSoup((output / 'system-implementation/numbering-disabled/index.html').read_text(), 'html.parser')
    assert not disabled.select('.section-number'), 'Per-page opt-out applies to both heading and TOC'
    overview = BeautifulSoup((output / 'index.html').read_text(), 'html.parser')
    assert overview.select_one('.document-meta-author .author').get_text() == 'Nan Lin'
    assert overview.select_one('.site-header .site-byline').get_text() == 'by Nan Lin'
    assert overview.select_one('main.article-layout.blog-layout > .blog-page-heading > header.blog-cover > h1.title').get_text() == 'Overview'
    assert not overview.select('header.page-title, .blog-sidebar'), 'Overview uses the document cover without a journal tree'
    assert {'document-page', 'reading-page', 'blog'} <= set(overview.body['class'])
    assert overview.select_one('.article-body > p'), 'Overview Markdown uses the shared article body'
    for stylesheet in ['document', 'blog-fonts', 'blog-layout']:
        assert any(link['href'].startswith(f'/css/{stylesheet}.css?') for link in overview.select('link[rel="stylesheet"]'))
    overview_headings = overview.select('.article-body > :is(h1,h2,h3,h4,h5,h6)')
    assert [unquote(a['href'][1:]) for a in overview.select('#TableOfContents a')] == [h['id'] for h in overview_headings]
    assert numbers(overview, '.article-body > :is(h1,h2,h3,h4,h5,h6)') == [str(i + 1) for i in range(len(overview_headings))]
    assert overview.select_one('#article-editor')['data-path'] == '_index.md'
    assert overview.select_one('.article-tools a[download="_index.md"]'), 'Overview retains its source editing/download controls'
    print('PASS: complete nested TOC, both footnote targets/backlinks, local script, overview and paper isolation')
    print('PASS: common header component and stylesheet across six page types')
    print('PASS: common non-blog titles, default Blog covers, optional TL;DR and removed contact/logos')
    print('PASS: Markdown TL;DR, sparse metadata, semantic H1/H2/H3 and corresponding TOC anchors')
    print('PASS: automatic H1–H6 numbering, skipped levels, resets, TOC parity, legacy migration and opt-out')
