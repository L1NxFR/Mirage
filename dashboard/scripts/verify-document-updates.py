"""Build real pages before/after an external edit and check all modification dates."""
from datetime import datetime, timedelta
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
    cases = [
        ('offset', '2026-12-31T18:30:45+01:00', '2027-01-01T01:30:45+08:00'),
        ('utc', '2026-12-31T17:30:45Z', '2027-01-01T01:30:45+08:00'),
        ('beijing', '2027-01-01T01:30:45+08:00', '2027-01-01T01:30:45+08:00'),
        ('naive', '2027-01-01T01:30:45', '2027-01-01T01:30:45+08:00'),
    ]
    (content / 'archive').mkdir()
    (content / 'archive/_index.md').write_text('---\ntitle: Archive\ndraft: false\n---\n')
    for name, value, expected in cases:
        (content / f'archive/{name}.md').write_text(
            f'---\ntitle: {name}\ndate: {value}\nlastmod: {value}\ndraft: false\n---\n')
    before, after = '2026-11-15T16:02:03Z', '2026-11-15T16:02:29Z'
    for path in [doc, missing, chinese]: stamp(path, before)
    command = ['hugo', '--source', str(repo / 'site'), '--themesDir', str(repo.parent),
               '--theme', repo.name, '--contentDir', str(content), '--destination', str(output),
               '--cleanDestinationDir']
    def build(environment):
        subprocess.run(command + ['--environment', environment], check=True, capture_output=True, text=True, env={**os.environ, 'TZ': 'America/Los_Angeles'})
    def read(route): return BeautifulSoup((output / route / 'index.html').read_text(), 'html.parser')
    def check_local(expected):
        page = read('meetings/updated')
        expected = datetime.fromisoformat(expected.replace('Z', '+00:00'))
        actual = modified(page)
        assert actual == expected
        assert actual.utcoffset() == timedelta(hours=8), actual
        assert page.select_one('.document-meta-created time')['datetime'] == '2026-11-12T00:00:00+08:00'
        text = page.select_one('.document-meta-modified time').get_text()
        assert actual.strftime('%Y-%m-%d %H:%M:%S') in text, text
        info = page.select_one('.article-info').get_text()
        assert actual.strftime('%H:%M:%S') in info, info
        listing = read('meetings')
        row = next(item for item in listing.select('.journal-entry') if item.a.get_text(strip=True) == 'Updated document')
        actual = datetime.fromisoformat(row.time['datetime'].replace('Z', '+00:00'))
        assert actual == expected
        assert actual.utcoffset() == timedelta(hours=8), actual
        assert actual.strftime('%H:%M:%S') in row.time.get_text(), row.time
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
    assert modified(read('meetings/updated')).isoformat() == '2026-11-13T18:00:00+08:00', 'Published explicit timestamps stay stable across copies/checkouts'
    assert modified(read('meetings/no-lastmod')) == datetime.fromisoformat(before.replace('Z', '+00:00'))
    assert not read('meetings/chinese').select_one('.document-meta-created time'), 'Modification dates must not become creation dates'
    for name, value, expected in cases:
        page = read(f'archive/{name}')
        assert page.select_one('.document-meta-created time')['datetime'] == expected, name
        assert modified(page).isoformat() == expected, name
        assert '01:30:45 UTC+08:00' in page.select_one('.article-info').get_text(), name
    archive = read('archive')
    assert [heading.get_text() for heading in archive.select('main h2')] == ['2027']
    assert {node['aria-label'] for node in archive.select('.archive-month')} == {'January 2027'}
    assert {node.get_text() for node in archive.select('.archive-entry time')} == {'2027-01-01'}
    print('PASS: explicit offsets and naive dates use Beijing time across the year boundary')
    print('PASS: external body edits update cover, information and index timestamps to the second')
    print('PASS: missing lastmod has a file-time fallback; creation dates and explicit publication dates are preserved')
