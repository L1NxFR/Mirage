// Reapply the local USENIX fix after updating Scientific Article Card (v1.11.2).
import { readFile, writeFile } from 'node:fs/promises';

const folder = new URL('../site/content/.obsidian/plugins/scientific-article-card/', import.meta.url);
const main = new URL('main.js', folder);
const original = await readFile(main, 'utf8');
let source = original;
const patches = [
  [
    '\t\t"aacrjournals.org", "ahajournals.org", "rupress.org", "life-science-alliance.org",',
    '\t\t"aacrjournals.org", "ahajournals.org", "rupress.org", "life-science-alliance.org",\n\t\t"usenix.org",',
  ],
  [
    '\t\tconst title = one("citation_title", "dc.title", "og:title", "twitter:title") || clean(doc.title);',
    [
      '\t\tlet title = one("citation_title", "dc.title", "og:title", "twitter:title") || clean(doc.title);',
      '\t\tlet abstract = one("citation_abstract", "dc.description", "og:description", "description");',
      '\t\tconst usenixPaper = hostOf(url) === "usenix.org" && !!one("citation_conference_title");',
      '\t\tif (usenixPaper) {',
      '\t\t\t// USENIX citation titles retain BibTeX braces; the abstract lives in the page body.',
      '\t\t\ttitle = title.replace(/[{}]/g, "");',
      '\t\t\tconst description = doc.querySelector(".field-name-field-paper-description .field-item");',
      '\t\t\tif (!abstract && description) abstract = description.innerHTML;',
      '\t\t}',
    ].join('\n'),
  ],
  [
    '\t\t\t\tpublisher: one("citation_publisher", "dc.publisher"),\n\t\t\t\tabstract: htmlToText(one("citation_abstract", "dc.description", "og:description", "description")),',
    [
      '\t\t\t\tpublisher: one("citation_publisher", "dc.publisher") || (usenixPaper ? "USENIX Association" : ""),',
      '\t\t\t\ttypes: one("citation_conference_title") ? ["Conference Paper"] : [],',
      '\t\t\t\tabstract: htmlToText(abstract),',
    ].join('\n'),
  ],
];
for (const [before, after] of patches) {
  if (source.includes(after)) continue;
  if (source.split(before).length !== 2) {
    throw new Error('Plugin source has changed; review the USENIX patch before applying. No files were written.');
  }
  source = source.replace(before, () => after);
}

const settingsFile = new URL('data.json', folder);
let saved = null;
try {
  saved = await readFile(settingsFile, 'utf8');
} catch (error) {
  if (error.code !== 'ENOENT') throw error;
}
const settings = saved ? JSON.parse(saved) : {};
let nextSettings = saved;
if (typeof settings.pasteDomains === 'string' && !settings.pasteDomains.split(/[\s,]+/).includes('usenix.org')) {
  settings.pasteDomains = settings.pasteDomains.trimEnd() + '\nusenix.org';
  nextSettings = JSON.stringify(settings, null, 2) + '\n';
}
if (source !== original) await writeFile(main, source);
if (nextSettings !== saved) await writeFile(settingsFile, nextSettings);
console.log('USENIX support is installed. Reload Scientific Article Card in Obsidian to activate it.');
