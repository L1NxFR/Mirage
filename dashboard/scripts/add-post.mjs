import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import { createInterface } from 'node:readline';
import { createStore } from './workspace-store.mjs';
import { checkDelivery } from './check-delivery.mjs';

const categories = ['related-work', 'meetings', 'research-journey', 'system-implementation', 'other'];
const labels = ['Related work', '归档', 'Research', 'Experiments', 'Other'];

export async function addPost({ args, root, input = process.stdin, output = process.stdout }) {
  if (args.length === 1 && ['--help', '-h'].includes(args[0])) {
    output.write('Usage: pnpm run add --target-root /absolute/project "post_name"\n');
    return;
  }
  if (args.length !== 1 || !args[0].trim()) throw new Error('Usage: pnpm run add --target-root /absolute/project "post_name" (quote titles containing spaces).');
  const title = args[0].replace(/\.md$/i, '').trim();
  if (!title || title.length > 180 || /[\\/\u0000-\u001f]/.test(title) || title.startsWith('.')) {
    throw new Error('Use a title of 1–180 characters without path separators or control characters.');
  }
  output.write('Choose a category:\n' + categories.map((name, i) => `  ${i + 1}. ${name} (${labels[i]})`).join('\n') + '\n');
  const reader = createInterface({ input, output, terminal: Boolean(input.isTTY && output.isTTY) });
  const lines = reader[Symbol.asyncIterator]();
  try {
    for (;;) {
      output.write('Category [1-5 or directory name; q to cancel]: ');
      const { value, done } = await lines.next();
      if (done || value.trim().toLowerCase() === 'q') { output.write('Cancelled.\n'); return; }
      const choice = value.trim();
      const category = /^[1-5]$/.test(choice) ? categories[Number(choice) - 1] : categories.find(name => name === choice);
      if (!category) { output.write('Invalid category. Try again.\n'); continue; }
      const document = await createStore(root).create({ kind: 'document', parent: category, title });
      output.write(`Created: ${path.join(root, document.path)}\n`);
      return document;
    }
  } finally { reader.close(); }
}

if (process.argv[1] && fs.realpathSync(process.argv[1]) === fs.realpathSync(fileURLToPath(import.meta.url))) {
  try {
    const args = process.argv.slice(2);
    const index = args.indexOf('--target-root');
    let targetRoot = process.env.DELIVERY_ROOT;
    if (index !== -1) {
      targetRoot = args[index + 1];
      args.splice(index, 2);
    }
    if (!(args.length === 1 && ['--help', '-h'].includes(args[0]))) {
      await checkDelivery({ targetRoot, operationRoot: fileURLToPath(new URL('../', import.meta.url)) });
    }
    await addPost({ args, root: fileURLToPath(new URL('../site/content/', import.meta.url)) });
  } catch (error) {
    const messages = { 409: 'A document or folder with this name already exists.', 422: 'Invalid post title or document metadata.', 403: 'The selected path is not editable.', 404: 'The category directory does not exist.' };
    console.error(messages[error.status] || error.message);
    process.exitCode = 1;
  }
}
