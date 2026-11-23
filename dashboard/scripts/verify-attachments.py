"""Verify that Obsidian attachment links resolve to files in Hugo's output."""
from html.parser import HTMLParser
from bs4 import BeautifulSoup
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.parse import quote, unquote, urlsplit


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


repo = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="obsidian-attachments-") as tmp:
    source = Path(tmp) / "site"
    content = source / "content"
    (content / "blog/nested").mkdir(parents=True)
    (content / "Attachments").mkdir()
    (content / "Excalidraw").mkdir()
    shutil.copy(repo / "site/hugo.yaml", source / "hugo.yaml")
    for folder in ("layouts", "static", "data"):
        (source / folder).symlink_to(repo / "site" / folder, target_is_directory=True)

    image = "CleanShot 2026-11-01 at 17.25.57@2x.png"
    unicode_image = "子目录/通信图 100%25.png"
    pdf = "paper notes.pdf"
    for name in (image, unicode_image, pdf):
        attachment = content / "Attachments" / name
        attachment.parent.mkdir(parents=True, exist_ok=True)
        attachment.write_bytes(b"attachment fixture")
    (content / "Excalidraw/drawing.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    (content / "Excalidraw/drawing.excalidraw.md").write_text("PRIVATE DRAWING SOURCE")
    (content / "Attachments/private.md").write_text("PRIVATE ATTACHMENT SOURCE")

    for filename, prefix in (("root.md", ""), ("blog/nested/note.md", "../../")):
        (content / filename).write_text(f'''---
title: Attachment fixture
draft: false
---
![screenshot]({prefix}Attachments/{quote(image)})
![unicode]({prefix}Attachments/{quote(unicode_image)})
[download]({prefix}Attachments/{quote(pdf)}?download=1#page=2)
![embedded PDF]({prefix}Attachments/{quote(pdf)}#page=3)
![drawing]({prefix}Excalidraw/drawing.svg)
![remote](https://cdn.example.org/Excalidraw/remote.svg?raw=1#part)
![cdn](//cdn.example.org/Excalidraw/remote.svg)
![legacy](/media/legacy.png)
![](/media/no-caption.png)
![中文图注](/media/caption.png "悬停提示")
[external PDF](https://example.org/paper.pdf#page=4)
''')

    output = Path(tmp) / "public"
    build = subprocess.run([
        "hugo", "--source", str(source), "--themesDir", str(repo.parent),
        "--theme", repo.name, "--baseURL", "https://example.org/preview/",
        "--destination", str(output), "--cacheDir", str(Path(tmp) / "cache"),
    ], capture_output=True, text=True)
    assert build.returncode == 0, build.stdout + build.stderr

    for filename in ("root/index.html", "blog/nested/note/index.html"):
        elements = Page((output / filename).read_text()).elements
        soup = BeautifulSoup((output / filename).read_text(), 'html.parser')
        captioned = soup.select_one('img[alt="中文图注"]').parent
        assert captioned.select_one('.image-caption').get_text() == '中文图注'
        assert captioned.img['title'] == '悬停提示'
        assert 'markdown-figure' not in soup.select_one('img[alt=""]').parent.get('class', [])
        assert not soup.select_one('a.pdf-attachment .image-caption')
        assert len(soup.select('.image-caption')) == 7
        images = {attrs.get("alt"): attrs.get("src") for tag, attrs in elements if tag == "img"}
        links = [attrs.get("href") for tag, attrs in elements if tag == "a"]
        for alt, path in (("screenshot", "attachments/" + image),
                          ("unicode", "attachments/" + unicode_image),
                          ("drawing", "excalidraw/drawing.svg")):
            resolved = unquote(urlsplit(images[alt]).path)
            assert resolved == "/preview/" + path, (filename, alt, images[alt])
            assert (output / path).is_file(), f"Missing published attachment: {path}"
        assert any(unquote(url) == f"/preview/attachments/{pdf}?download=1#page=2" for url in links)
        assert any(unquote(url) == f"/preview/attachments/{pdf}#page=3" for url in links)
        assert "embedded PDF" not in images, "PDF embeds must be downloadable links"
        assert images["remote"] == "https://cdn.example.org/Excalidraw/remote.svg?raw=1#part"
        assert images["cdn"] == "//cdn.example.org/Excalidraw/remote.svg"
        assert images["legacy"] == "/media/legacy.png"
        assert "https://example.org/paper.pdf#page=4" in links
    assert (output / "attachments" / pdf).is_file()
    assert not (output / "attachments/private.md").exists()
    assert not (output / "attachments/private/index.html").exists()
    assert not (output / "excalidraw/drawing.excalidraw.md").exists()
    print("PASS: root/nested notes, published attachments, spaces/Unicode/%, PDF links, Excalidraw and remote URLs")
