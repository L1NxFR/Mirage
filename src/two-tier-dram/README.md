# Two-tier DRAM decode model for AISim

This out-of-tree extension models prefetching and hot KV caching across two memory tiers. AISim loads the `two_tier_dram` stack and configuration section through Python entry points.

```sh
aisim predict --stack two_tier_dram --config CONFIG.yaml --output-dir OUT
```

## Development release 0.1.0.dev1

This release records the research prototype at `9c92314`. Hardware calibration and three correctness fixes remain open.

- With `expert_cache: per_layer` and `expert_prefetch: last_step`, unused predicted experts can remain in tier 1. This changes the intended baseline with no cross-step caching.
- When the cache can hold only one layer's experts, prefetches can fill all slots with entries protected from eviction. A subsequent demand read can fail the capacity check.
- The tier 2 capacity check counts the initial KV cache. It does not account for KV growth during decode.

Repeat the prefetch comparison after correcting the cache behavior described above.

## Hardware inputs

All reported results are simulations. Four assumptions limit their interpretation as estimates for EXI-3DDRAM hardware. The official DeepSeek-V4-Pro weights occupy 806.6 GB, exceeding even the 512 GB upper bound considered for a single card. Counterfactual runs continue with an infeasibility flag. The model also uses synthetic cross-step overlap for routed experts and top-k KV entries, assumed copy efficiency and transfer overhead, and an uncalibrated AISim roofline for compute.

Specify quantities with units, for example `"36 GB"`, `"2.2 TB/s"`, or `"10 us"`. The configuration parser converts them to bytes, bytes per second, and seconds. One GB is 10⁹ bytes, one GiB is 2³⁰ bytes, and one Tb/s is 1.25 × 10¹¹ bytes/s. The replay distinguishes preset inputs from assumptions and scenario overrides.

| Parameter | `exi_figure` preset | Interpretation |
| --- | --- | --- |
| Tier 1 capacity (`tier1_capacity`) | 36 GB | Reference capacity |
| Tier 1 read bandwidth for compute (`tier1_bandwidth`) | 18 TB/s | Reference read bandwidth (zHBM / 3D DRAM) |
| Tier 2 capacity (`tier2_capacity`) | 128 GB | Reference capacity, with a range of 64–512 GB |
| Nominal tier 2 bandwidth (`tier2_bandwidth`) | 2.2 TB/s | Upper end of the 1.1–2.2 TB/s range for LPDDR6 |
| Copy efficiency (`copy_efficiency`) | 1.0 | Assumes an ideal copy |
| Fixed overhead per transfer (`transfer_overhead`) | 0 s | Idealized assumption |
| Inter-card bandwidth (`interconnect_bandwidth`) | 1.6 TB/s, both directions combined | Unconfirmed and unused at TP1 |
| Scratch space (`scratch`) | 4 GB | Assumed allowance for activations and temporary storage |

Tier 1 read bandwidth determines compute time through `mem_bw` in `systems/exi_3ddram.yaml`. It also sets the upper bound on tier 1 contention. All transfers share a single link with an effective copy bandwidth equal to the nominal tier 2 bandwidth multiplied by copy efficiency. The single-card model records inter-card bandwidth for reference.

Two other presets support comparisons.

- `exi_96gb_explore` changes tier 1 capacity from 36 GB to 96 GB while keeping the other reference parameters.
- `legacy_64gbps` reproduces the assumptions in `e86bfad` for historical comparison. It uses a 96 GB tier 1, a fictitious 2048 GB tier 2 to fit the 1579 GB model, a 64 GB/s link, 10 µs per transfer, and B200 compute times. Its hardware assumptions have been withdrawn.

Effective copy bandwidth, internal interconnect limits, and fixed transfer overhead remain uncalibrated. BF16, INT8, and FP32 throughput and direct compute access to tier 2 are also unspecified. The system specification records FP4 at 6.13 PFLOP/s and FP8 at 2.95 PFLOP/s. Neither peak constrains the batch-one decode workload below.

## Compute baselines

| Baseline | Timing model |
| --- | --- |
| EXI-SOL | AISim uses `systems/exi_3ddram.yaml` with 18 TB/s tier 1 read bandwidth, the FP8 and FP4 peaks above, and assumptions labeled in the file. Each operator takes the larger of operations / peak throughput and bytes / bandwidth. All operators in this batch-one decode workload are bandwidth-bound, so the roofline gives a speedup of 18 / 7.7 = 2.34 over B200. This estimate has no hardware calibration. |
| B200 hybrid | AISim's `b200_sxm` compute timings are paired with the EXI memory assumptions. The runner labels this combination as a hybrid experiment. |

`runner.compute_basis` checks the `mem_bw` used by AISim against the configured `tier1_bandwidth`. A difference greater than 1% marks the experiment as hybrid.

## Models and workload

