"""Build real pages before/after an external edit and check all modification dates."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
import os
import subprocess
import tempfile
from bs4 import BeautifulSoup

repo = Path(__file__).resolve().parents[1]

def stamp(path, value):
    timestamp = datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    os.utime(path, (timestamp, timestamp))

def modified(page):
    node = page.select_one('.document-meta-modified time')
    assert node, 'A file-backed document must show its modification time'
    return datetime.fromisoformat(node['datetime'].replace('Z', '+00:00'))

with tempfile.TemporaryDirectory(prefix='document-updates-') as directory:
    root = Path(directory)
    content, output = root / 'content', root / 'public'
    (content / 'meetings').mkdir(parents=True)
    (content / '_index.md').write_text('---\ntitle: Home\ndraft: false\n---\n')
    (content / 'meetings/_index.md').write_text('---\ntitle: Meetings\ndraft: false\n---\n')
    doc = content / 'meetings/updated.md'
    doc.write_text('''---
title: Updated document
content_lang: en
date: 2026-11-12
lastmod: 2026-11-13T10:00:00Z
draft: false
---
Ordinary serif prose with **sans-serif bold**, <b>HTML bold</b> and ***bold italic***.

> A quotation with **bold emphasis**.

**`inline code`** remains code.
''')
    missing = content / 'meetings/no-lastmod.md'
    missing.write_text('---\ntitle: No lastmod\ncontent_lang: en-US\ndate: 2026-11-12\ndraft: false\n---\nA **bold** phrase.\n')
    chinese = content / 'meetings/chinese.md'
    chinese.write_text('---\ntitle: 中文排版\ncontent_lang: zh-CN\ndraft: false\n---\n普通正文与**加粗正文**。\n')
    current_year = datetime.now(ZoneInfo('Europe/Paris')).year
    for year in [current_year, current_year - 1]:
        (content / f'meetings/year-{year}.md').write_text(f'---\ntitle: Year {year}\ndate: {year}-02-03\nlastmod: {year}-02-03T04:05:06Z\ndraft: false\n---\n')
    before, after = '2026-11-15T01:02:03Z', '2026-11-15T01:02:29Z'
    for path in [doc, missing, chinese]: stamp(path, before)
    command = ['hugo', '--source', str(repo / 'site'), '--themesDir', str(repo.parent),
               '--theme', repo.name, '--contentDir', str(content), '--destination', str(output),
               '--cleanDestinationDir']
    def build(environment):
        subprocess.run(command + ['--environment', environment], check=True, capture_output=True, text=True)
    def read(route): return BeautifulSoup((output / route / 'index.html').read_text(), 'html.parser')
    def check_local(expected):
        page = read('meetings/updated')
        expected = datetime.fromisoformat(expected.replace('Z', '+00:00'))
        actual = modified(page)
        assert actual == expected
        assert page.select_one('.document-meta-created time')['datetime'].startswith('2026-11-12T')
        text = page.select_one('.document-meta-modified time').get_text()
        assert actual.strftime('%H:%M') in text, text
        assert actual.strftime('%H:%M:%S') not in text, text
        info = page.select_one('.article-info').get_text()
        assert actual.strftime('%H:%M') in info, info
        listing = read('meetings')
        row = next(item for item in listing.select('.journal-entry') if item.a.get_text(strip=True) == 'Updated document')
        actual = datetime.fromisoformat(row.time['datetime'].replace('Z', '+00:00'))
        assert actual == expected
        assert actual.strftime('%H:%M') in row.time.get_text(), row.time
    build('workspace')
    check_local(before)
    assert modified(read('meetings/no-lastmod')) == datetime.fromisoformat(before.replace('Z', '+00:00'))
    original = doc.read_text()
    doc.write_text(original + '\nAn external editor changed only the body.\n')
    stamp(doc, after)
    build('workspace')
    check_local(after)
    assert 'lastmod: 2026-11-13T10:00:00Z' in doc.read_text(), 'Rendering must not rewrite user metadata'
    build('production')
    for year in [current_year, current_year - 1]:
        page = read(f'meetings/year-{year}')
        expected = '02-03' if year == current_year else f'{year}-02-03'
        assert page.select_one('.document-meta-created time').get_text() == expected
        assert page.select_one('.document-meta-modified time').get_text().startswith(expected + ' 04:05')
        row = next(item for item in read('meetings').select('.journal-entry') if item.a.get_text(strip=True) == f'Year {year}')
        assert row.time.get_text() == expected + ' 04:05'

    assert modified(read('meetings/updated')) == datetime(2026, 11, 13, 10, tzinfo=timezone.utc), 'Published explicit timestamps stay stable across copies/checkouts'
    assert modified(read('meetings/no-lastmod')) == datetime.fromisoformat(before.replace('Z', '+00:00'))
    assert not read('meetings/chinese').select_one('.document-meta-created time'), 'Modification dates must not become creation dates'
    print('PASS: external body edits update cover, information and index timestamps with minute-only display and second-precision metadata')
    print('PASS: missing lastmod has a file-time fallback; creation dates and explicit publication dates are preserved')
