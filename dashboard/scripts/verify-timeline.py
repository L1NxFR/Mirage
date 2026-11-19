"""Check that the authoring syntax and legacy shortcode both build as timelines."""
from pathlib import Path
from html.parser import HTMLParser
import subprocess
import tempfile

class Page(HTMLParser):
    def __init__(self, html):
        super().__init__(); self.tags = []; self.feed(html)
    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

repo = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='timeline-hugo-') as tmp:
    tmp = Path(tmp)
    content = tmp / 'content'
    content.mkdir()
    (content / 'modern.md').write_text('''---
title: Timeline fixture
draft: false
---
````timeline
# Progress
collapse: 1
- [x] Done <script>alert(1)</script>
- [/] Working {open}
  **Details**

  - nested item
  ```python
  print(1)
  ```
- [ ] Later
- [!] Failed
````
''')
    (content / 'legacy.md').write_text('''---
title: Legacy
draft: false
---
{{< timeline >}}
- text: Legacy step
  status: done
{{< /timeline >}}
''')
    subprocess.run(['hugo', '--source', str(repo / 'site'), '--themesDir', str(repo.parent), '--theme', repo.name,
                    '--contentDir', str(content), '--destination', str(tmp / 'public'), '--cacheDir', str(tmp / 'cache')],
                   capture_output=True, text=True, check=True)
    html = (tmp / 'public/modern/index.html').read_text()
    page = Page(html)
    assert sum(a.get('class') == 'timeline' for _, a in page.tags) == 1, 'timeline fence was not rendered'
    assert sum(a.get('class') == 'timeline__step' for _, a in page.tags) == 4
    assert [a['data-status'] for _, a in page.tags if 'data-status' in a] == ['running', 'pending', 'error']
    assert any(t == 'details' and a.get('class') == 'timeline__detail' and 'open' in a for t, a in page.tags)
    assert '<strong>Details</strong>' in html and '<li>nested item</li>' in html
    assert '&lt;script&gt;' in html and '<script>alert(1)</script>' not in html
    assert '/css/timeline.css' in html, 'timeline-only pages need the component stylesheet'
    assert 'class="timeline__step"' in (tmp / 'public/legacy/index.html').read_text()
    print('PASS Hugo task syntax, details, statuses, escaped titles, CSS, legacy shortcode')
