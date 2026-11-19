"""Verify real Hugo ordering, including zero, negative, manual and new weights."""
from pathlib import Path
import argparse
import subprocess
import tempfile
import shutil
from bs4 import BeautifulSoup

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path)
args = parser.parse_args()
repo = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='document-order-') as directory:
    content = Path(directory) / 'content'
    content.mkdir()
    (content / '_index.md').write_text('---\ntitle: Overview\ndraft: true\n---\n')
    for section in ['related-work','research-journey','system-implementation','meetings']:
        (content / section).mkdir()
        (content / section / '_index.md').write_text(f'---\ntitle: {section}\ndraft: true\n---\n')
    folder = content / 'meetings/order'
    folder.mkdir()
    (folder / '_index.md').write_text('---\ntitle: Document order\ndraft: true\n---\n')
    for name, weight in [('A: Negative',-2),('B: Zero',0),('C: One',1),('D: Twenty',20)]:
        (folder / (name[0]+'.md')).write_text(f'---\ntitle: "{name}"\nweight: {weight}\ndraft: true\nsidebar_pinned: {str(weight == 20).lower()}\n---\n\nThe weight controls this document\'s position.\n')
    node = '''import {createStore} from './scripts/workspace-store.mjs';
const store=createStore(process.argv[2]);
await store.create({kind:'document',parent:'meetings/order',title:'E: Newly created'});
'''
    subprocess.run(['node','--input-type=module','-',str(content)],input=node,text=True,cwd=repo,check=True,capture_output=True)
    output = args.output.resolve() if args.output else Path(directory) / 'public'
    subprocess.run(['hugo','--source',str(repo/'site'),'--themesDir',str(repo.parent),'--theme',repo.name,
                    '--contentDir',str(content),'--destination',str(output),'--environment','workspace','--buildDrafts'],
                   check=True,capture_output=True)
    expected = ['A: Negative','B: Zero','C: One','D: Twenty','E: Newly created']
    for route in ['meetings/order/index.html','meetings/order/a/index.html','meetings/order/e-newly-created/index.html']:
        page = BeautifulSoup((output / route).read_text(),'html.parser')
        titles = [item['data-document-title'] for item in page.select('.sidebar-document')]
        assert titles == expected,(route,titles)
    index = BeautifulSoup((output/'meetings/order/index.html').read_text(),'html.parser')
    for badge in index.select('.draft-badge'):
        badge.decompose()
    assert [a.get_text(strip=True) for a in index.select('.journal-entry > a')] == expected
    if args.output:
        shutil.copytree(content,output/'sources',dirs_exist_ok=True)
        print(f'Preview: {output}')
    print('PASS: negative, zero, ascending and newly appended weights control sidebar and index order')
