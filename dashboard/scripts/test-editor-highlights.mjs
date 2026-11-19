import test from 'node:test';
import assert from 'node:assert/strict';
import { parseMarkdown } from './editor/markdown.mjs';

test('renders default and six Obsidian highlight colors with nested Markdown', () => {
  assert.match(parseMarkdown('==Default **bold** and *italic*==').html, /<mark>Default <strong>bold<\/strong> and <em>italic<\/em><\/mark>/);
  for (const [emoji, color] of Object.entries({ '🔴':'red', '🟠':'orange', '🟡':'yellow', '🟢':'green', '🔵':'blue', '🟣':'purple' })) {
    const { html } = parseMarkdown(`Before ==${emoji}**Highlighted** text== after.`);
    assert.match(html, new RegExp(`<mark data-highlight-color="${color}"><strong>Highlighted</strong> text</mark>`));
    assert.ok(!html.includes(emoji));
  }
});

test('leaves code, escaped delimiters, equations, incomplete and whitespace-padded marks literal', () => {
  const { html } = parseMarkdown('`==code==` \\==escaped== == missing end\n\n```text\n==🔴code==\n```\n\n== padded ==');
  assert.doesNotMatch(html, /<mark/);
  const formula = parseMarkdown('$a==b$ and ==$x_i$==');
  assert.deepEqual(formula.formulas.map(f => f.text), ['a==b', 'x_i']);
  assert.match(formula.html, /<mark><span data-workspace-math="1"><\/span><\/mark>/);
});

test('ignores highlight delimiters inside embedded code and keeps custom HTML for sanitization', () => {
  assert.match(parseMarkdown('==Compare `a==b` carefully==').html, /<mark>Compare <code>a==b<\/code> carefully<\/mark>/);
  assert.match(parseMarkdown('<mark style="background: #ADCCFFA6;">Blue</mark>').html, /style="background: #ADCCFFA6;"/);
});