| Model | Expert quantization | Total weights | Routed experts | Non-expert weights |
| --- | --- | ---: | ---: | ---: |
| `deepseek-ai/DeepSeek-V4-Pro` (official, primary workload) | w4a8 mxfp4 | 806.6 GB | 774 GB | 32 GB |
| `nvidia/DeepSeek-V4-Pro-NVFP4` | nvfp4 | 902 GB | 870 GB | 32 GB |
| `sgl-project/DeepSeek-V4-Pro-FP8` (previous workload) | fp8_block | 1579 GB | 1547 GB | 32 GB |

One scale byte per 32 mxfp4 values gives 4.25 bits per weight. For example, 720 GB of packed 4-bit expert weights would occupy approximately 765 GB with this scaling overhead, compared with AISim's estimate of 774 GB. The earlier FP8 workload roughly doubled expert storage.

Even the official model exceeds both the 128 GB default and the 512 GB maximum tier 2 capacity of one EXI card. The model has no multi-card sharding. The default `tier2_capacity_check: enforce` reports an infeasible run and stops. The `counterfactual` setting continues and marks every result infeasible.

With 4 GB reserved for scratch space, the 36 GB tier 1 cannot hold all the approximately 32 GB of non-expert weights. The 36 GB reference configuration therefore uses `base_weights: layer_rotation`. The 96 GB configuration can keep those weights resident.

## Policies

| Field | Behavior |
| --- | --- |
| `base_weights` | `resident` keeps all non-expert weights in tier 1. `layer_rotation` keeps the current layer and prefetches the next. |
| `expert_cache` | `lru` retains experts across steps with least-recently-used eviction. `per_layer` releases experts at layer completion. See the prefetch limitation above. |
| `expert_prefetch` | `none` disables prefetching. `last_step` prefetches missing experts that the next layer used in the preceding step. |
| `hot_kv_entries` | Maximum number of top-k KV entries in the LRU cache. Zero discards entries after use. |
| `expert_overlap`, `topk_overlap` | Synthetic overlap between selections at successive steps. |
| `link_policy` | `demand_first` lets demand reads preempt prefetches and writebacks. `fifo` serves transfers in arrival order. |

Each (layer, expert) pair occupies one slot. The cache fills before it evicts any entry. Once full, it replaces entries in LRU order and stays within its capacity. In-flight experts and experts in use by the current layer are protected. A prefetch that has arrived but has not yet been used can be evicted. The replay shows occupancy, capacity, cumulative evictions, and the current step's hit rate so that replacement remains visible at constant occupancy. The cache rules are covered in `tests/test_model.py`.

## Outputs

`trace.json` records hardware inputs and how they were configured, the compute baseline, feasibility, aggregate metrics, and per-step statistics. Each step reports compute and wait times, bytes transferred by type, link utilization, expert and KV hit rates, evictions, cache occupancy, and tier 1 usage. With `trace_detail: full`, the trace also includes events and snapshots at event boundaries.

Step 1 is the cold start. Subsequent steps are labeled as filling until the first eviction and evicting afterward for the cross-step cache. The model reports a steady-state value only if the last six steps are past filling and vary by at most 5%. The remaining cases report that steady state was not reached.

Copies write to tier 1 while compute reads from it. The simulated latency excludes contention between these operations. The field `tier1_contention_bound_ms` estimates the upper bound as overlap time × effective copy bandwidth / tier 1 bandwidth.

## Run the experiments

Use an AISim development environment with the matching performance tables. From the Mirage repository root, install the extension and run the sweep.

```sh
uv pip install --python src/aisim/python/aisim/.venv/bin/python -e src/two-tier-dram
python3 src/two-tier-dram/scenarios.py
```

Each scenario runs one AISim prediction. The sweep writes `output/sweep.md`, `output/sweep.json`, and `output/two-tier-dram-replay.html` under this component. The sweep checks that increasing bandwidth does not increase latency, increasing overhead does not reduce latency, a sufficiently fast link approaches native AISim timing, the legacy configuration reproduces its earlier values, and infeasible configurations are reported.

Run the full test suite in the same environment.

```sh
cd src/two-tier-dram
../aisim/python/aisim/.venv/bin/python -m unittest discover -s tests -v
```

The suite includes 28 standalone model tests and seven AISim integration tests. Model tests cover units, link timing, capacity failures, cache growth and eviction, eviction protection, and steady-state detection.

## Simulation results

The main sweep used the official DeepSeek-V4-Pro model with a 200K-token context, one request, and 32 decode steps. Expert overlap was 0.5 and top-k overlap was 0.75 by default. These are counterfactual single-card comparisons. The legacy row uses its original FP8 workload and fictitious tier 2 capacity.

