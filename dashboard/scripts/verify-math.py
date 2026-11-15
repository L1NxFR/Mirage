"""Check compiled formulas independently of browser JavaScript or remote CDNs."""
from pathlib import Path
import shutil
import subprocess
import tempfile
from bs4 import BeautifulSoup

repo = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='math-rendering-') as directory:
    content = Path(directory) / 'content'
    output = Path(directory) / 'public'
    (content / 'related-work').mkdir(parents=True)
    (content / '_index.md').write_text('---\ntitle: Overview\ndraft: false\n---\n')
    (content / 'related-work/_index.md').write_text('---\ntitle: Related\ndraft: false\n---\n')
    shutil.copyfile(repo / 'scripts/fixtures/editor-math.md', content / 'related-work/math-check.md')
    subprocess.run(['hugo', '--source', str(repo / 'site'), '--themesDir', str(repo.parent),
                    '--theme', repo.name, '--contentDir', str(content), '--destination', str(output)],
                   check=True, text=True)
    page = BeautifulSoup((output / 'related-work/math-check/index.html').read_text(), 'html.parser')
    article = page.select_one('.article-body')
    assert len(article.select('.katex')) == 5
    assert len(article.select('.katex-display')) == 3
    assert len(article.select('math')) == 5
    assert not article.select('code .katex')
    assert '$this stays code$' in article.select_one('pre').get_text()
    assert not page.select('script[src*="katex"]')
    assert page.select_one('link[href="/vendor/katex/katex.min.css"]')
print('Compiled math: five formulas, three display blocks, literal code preserved, local CSS.')
