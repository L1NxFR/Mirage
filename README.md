# Mirage

An LLM serving simulator.

Implementation has not started yet.

## Structure

- `src/`: simulator code, experiments, and evaluation.
- `dashboard/site/content/`: project notes and documentation.
- `dashboard/`: local dashboard application; see [setup instructions](dashboard/README.md).

## Dashboard

Requires Node.js 22+ and Hugo.

```sh
cd dashboard
npm ci --ignore-scripts
npm run dev
```

Open the URL printed at startup (starting at port `23130`). Edits save to local Markdown files.

```sh
npm run build
npm run test:workspace
```

These commands check the dashboard. Simulator run and test commands will be added with the implementation.
