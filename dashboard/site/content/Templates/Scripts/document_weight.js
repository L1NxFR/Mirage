/** Assign the next sibling weight when Templater creates a journal document. */
module.exports = async function documentWeight(tp) {
  const target = tp.config.target_file;
  if (target.basename === '_index' || target.basename.endsWith('.excalidraw') || !['related-work','research-journey','system-implementation','meetings'].includes(target.path.split('/')[0])) return '';
  const peers = [];
  for (const file of target.parent.children) {
    if (file === target || file.extension !== 'md' || file.basename === '_index' || file.basename.endsWith('.excalidraw')) continue;
    const source = await tp.app.vault.read(file);
    const match = source.match(/^---\r?\n(?:([\s\S]*?)\r?\n)?---(?:\r?\n|$)/);
    if (!match && source.startsWith('---')) throw new Error(`Invalid YAML metadata: ${file.path}`);
    const metadata = match ? tp.obsidian.parseYaml(match[1] || '') || {} : {};
    if (typeof metadata !== 'object' || Array.isArray(metadata)) throw new Error(`Invalid YAML metadata: ${file.path}`);
    if (Object.hasOwn(metadata, 'weight') && !Number.isSafeInteger(metadata.weight)) throw new Error(`weight must be a safe integer: ${file.path}`);
    peers.push({ file, source, metadata, hasMetadata: Boolean(match) });
  }
  const weights = peers.map(peer => peer.metadata.weight).filter(Number.isSafeInteger);
  let next = weights.length ? Math.max(...weights) + 1 : 1;
  const missing = peers.filter(peer => peer.metadata.weight === undefined).sort((a,b) =>
    String(a.metadata.title || a.file.basename).localeCompare(String(b.metadata.title || b.file.basename)));
  if (!Number.isSafeInteger(next + missing.length)) throw new Error('No integer weight remains after the last document.');
  for (const peer of missing) {
    const newline = peer.source.includes('\r\n') ? '\r\n' : '\n';
    const line = `weight: ${next++}${newline}`;
    const offset = peer.source.indexOf('\n') + 1;
    const source = peer.hasMetadata ? peer.source.slice(0, offset) + line + peer.source.slice(offset) : `---${newline}${line}---${newline}${peer.source}`;
    await tp.app.vault.modify(peer.file, source);
  }
  return `weight: ${next}`;
};
