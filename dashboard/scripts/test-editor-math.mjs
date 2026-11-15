import test from 'node:test';
import assert from 'node:assert/strict';
import katex from 'katex';
import { parseMarkdown } from './editor/markdown.mjs';

test('preserves TeX in all supported delimiters and math fences', () => {
  const source = String.raw`Inline $a_i^2$ and \(\frac{1}{2}\).

$$
\sum_{i=1}^{n} x_i
$$

\[
\begin{pmatrix}1 & 2 \\ 3 & 4\end{pmatrix}
\]

` + '```math\nx^2 + y^2 = z^2\n```';
  const { html, formulas } = parseMarkdown(source);
  assert.equal(formulas.length, 5);
  assert.deepEqual(formulas.map(f => f.displayMode), [false, false, true, true, true]);
  assert.equal(formulas[0].text, 'a_i^2');
  assert.equal(formulas[1].text, String.raw`\frac{1}{2}`);
  assert.equal((html.match(/data-workspace-math=/g) || []).length, 5);
  for (const formula of formulas) assert.match(katex.renderToString(formula.text, formula), /class="katex"/);
});

test('leaves code and escaped dollars literal, preserves adjacent Markdown', () => {
  const { html, formulas } = parseMarkdown('`$x$` and \\$5 and **$a_i$**\n\n```js\nconst x = "$x$";\n```');
  assert.deepEqual(formulas, [{ text: 'a_i', displayMode: false }]);
  assert.match(html, /<code>\$x\$<\/code>/);
  assert.match(html, /<strong><span data-workspace-math/);
  assert.match(html, /class="language-js"/);
});

test('handles nested lists, escaped delimiters, and incomplete input', () => {
  const { formulas } = parseMarkdown(String.raw`- $a + \$b$
- \(x_1\)

Unclosed $x and \(y`);
  assert.deepEqual(formulas.map(f => f.text), [String.raw`a + \$b`, 'x_1']);
  const invalid = parseMarkdown('$\\frac{$').formulas[0];
  assert.match(katex.renderToString(invalid.text, { throwOnError: false }), /katex-error/);
  assert.doesNotMatch(katex.renderToString(String.raw`\href{javascript:alert(1)}{click}`, { trust: false }), /href=/);
});