| Configuration | Cold start (ms) | After cache fill (ms/token) | Compute (ms) | Wait for non-expert weights (ms) | Wait for experts (ms) | GB transferred/token | Link utilization |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 36 GB, ideal 2.2 TB/s | 18.5 | 15.6 (steady) | 2.13 | 10.8 | 2.7 | 34.3 | 100% |
| 36 GB, ideal 1.1 TB/s | 36.9 | 31.2 (steady) | 2.13 | 23.7 | 5.4 | 34.3 | 100% |
| 36 GB, 2.2 TB/s × 0.7 assumed efficiency | 26.4 | 22.3 (steady) | 2.13 | 16.3 | 3.8 | 34.3 | 100% |
| 96 GB, ideal 2.2 TB/s | 7.6 | 4.7 (13% variation, unsteady) | 2.13 | 0 | 2.5 | 5.6 | 54% |
| 96 GB, ideal 1.1 TB/s | 13.1 | 7.2 (16% variation, unsteady) | 2.13 | 0 | 5.1 | 5.6 | 70% |
| Legacy 64 GB/s assumption (withdrawn) | 385.5 | 183.3 | 6.54 | 0 | 176.4 | 11.3 | 96% |

The generated `output/sweep.md` includes comparisons of transfer overhead, prefetching, cache policies, hot KV, cross-step overlap, and compute baselines.

1. **At 36 GB, the link limits decode.** The 15.57 ms token time matches the 15.59 ms implied by bytes transferred / effective bandwidth. Halving bandwidth doubles token time. Rotating non-expert weights accounts for 28.1 GB (82%) of traffic per token and routed experts account for 6.3 GB.
2. **At 96 GB, non-expert weights stay resident.** Experts account for approximately 5.6 GB/token. Fetching experts after routing serializes fetching and compute. Token time is about 2.13 ms of compute plus 2.54 ms of expert transfer, leaving the link busy 54% of the time.
3. **Cross-step LRU reuse reduces token time.** Releasing experts after each layer increases token time from 15.6 to 18.4 ms at 36 GB and from 4.7 to 7.6 ms at 96 GB.
4. **Hot top-k KV has little effect in this workload.** Toggling it changes token time by at most 0.01 ms. KV traffic is only a few MB/token, but each CSA layer issues one KV transfer. With a 10 µs fixed overhead, these transfers contribute 0.3 ms/token.
5. **Previous-step expert prefetch showed no gain in these configurations.** With LRU, last step's experts were still cached and the prefetcher issued zero requests. Without cross-step caching, the 36 GB result rose from 18.4 to 21.0 ms. At roughly 50% accuracy, prefetch increased expert traffic by 44%. A layer took 0.035 ms to compute while fetching six experts took 0.09 ms, so most prefetches arrived late. The prefetch limitations above warrant repeating this comparison after the fixes.
6. **Fixed overhead scales with transfer count.** Each token required about 153 transfers at 36 GB and 92 at 96 GB. A 10 µs overhead added about 1.5 and 0.9 ms/token, respectively. A 100 µs overhead added about 15 and 9 ms/token.
7. **The compute baseline matters more at 96 GB.** B200 and EXI-SOL times differed by 0.1 ms at the link-bound 36 GB setting and by 2.9 ms at 96 GB (7.56 vs. 4.67 ms).
8. **Tier 1 contention has a separate upper bound.** At 36 GB, the effective copy bandwidth is 12% of tier 1 bandwidth, giving at most about 0.26 ms/token of additional compute time during overlaps. The table excludes this bound.

## Files

| Path | Purpose |
| --- | --- |
| `two_tier_dram/config.py` | Unit conversion, hardware presets, policies, and model profile types |
| `two_tier_dram/model.py` | Memory accounting, link scheduling, per-layer state machine, per-step statistics, and steady-state detection |
| `two_tier_dram/profile.py` | Reads model geometry, byte counts, per-operator latency, and compute-side tier 1 bandwidth from AISim |
| `two_tier_dram/runner.py`, `two_tier_dram/adapter.py` | AISim stack and configuration section |
| `two_tier_dram/render.py`, `two_tier_dram/template.html` | Replay page |
| `systems/exi_3ddram.yaml` | AISim system specification for EXI-3DDRAM used to price operators |
| `scenarios.py` | Scenario catalog, consistency checks, comparison table, and replay generation |

## Modeling limits

- The simulation is open loop. Two-tier stalls do not feed back into AISim scheduling. Requests must decode without overlap, and each request starts with a cold cache.
- The model covers one card at TP1 and EP1. The 36 GB reference configuration cannot fit this workload on one card. Multi-card sharding is unimplemented.
- Per-layer compute time divides AISim's aggregate operator latency evenly across the layers.
- Link timing uses bandwidth and fixed overhead. Effective bandwidth does not vary with access size. Tier 1 contention between copy and compute has an upper bound only.
- A preempted transfer pays its fixed overhead once, including when it resumes.
