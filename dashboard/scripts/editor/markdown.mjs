import { Marked } from 'marked';

// Tokenize math before Markdown can consume TeX escapes, underscores, or stars.
// Code spans and ordinary code fences remain owned by Marked's code tokenizers.
function closingDelimiter(source, delimiter, from) {
  for (let i = from; i < source.length; i++) {
    if (source.startsWith(delimiter, i)) return i;
    if (source[i] === '\\') i++;
  }
  return -1;
}

function mathToken(source, block) {
  const leading = block ? source.match(/^ {0,3}/)[0].length : 0;
  const input = source.slice(leading);
  const open = ['$$', '\\[', '\\(', '$'].find(value => input.startsWith(value));
  if (!open || (block && open !== '$$' && open !== '\\[')) return;
  const close = { '$$': '$$', '\\[': '\\]', '\\(': '\\)', '$': '$' }[open];
  const end = closingDelimiter(input, close, open.length);
  if (end < 0) return;
  const text = input.slice(open.length, end);
  if (!text.trim() || (open === '$' && (/^\s|\s$/.test(text) || text.includes('\n')))) return;
  let length = leading + end + close.length;
  if (block) {
    const tail = source.slice(length).match(/^[ \t]*(?:\n|$)/);
    if (!tail) return;
    length += tail[0].length;
  }
  return { type: block ? 'blockMath' : 'inlineMath', raw: source.slice(0, length), text,
    displayMode: open === '$$' || open === '\\[' };
}

export function parseMarkdown(source) {
  const formulas = [];
  function placeholder(text, displayMode, block) {
    const index = formulas.push({ text, displayMode }) - 1;
    const tag = block ? 'div' : 'span';
    return `<${tag} data-workspace-math="${index}"></${tag}>`;
  }
  const parser = new Marked({
    extensions: [
      { name: 'blockMath', level: 'block',
        start: source => source.match(/(?:^|\n) {0,3}(?:\$\$|\\\[)/)?.index,
        tokenizer: source => mathToken(source, true),
        renderer: token => placeholder(token.text, true, true) },
      { name: 'inlineMath', level: 'inline',
        start: source => source.search(/\$|\\[([]/),
        tokenizer: source => mathToken(source, false),
        renderer: token => placeholder(token.text, token.displayMode, false) }
    ],
    renderer: {
      code(token) {
        if (token.lang?.trim() === 'math') return placeholder(token.text, true, true);
        return false;
      }
    }
  });
  return { html: parser.parse(source), formulas };
}
