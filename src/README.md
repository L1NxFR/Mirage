# Mirage

Mirage uses AISim to study how memory placement affects LLM inference. The
two-tier DRAM model estimates decode latency when KV cache entries and expert
weights share a fast memory tier backed by a larger, slower tier.

## Source layout

| Directory | What it contains |
| --- | --- |
| [aisim](aisim/README.md) | NVIDIA's offline LLM serving simulator. Mirage uses its prediction engine and replay events. |
| [two-tier-dram](two-tier-dram/README.md) | An AISim extension that models fast-tier capacity, transfers between tiers, and their effect on decode latency. |
| [dynamo](dynamo/README.md) | NVIDIA's distributed inference framework, included as a serving-system reference. |
| [kv-trace](kv-trace/README.md) | A replay tool that renders AISim's KV cache events as an offline HTML timeline. |

## Run the two-tier DRAM model

The upstream directories in this branch are source references. Performance
tables, benchmark datasets, workload traces, and media assets are excluded.
For the full sweep, use the prepared AISim environment and performance tables
on i163v. Run these commands there from the Mirage repository root.

```bash
uv pip install --python src/aisim/python/aisim/.venv/bin/python -e src/two-tier-dram
python3 src/two-tier-dram/scenarios.py
```

The sweep writes its results to `src/two-tier-dram/output/sweep.md` and
`sweep.json`. Open `two-tier-dram-replay.html` in the same directory to inspect
the replay.

## Test the model

The model tests use a synthetic workload and run with Python 3.11 or later.

```bash
(cd src/two-tier-dram && python3 -m unittest discover -s tests -p test_model.py)
```

After installing AISim and the extension, run the full suite, including the
integration tests.

```bash
(cd src/two-tier-dram && ../aisim/python/aisim/.venv/bin/python -m unittest discover -s tests -v)
```

## Source versions

The AISim and Dynamo source files are selected from the pinned revisions below.
The versions
below come from the `two-tier-dram-replay` checkout on `i163v`, at Mirage
commit `47622cc09bdf2abfeb7e447d6bc93dcb74512df4`.

| Component | Pinned revision | Source on i163v |
| --- | --- | --- |
| AISim | [c85b08623fc5fb8c6c6600619251d7fbf775bb1f](https://github.com/ai-dynamo/aisim/tree/c85b08623fc5fb8c6c6600619251d7fbf775bb1f) | Clean checkout at this commit. |
| Dynamo | [b20fe6fe94021b854597965c7305931175e8f482](https://github.com/ai-dynamo/dynamo/tree/b20fe6fe94021b854597965c7305931175e8f482) | The server records this commit. Its source directory was empty, so the files come from the pinned upstream revision. |
| Two-tier DRAM | `b4432aa2210d60bc0657efe8e635cdcd751e04ae` (Git tree) | Matches the tracked files in the server checkout. |

KV trace is an additional tool from this Mirage worktree.
