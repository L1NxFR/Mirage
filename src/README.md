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

The sweep requires AISim's native extension and the performance tables for
the selected hardware and backend. Use the tables from the pinned AISim
revision listed below. They belong under
`src/aisim/python/aisim/src/aisim_core/systems/data/` and are distributed
separately from the source files in Mirage.

Follow the [AISim development guide](aisim/DEVELOPMENT.md) to build the
environment at `src/aisim/python/aisim/.venv`. From the Mirage repository
root, install the extension and run the sweep.

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

Mirage includes selected source files from these upstream revisions.

| Component | Upstream revision |
| --- | --- |
| AISim | [`c85b08623fc5`](https://github.com/ai-dynamo/aisim/tree/c85b08623fc5fb8c6c6600619251d7fbf775bb1f) |
| Dynamo | [`b20fe6fe9402`](https://github.com/ai-dynamo/dynamo/tree/b20fe6fe94021b854597965c7305931175e8f482) |
