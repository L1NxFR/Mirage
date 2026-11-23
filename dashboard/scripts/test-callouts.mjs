import test from 'node:test';
import assert from 'node:assert/strict';
import { parseMarkdown } from './editor/markdown.mjs';

test('callouts render Chinese bold text, optional titles and multiple paragraphs', () => {
  const { html, formulas } = parseMarkdown('> [!summary] 核心 **结论**\n> 中文**重点**与 $x^2$。\n>\n> - 第一项\n> - 第二项\n');
  assert.match(html, /class="research-callout"/);
  assert.match(html, /class="research-callout-title">核心 <strong>结论<\/strong>/);
  assert.match(html, /中文<strong>重点<\/strong>/);
  assert.match(html, /<li>第一项<\/li>/);
  assert.equal(formulas[0].text, 'x^2');
  assert.doesNotMatch(html, /\[!summary\]/);
});

test('plain quotes and code samples retain their original meaning', () => {
  assert.equal(parseMarkdown('> 普通 **引用**').html, '<blockquote>\n<p>普通 <strong>引用</strong></p>\n</blockquote>\n');
  const { html } = parseMarkdown('```md\n> [!summary]\n> **示例**\n```');
  assert.doesNotMatch(html, /class="research-callout"/);
  assert.match(html, /\[!summary\]/);
  assert.doesNotMatch(parseMarkdown('> [!summary]\n> 正文').html, /research-callout-title/);
});
