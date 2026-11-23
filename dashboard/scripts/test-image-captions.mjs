import test from 'node:test';
import assert from 'node:assert/strict';
import { parseMarkdown } from './editor/markdown.mjs';

test('image descriptions become escaped captions and retain alt, URLs and hover titles', () => {
  const { html } = parseMarkdown('![中文图注](../Attachments/test.png "悬停提示")');
  assert.match(html, /src="\.\.\/Attachments\/test.png" alt="中文图注" title="悬停提示"/);
  assert.match(html, /<span class="image-caption">中文图注<\/span>/);
  const escaped = parseMarkdown('![<script>alert(1)</script>](image.png)').html;
  assert.doesNotMatch(escaped, /<script>/);
  assert.match(escaped, /&lt;script&gt;/);
});

test('empty images, inline images, linked images and code blocks remain valid', () => {
  assert.doesNotMatch(parseMarkdown('![](image.png)').html, /image-caption|markdown-figure/);
  const inline = parseMarkdown('Before ![Caption](image.png) after.').html;
  assert.match(inline, /^<p>Before <span/);
  assert.doesNotMatch(inline, /<figure/);
  assert.match(parseMarkdown('[![Caption](image.png)](https://example.org)').html, /<a href="https:\/\/example.org"><span/);
  assert.doesNotMatch(parseMarkdown('`![Caption](image.png)`').html, /image-caption/);
  assert.doesNotMatch(parseMarkdown('![Paper](paper.pdf)').html, /image-caption/);
});
