"""Check actual Hugo output: section scoping, publication and search anchors."""
import json
import re
from pathlib import Path
import subprocess
import tempfile
import shutil
from urllib.parse import unquote
from bs4 import BeautifulSoup

import runpy

write_layout_fixtures = runpy.run_path(str(Path(__file__).with_name('layout-fixtures.py')))['write_layout_fixtures']
repo = Path(__file__).resolve().parents[1]
config = json.loads(subprocess.check_output(['hugo', 'config', '--source', str(repo / 'site'), '--themesDir', str(repo.parent), '--theme', repo.name, '--format', 'json'], text=True))
expected_repository = config.get('params', {}).get('source_repository', '')
with tempfile.TemporaryDirectory(prefix='.navigation-search-', dir=repo / 'site') as directory:
    output = Path(directory)
    baseline = output / 'published-content'
    shutil.copytree(repo / 'site/content', baseline, ignore=shutil.ignore_patterns('.obsidian'))
    write_layout_fixtures(baseline)
    # Exercise explicit publication independently of the workspace's current drafts.
    published = ['_index.md', 'search.md', 'related-work/_index.md', 'research-journey/_index.md',
                 'system-implementation/_index.md', 'meetings/_index.md',
                 'related-work/group/card-example.md', 'related-work/group/中文笔记.md',
                 'related-work/paper-example.md']
    for name in published:
        page = baseline / name
        source = page.read_text()
        source = re.sub(r'^draft:.*$', 'draft: false', source, count=1, flags=re.M)
        page.write_text(source)
    (baseline / 'related-work/group/_index.md').write_text('---\ntitle: Communication\ndraft: false\n---\n')
    command = ['hugo', '--source', str(repo / 'site'), '--themesDir', str(repo.parent),
               '--theme', repo.name, '--contentDir', str(baseline), '--destination', str(output), '--minify']
    subprocess.run(command, check=True, capture_output=True)
    blog_routes = ['related-work/index.html', 'related-work/group/中文笔记/index.html',
                   'related-work/group/card-example/index.html', 'related-work/paper-example/index.html']
    ordinary_routes = ['index.html', 'search/index.html']
    empty_routes = ['research-journey/index.html', 'system-implementation/index.html', 'meetings/index.html']
    blog_routes += empty_routes
    for removed in ['about', 'cv', 'tags', 'categories', 'blog']:
        assert not (output / removed).exists(), removed
    assert not (output / 'docs').exists(), 'Removed documentation must not be published'
    for route in blog_routes + ordinary_routes:
        page = BeautifulSoup((output / route).read_text(), 'html.parser')
        assert bool(page.select('.blog-sidebar')) == (route in blog_routes), route
        assert len(page.select('.article-tools')) == 1, route
        assert page.select_one('#article-editor[data-path]')
        assert page.select_one('[data-editor-save]')
        assert not page.select('[data-editor-download]')
        styles = [link['href'] for link in page.select('link[rel="stylesheet"]')]
        assert any('/css/blog-layout.css' in href for href in styles) == (route in blog_routes or route == 'index.html'), route
        assert not page.select_one('.site-header a[href="/docs/"]'), route
        assert [a.get_text(strip=True) for a in page.select('.site-header .menu a')] == ['Overview', 'Related', 'Research', 'Docs', 'Meetings', 'Search']
        assert len(page.select('.site-header .menu [aria-current="page"]')) == 1
        assert page.select_one('.site-header [data-search-open]'), route
        assert len(page.select('#site-search')) == 1, route
        assert page.select_one('#site-search[aria-labelledby="site-search-title"]')
        for script in page.select('script[src]'):
            assert 'fuse-search' not in script['src']
        if route in blog_routes:
            editor = page.select_one('#article-editor')
            assert editor and len(page.select('#article-editor')) == 1
            source_url = unquote(editor['data-source-url'])
            assert source_url.startswith('/sources/')
            original_path = baseline / source_url.removeprefix('/sources/')
            assert (output / source_url.lstrip('/')).read_bytes() == original_path.read_bytes(), source_url
            assert page.select_one(f'.article-tools a[download="{editor["data-filename"]}"]')
            assert page.select_one('[data-edit-article][aria-controls="article-editor"]')
            repository_link = page.select_one('.article-tools a[title="View GitHub repository"]')
            assert bool(repository_link) == bool(expected_repository)
            if repository_link:
                assert repository_link['href'] == expected_repository
            links = page.select('.blog-sidebar a')
            assert len(links) >= 1
            assert page.select_one('[data-sidebar-search]')
            assert [b.get_text() for b in page.select('[data-create-kind]')] == ['Document', 'Group']
            assert len(page.select('.blog-sidebar a[aria-current="page"]')) == 1
            assert page.select_one('main.blog-layout > .blog-sidebar')
            group = page.select_one('.blog-tree-group')
            if route in empty_routes:
                empty = page.select_one('.archive-empty')
                if empty:
                    assert empty.get_text(strip=True) == 'No published entries yet.'
                    assert not group
                else:
                    assert page.select_one('.journal-index'), 'Populated journals show their entries'
                continue
            assert group and group.select_one('summary').get_text(strip=True) == 'Communication'
            assert group.has_attr('open') == ('/group/' in route), route
            assert page.select_one('main.blog-layout > .blog-page-heading > header'), 'Navigation must start alongside the title'
            if '/group/' in route:
                active = page.select_one('.blog-sidebar a[aria-current="page"]')
                assert active.find_parent('details', class_='blog-tree-group') == group
    index = json.loads((output / 'index.json').read_text())
    assert any(page['uri'] == '/' and page['title'] == 'Overview' for page in index)
    assert not any(page['section'] in ['blog', 'docs', 'tags'] for page in index)
    assert not any('private-note' in page['uri'].lower() for page in index)
    assert not any('private-note' in str(p).lower() for p in (output / 'sources').rglob('*.md'))
    for page in index:
        path = output / unquote(page['uri']).lstrip('/') / 'index.html'
        soup = BeautifulSoup(path.read_text(), 'html.parser')
        for section in page['sections']:
            if section['anchor']:
                assert soup.find(id=section['anchor']), (page['uri'], section['anchor'])
    collective = next(p for p in index if '中文笔记' in unquote(p['uri']))
    assert len(collective['sections']) == 7
    assert any(s['anchor'] == 'child' for s in collective['sections'])
    print('PASS: Blog-only rails, removed documentation, shared search dialog, all search anchors resolve')
    print('PASS: Blog editor/download controls, byte-exact Markdown with metadata, draft source exclusion')

    # Even an explicit draft preview must not leak drafts into the shared index/tree.
    subprocess.run(command + ['--buildDrafts'], check=True, capture_output=True)
    preview_index = json.loads((output / 'index.json').read_text())
    assert not any('private-note' in p['uri'].lower() for p in preview_index)
    preview = BeautifulSoup((output / 'related-work/index.html').read_text(), 'html.parser')
    assert not any('private-note' in a['href'].lower() for a in preview.select('.blog-sidebar a'))
    print('PASS: draft-enabled previews keep drafts out of navigation and search')

    # Exercise adding real records in every journal and deploying under a project path.
    content = Path(directory) / 'fixtures'
    shutil.copytree(baseline, content, ignore=shutil.ignore_patterns('.obsidian'))
    sections = ['related-work', 'research-journey', 'system-implementation', 'meetings']
    for section in sections:
        folder = content / section / 'nested'
        folder.mkdir(exist_ok=True)
        (folder / '_index.md').write_text('---\ntitle: Experiments\ndraft: false\n---\n')
        deep = folder / 'deeper'
        deep.mkdir()
        (deep / 'result.md').write_text('---\ntitle: Deep result\ndate: 2026-10-01\ndraft: false\n---\n')
        hidden = content / section / 'hidden'
        hidden.mkdir()
        (hidden / 'draft.md').write_text('---\ntitle: Hidden draft\ndraft: true\n---\n')
        (folder / 'default-draft.md').write_text('---\ntitle: Default draft\n---\nUnfinished work.\n')
        default_group = content / section / 'default-group'
        default_group.mkdir()
        (default_group / '_index.md').write_text('---\ntitle: Draft group\n---\n')
        for name, date, extra in [('older', '2026-01-01', 'lastmod: 2026-11-13T16:45:00+01:00'), ('newer', '2026-11-14', 'lastmod: 2026-11-14'),
                                  ('pinned', '2025-01-01', 'weight: -1'),
                                  ('private', '2026-11-14', 'draft: true')]:
            (folder / f'{name}.md').write_text(
                f'---\ntitle: {section}-{name}\ndate: {date}\n{extra}\n' +
                ('' if name == 'private' else 'draft: false\n') +
                'show_toc: true\n---\n\n## 验证\n\n科研记录检索样例。\n')
    (content / 'standalone-draft.md').write_text('---\ntitle: Standalone draft\n---\nUnfinished work.\n')
    fixture_output = Path(directory) / 'fixture-public'
    subprocess.run(command + ['--contentDir', str(content), '--destination', str(fixture_output),
                              '--baseURL', 'https://example.org/project/'], check=True, capture_output=True)
    fixture_index = json.loads((fixture_output / 'index.json').read_text())
    assert not (fixture_output / 'standalone-draft/index.html').exists()
    for section in sections:
        assert not (fixture_output / section / 'default-group/index.html').exists(), 'Groups also default to drafts'
        assert not (fixture_output / section / 'nested/default-draft/index.html').exists(), 'Omitted draft must default to true'
        assert not (fixture_output / 'sources' / section / 'nested/default-draft.md').exists()
        archive = BeautifulSoup((fixture_output / section / 'index.html').read_text(), 'html.parser')
        entries = [a['href'] for a in archive.select('.journal-entry a')]
        prefix = f'/project/{section}/nested/'
        assert not archive.select('.archive-month, .archive-pinned')
        folder = next(node for node in archive.select('.journal-folder > details')
                      if node.find('summary', recursive=False).get_text(strip=True) == 'Experiments')
        direct = folder.find('ul', recursive=False).select(':scope > .journal-entry')
        assert [node.a['href'] for node in direct] == [prefix + 'pinned/', prefix + 'newer/', prefix + 'older/']
        assert folder.select_one('.journal-folder .journal-entry a')['href'] == prefix + 'deeper/result/'
        older = direct[-1].select_one('time')
        assert older['datetime'] == '2026-11-13T23:45:00+08:00'
        assert older.get_text(strip=True) == '2026-11-13 23:45:00'
        assert '2026-11-14 00:00:00' == direct[1].select_one('time').get_text(strip=True)
        assert not any('/hidden/' in href or '/private/' in href or '/default-draft/' in href for href in entries)
        assert all(node.has_attr('open') for node in archive.select('.journal-folder > details'))
        assert all(node.select_one('.journal-leader[aria-hidden="true"]') for node in archive.select('.journal-entry'))
        article = BeautifulSoup((fixture_output / section / 'nested/newer/index.html').read_text(), 'html.parser')
        assert article.select_one('.blog-cover h1').get_text() == section + '-newer'
        assert article.select_one('.menu [aria-current="page"]')['href'] == f'/project/{section}/'
        assert article.select_one('.blog-sidebar [aria-current="page"]')['href'] == prefix + 'newer/'
        assert all(a['href'].startswith(f'/project/{section}/') for a in article.select('.blog-sidebar a'))
        assert not any('private' in a['href'] for a in article.select('.blog-sidebar a'))
        assert article.select_one('#TableOfContents a')
        assert article.select_one('#article-editor')['data-source-url'].startswith(f'/project/sources/{section}/')
        assert any(p['uri'] == prefix + 'newer/' for p in fixture_index)
    assert not any('/private/' in p['uri'] or '/default-draft/' in p['uri'] or '/standalone-draft/' in p['uri'] for p in fixture_index)
    print('PASS: all four journals support records, nested indexes, update timestamps, scoped ordering, isolated trees and project subpaths')
    subprocess.run(command + ['--contentDir', str(content), '--destination', str(fixture_output),
                              '--buildDrafts'], check=True, capture_output=True)
    for section in sections:
        assert (fixture_output / section / 'nested/default-draft/index.html').exists(), 'Drafts stay available in local preview'
    preview_index = json.loads((fixture_output / 'index.json').read_text())
    assert not any('default-draft' in p['uri'] or 'standalone-draft' in p['uri'] for p in preview_index)
    print('PASS: omitted draft defaults to true across all documents; explicit false publishes; draft previews stay out of search')
    # A replacement Overview without a draft field also inherits the global default.
    home = content / '_index.md'
    home.write_text(re.sub(r'^draft:.*\n', '', home.read_text(), count=1, flags=re.M))
    default_output = Path(directory) / 'default-public'
    subprocess.run(command + ['--contentDir', str(content), '--destination', str(default_output)],
                   check=True, capture_output=True)
    assert not (default_output / 'index.html').exists(), 'Overview also defaults to a draft'
    print('PASS: default drafts cover the Overview, journal groups, nested documents and future standalone pages')
