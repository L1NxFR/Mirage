"""Build isolated highlight specimens; optionally keep output for browser checks."""
from pathlib import Path
import argparse
import subprocess
import tempfile
from bs4 import BeautifulSoup

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, help='Keep a browser-ready test site at this directory')
args = parser.parse_args()
repo = Path(__file__).resolve().parents[1]
colors = {'🔴': 'red', '🟠': 'orange', '🟡': 'yellow', '🟢': 'green', '🔵': 'blue', '🟣': 'purple'}
samples = 'Default ==highlight **bold**==.\n\n' + '\n\n'.join(f'=={emoji}{color} highlight==' for emoji, color in colors.items())
samples += '\n\n<mark style="background: #ADCCFFA6;">Custom blue</mark>\n\n`==literal==` and \\==escaped==.\n\n```text\n==🔴code==\n```\n'
source = '---\ntitle: "[Agent] Highlight specimen"\ncontent_lang: en\ndraft: true\ndisable_highlight: true\ntldr: |\n' + ''.join('  ' + line + '\n' for line in samples.splitlines()) + '---\n\n' + samples
with tempfile.TemporaryDirectory(prefix='highlight-check-') as directory:
    base = Path(directory)
    content = base / 'content'
    content.mkdir()
    (content / '_index.md').write_text('---\ntitle: Overview\ndraft: true\n---\n')
    for section in ['related-work', 'research-journey', 'system-implementation', 'meetings']:
        (content / section).mkdir()
        (content / section / '_index.md').write_text(f'---\ntitle: {section}\ndraft: true\n---\n')
    (content / 'related-work/agent-highlights.md').write_text(source)
    output = args.output.resolve() if args.output else base / 'public'
    subprocess.run(['hugo', '--source', str(repo / 'site'), '--themesDir', str(repo.parent), '--theme', repo.name,
                    '--contentDir', str(content), '--destination', str(output), '--environment', 'workspace', '--buildDrafts'],
                   check=True, capture_output=True, text=True)
    page = BeautifulSoup((output / 'related-work/agent-highlights/index.html').read_text(), 'html.parser')
    for selector in ['.article-body', '.blog-tldr-content']:
        body = page.select_one(selector)
        assert len(body.select('mark')) == 8, f'{selector}: native marks missing'
        assert body.select_one('mark strong').get_text() == 'bold'
        for color in colors.values():
            assert body.select_one(f'mark[data-highlight-color="{color}"]').get_text() == f'{color} highlight'
        assert body.select_one('mark[style]')['style'] == 'background: #ADCCFFA6;'
        assert body.select_one('code').get_text() == '==literal=='
        assert body.select_one('pre code').get_text().strip() == '==🔴code=='
        assert '==escaped==' in body.get_text()
    assert page.select_one('link[href^="/css/text-highlights.css?"]')
    if args.output:
        # The read-only editor fetches this synthetic source, never a user note.
        target = output / 'sources/related-work/agent-highlights.md'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source)
    print('PASS: default/six-color highlights, custom HTML, nested emphasis and code isolation in body and summary')
    if args.output:
        print(f'Preview: {output}')
