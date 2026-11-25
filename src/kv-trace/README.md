# AISim KV cache replay

KV trace shows how requests use GPU HBM (G1) and host DRAM (G2) during AISim
inference. Step through a replay to see which blocks hold tokens, when a
transfer occupies the link, and why a request waits for admission or prefill.

## Requirements

The capture script uses the AISim development environment at
`src/aisim/python/aisim/.venv`. Install Python 3.11–3.13, uv, and the Rust
build toolchain. Prepare AISim and the tiny-model fixture used by the
scenarios at `src/aisim/tests/e2e/configs/unified_cli/fixtures/tiny-model`.
See the [AISim development guide](../aisim/DEVELOPMENT.md) and the
[pinned source versions](../README.md#source-versions).

```sh
(cd src/aisim && uv sync --project python/aisim --extra dev --python 3.12)
```

The scenario runner and HTML renderer use the Python standard library.

## Run a replay

From the Mirage repository root, run all scenarios and open
`src/kv-trace/output/kv-cache-replay.html` in a browser.

```sh
python3 src/kv-trace/scenarios.py
```

To run only the slow device-to-host transfer scenario, or to copy the result
to the Dashboard's attachments, use:

```sh
python3 src/kv-trace/scenarios.py --only slow-d2h
python3 src/kv-trace/scenarios.py --publish dashboard/site/content/Attachments/kv-cache-replay.html
```

Each run writes a config and a Mooncake request trace, calls `aisim predict`,
and checks time to first token (TTFT), tokens reused from G2, and request
rejections against the scenario's `expect` field. A mismatch prints
`MISMATCH` and exits with status 1. The renderer embeds the results in one
offline HTML file.

Append `?scenario=<slug>` to open a scenario directly. The page hides its
header inside an iframe or when opened with `?embed` and sends
`postMessage({kvReplayHeight})` to let its parent resize the frame. The
Dashboard embeds the page with the `embed-html` shortcode.

## Scenarios

The baseline runs one vLLM worker with tensor parallelism 1, a fixed 2 ms
prefill, four tokens per 1 MB block, three G1 blocks, eight G2 blocks, and
1 GB/s transfers in each direction. Most requests have nine input tokens and
one output token. R3 continues R1 with a 12-token prompt and shares its first
two full blocks. The renderer identifies these relationships from block hashes.

| Scenario | Change from baseline | Expected observation |
| --- | --- | --- |
| `baseline` | None | TTFT is 2, 2, 4, and 2 ms. R3 reuses eight tokens from G2. |
| `g2-pressure` | Four G2 blocks and 0.05 GB/s H2D | R3 has a 42 ms TTFT. At 300 ms G2 evicts a block belonging to R2. |
| `slow-d2h` | D2H takes 125 ms to store 2 MB at 0.016 GB/s | Reusing D2H source blocks triggers fences. TTFT is 2, 29, 58, and 22.5 ms. |
| `g2-one-block` | One G2 block | A store exceeds total capacity. No tokens are reused from G2. |
| `aligned-full-hit` | Eight-token prompt and two G1 blocks | R3 reuses four tokens. The second restored block is recomputed in full. |
| `h2d-blocks-peer` | Two concurrent sequences, 0.05 GB/s H2D, and R4 arriving at 210 ms | R4 finishes before R3. R3 has a 42 ms TTFT. |
| `prompt-exceeds-g1` | Two G1 blocks | AISim rejects the request and exits with status 1, as expected for this scenario. |

Add cases to `SCENARIOS` in [scenarios.py](scenarios.py) and define their
expected results in `expect`. The page highlights each `kv` or `sched`
setting that differs from the baseline.

## How to interpret the replay

[capture.py](capture.py) uses the normal supervised AISim CLI. It passes
`PYTHONPATH` and `KV_TRACE_OUT` to the child process, where
[`sitecustomize.py`](_hook/sitecustomize.py) selects
`run_replay_with_artifacts_json`. That entry point uses the same replay loop
as `run_replay_json` and also returns `kv_events` and `host_offload_events`.

[render.py](render.py) reconstructs slot occupancy from those events and checks
the configured capacity of each tier. Three display details require inference:

1. The count of blocks being written follows the engine's admission rule:
   `token_blocks - max(reused blocks, H2D-loaded blocks)`.
2. vLLM reports G1 evictions at pass end. The replay draws an eviction at the
   admission that caused it. Evictions published after the pass's own
   `stored` event belong to later scheduling and keep their reported time.
3. A transfer bar begins at `completes_at_ms - bytes / bandwidth`. Time
   before that start represents queueing or a fence.

The artifact path supports aggregated vLLM with one data-parallel rank. These
scenarios use one output token per request and no pipeline parallelism. G2
slot positions are illustrative. The model assigns no physical addresses.
