import { isMap, parseDocument } from 'yaml';

function summaryDocument(metadata) {
  const doc = parseDocument(metadata);
  if (doc.errors.length || !isMap(doc.contents)) {
    throw new Error('请先在文档属性中修正 YAML，再编辑内容摘要。');
  }
  const value = doc.get('tldr');
  if (value != null && typeof value !== 'string') {
    throw new Error('请先在文档属性中将 tldr 设为文本，再编辑内容摘要。');
  }
  return doc;
}

export function readSummary(metadata) {
  return summaryDocument(metadata).get('tldr') || '';
}

export function writeSummary(metadata, summary) {
  const doc = summaryDocument(metadata);
  if (summary.trim()) {
    const node = doc.createNode(summary);
    if (summary.includes('\n')) node.type = 'BLOCK_LITERAL';
    doc.set('tldr', node);
  } else {
    doc.delete('tldr');
  }
  return String(doc).trimEnd();
}
