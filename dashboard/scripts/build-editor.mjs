import { build } from 'esbuild';
import { cp } from 'node:fs/promises';
// Keep the local math stylesheet and fonts in sync with the bundled renderer.
for (const asset of ['katex.min.css', 'fonts']) {
  await cp(`node_modules/katex/dist/${asset}`, `site/static/vendor/katex/${asset}`, { recursive: true });
}
await cp('node_modules/katex/LICENSE', 'site/static/vendor/katex/LICENSE');
await build({ entryPoints: ['scripts/editor/main.js'], bundle: true, minify: true,
  format: 'iife', target: 'es2022', outfile: 'site/static/js/workspace-editor.bundle.js',
  legalComments: 'linked' });
