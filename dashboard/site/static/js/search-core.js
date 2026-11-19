/* Static, Unicode-aware substring search. No network service or tokenizer. */
(function (root) {
  'use strict';
  const fold = value => value.normalize('NFKC').toLocaleLowerCase();
  function parse(query) {
    const groups = [[]];
    let token = '', quoted = false;
    const flush = () => { if (token.trim()) groups.at(-1).push(fold(token.trim())); token = ''; };
    for (const char of query) {
      if (char === '"') { quoted = !quoted; }
      else if (!quoted && char === '|') { flush(); groups.push([]); }
      else if (!quoted && /\s/u.test(char)) { flush(); }
      else token += char;
    }
    if (quoted) throw new Error('精确匹配短语时，请使用成对的双引号。');
    flush();
    return groups.filter(group => group.length);
  }
  function search(pages, query) {
    const groups = parse(query);
    if (!groups.length) return [];
    const terms = [...new Set(groups.flat())];
    const matches = text => groups.some(group => group.every(term => text.includes(term)));
    return pages.flatMap(page => {
      const title = fold(page.title);
      if (!matches(title + '\n' + fold(page.content))) return [];
      const sections = page.sections.filter(section => matches(title + '\n' + fold(section.title + '\n' + section.text)));
      const score = terms.reduce((sum, term) => sum + (title.includes(term) ? 10 : 0), 0)
        + sections.reduce((sum, section) => sum + terms.filter(term => fold(section.title).includes(term)).length, 0);
      return [{ ...page, sections: sections.slice(0, 3), terms, score }];
    }).sort((a, b) => b.score - a.score || a.title.localeCompare(b.title));
  }
  function snippet(text, terms, length = 150) {
    const normalized = fold(text);
    const positions = terms.map(term => normalized.indexOf(term)).filter(i => i >= 0);
    const start = positions.length ? Math.max(0, Math.min(...positions) - 35) : 0;
    return (start ? '…' : '') + text.slice(start, start + length).replace(/\s+/g, ' ') + (text.length > start + length ? '…' : '');
  }
  const api = { parse, search, snippet };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.SiteSearch = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
