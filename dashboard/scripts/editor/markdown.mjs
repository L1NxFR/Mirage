import { Marked, Renderer } from 'marked';

const highlightColors = { '🔴':'red', '🟠':'orange', '🟡':'yellow', '🟢':'green', '🔵':'blue', '🟣':'purple' };

function highlightToken(source) {
  if (!source.startsWith('==') || source[2] === '=' || !source[2] || /\s/.test(source[2])) return;
  for (let i = 2; i < source.length; i++) {
    // Embedded code and math may contain equality operators of their own.
    const math = mathToken(source.slice(i), false);
    if (math) { i += math.raw.length - 1; continue; }
    if (source[i] === '\\') { i++; continue; }
    if (source[i] === '`') {
      const run = source.slice(i).match(/^`+/)[0];
      const end = source.indexOf(run, i + run.length);
      if (end !== -1) { i = end + run.length - 1; continue; }
    }
    if (source.startsWith('==', i) && source[i + 2] !== '=' && !/\s/.test(source[i - 1])) {
      let text = source.slice(2, i), color;
      for (const [emoji, name] of Object.entries(highlightColors)) {
        if (text.startsWith(emoji)) { color = name; text = text.slice(emoji.length).replace(/^\uFE0F/, ''); break; }
      }
      return { type: 'highlight', raw: source.slice(0, i + 2), color, tokens: this.lexer.inlineTokens(text) };
    }
  }
}

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
      { name: 'highlight', level: 'inline', start: source => source.indexOf('=='), tokenizer: highlightToken,
        renderer(token) {
          return `<mark${token.color ? ` data-highlight-color="${token.color}"` : ''}>${this.parser.parseInline(token.tokens)}</mark>`;
        } },
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
      image(token) {
        // Reuse Marked's URL handling and escaping for both alt and caption.
        const image = Renderer.prototype.image.call(this, token);
        const caption = image.match(/ alt="([^"]*)"/)?.[1].trim();
        if (!caption || /\.pdf(?:[?#]|$)/i.test(token.href)) return image;
        return `<span class="markdown-figure" role="figure">${image}<span class="image-caption">${caption}</span></span>`;
      },
      blockquote(token) {
        const match = token.text.match(/^\[!([a-z]+)\](?:[+-])?(?:[ \t]+([^\n]*))?(?:\n|$)/i);
        if (!match) return false;
        const title = match[2]?.trim();
        return `<blockquote class="research-callout">${title ? `<p class="research-callout-title">${parser.parseInline(title)}</p>` : ''}${parser.parse(token.text.slice(match[0].length))}</blockquote>\n`;
      },
      code(token) {
        if (token.lang?.trim() === 'math') return placeholder(token.text, true, true);
        return false;
      }
    }
  });
  return { html: parser.parse(source), formulas };
}
