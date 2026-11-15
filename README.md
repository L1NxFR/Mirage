# Research Project Template

A template for research and engineering projects. Use `dashboard/` to guide the project and track decisions and evidence. Put implementations, experiments, and evaluation code in `src/`.

The dashboard is ready for local editing. `src/` is empty; choose a stack when the project needs one.

## Project map

| Location | Purpose |
| --- | --- |
| [Overview](dashboard/site/content/_index.md) | Goals, scope, success criteria, progress, and next steps |
| [Related](dashboard/site/content/related-work/) | Prior work and comparisons |
| [Journey](dashboard/site/content/research-journey/) | Experiments, findings, and open questions |
| [System](dashboard/site/content/system-implementation/) | Architecture, implementation, and decisions |
| [Meetings](dashboard/site/content/meetings/) | Discussions, decisions, and action items |
| [src/](src/) | Implementation and evaluation code |
| [AGENTS.md](AGENTS.md) | Agent working rules |
| [Dashboard guide](dashboard/README.md) | Editing, building, and publishing |

Keep changing goals and status in the dashboard. Keep setup instructions and stable links in README files.

Write in concise English by default. Agents edit user documents only when requested. Agent-created dashboard notes use `agent-` in filenames and `[Agent]` in titles, such as `agent-evaluation-plan.md` and `[Agent] Evaluation Plan`. Agents maintain these notes as work progresses, preserving user contributions.

## Start a project

1. Replace this title and introduction with the project's purpose and deliverables.
2. Fill in Overview: goals, non-goals, constraints, success criteria, and the next task.
3. Update `dashboard/site/hugo.yaml`: title, description, author, repository URL, and footer.
4. Record the initial approach and validation plan in System.
5. Add components under `src/`. Each runnable component needs a README with dependencies, inputs, outputs, and run and test commands.

Group code by component. Keep tests, scripts, and configuration with their component. Add shared code only when needed. Store large datasets, models, and logs separately; record their versions and locations in the dashboard.

### Repository setup

Git tracks the whole project from this root directory on the `main` branch. The private repository is [Research-Project-Template](https://github.com/Languisher/Research-Project-Template).

The optional deployment workflow is at `dashboard/.github/workflows/deploy.yml`. GitHub Actions does not run workflows in this nested location. To enable deployment later, move it to the root `.github/workflows/` and update its working directories and Hugo theme paths.

## Run the dashboard

Requires Node.js 22+ and Hugo. The existing deployment workflow uses Hugo 0.168.0.

From the project root:

```sh
cd dashboard
npm ci --ignore-scripts
npm run dev
```

Open <http://localhost:1313/>. Edits save to local Markdown files. You can also open `dashboard/site/content/` as an Obsidian vault.

Run these commands from `dashboard/`:

| Command | Purpose |
| --- | --- |
| `npm run dev` | Preview and edit locally |
| `npm run build` | Build the site into `site/public/` |
| `npm run test:workspace` | Check workspace and editor behavior |

Pages default to drafts; set `draft: false` to publish. Attachments and exported Excalidraw SVGs enter the build even when only drafts reference them.

Project code has no run or test commands yet. Add them to component READMEs as implementations are introduced.

## Workflow

1. **Plan:** define the task and acceptance criteria.
2. **Implement:** make the change in the relevant component.
3. **Verify:** run relevant checks and record results and limits.
4. **Record:** add findings to Journey and design changes to System. Agents maintain labeled notes and propose Overview updates in a companion note unless asked to edit it directly.

A task is complete when its deliverable exists, acceptance criteria are verified, and relevant records are current. Mark skipped checks explicitly. Minor edits do not need a separate journal entry.

When adapting this template, remove completed setup notes and keep only the instructions the project uses.
