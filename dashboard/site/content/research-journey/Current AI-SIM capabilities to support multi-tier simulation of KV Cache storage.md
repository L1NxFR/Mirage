---
weight: 1
content_lang: en
title: Current AI-SIM capabilities to support multi-tier simulation of KV Cache storage
date: 2026-11-15
lastmod: 2026-11-16
draft: false
show_toc: true
description: "Technical Research Report: architecture, mechanisms, and extension requirements for multi-tier KV-cache simulation."
subtitle: Weekly Report
tldr: |
  AISim implements GPU–host KV-cache offloading, a deployment-wide shared host pool, and restricted storage-tier replay. These mechanisms provide a baseline for studying capacity, bandwidth, and scheduling under agentic workloads. Expert offloading, direct execution from a slower tier, and unified contention across transfer paths require additional models; runtime correctness and hardware accuracy remain unverified in this report.
---


| Case 1 capability                            | Existing implementation                                                                                          | Limitations                                                                                                                                 |
| -------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| **Multi-worker agentic workload**            | AgentX/Weka replay supports multiple workers and prefix reuse within conversations.                              |                                                                                                                                             |
| **Siloed KV-cache baseline**                 | Each worker has private G1; `dp_rank_local` provides private G2.                                                 |                                                                                                                                             |
| **Shared DDR-cache pool**                    | `cluster_shared` lets workers share G2 residency, capacity, and pool bandwidth while keeping HBM private.        | Models a logical shared pool, rather than the full behavior of a specific shared-memory device or distributed-storage protocol.             |
| **Cache lookup and eviction**                | Tracks complete prefix blocks, G1/G2 residency, capacity, store/load states, and eviction.                       |                                                                                                                                             |
| **Cache-locality and load-aware routing**    | The Dynamo adapter can integrate the KV Router; AISim exposes placement and cache-event interfaces.              |                                                                                                                                             |
| **Peer DDR retrieval under agentic traffic** | KVCR can fetch KV from peer G2 into local G2, then restore it to the destination GPU.                            | Current agentic traffic does not supply source hints, so peer pulls are not triggered. Source selection and hint propagation must be added. |
| **KV-transfer latency and contention**       | Models first-byte latency, H2D/D2H bandwidth, shared-pool bandwidth contention, and KVCR source-side contention. | Lacks a complete model of destination NIC constraints, network topology, and shared-resource contention across transfer paths.              |
| **Worker queueing and execution**            | Models worker scheduling, batching, prefill/decode, and waiting for KV restoration.                              |                                                                                                                                             |

## Research objective



Mirage studies how memory capacity, transfer bandwidth, and scheduling affect LLM serving under agentic workloads. The [November 13 meeting](../../meetings/2026-11-13-weekly-meeting/) defines two configurations: **Case 1**, KV-cache sharing across workers; and **Case 2**, single-GPU two-level memory, starting with KV offloading and then MoE expert offloading. Case 2 remains the first implementation target.

The existing G1/G2 path provides the storage-offloading baseline for Case 2: reusable KV resides in host memory between uses and returns to GPU memory before execution. Executing attention directly against a slower memory tier is a different capability, not represented by this restore path. [A3]

Unless stated otherwise, implementation findings below are based on static source analysis. Test assertions specify expected behavior but have not been reproduced here. There are no locally verified runtime or GPU-performance results. Proposed extensions and performance hypotheses are identified separately; reproducibility details are in the Appendix.

## System architecture and state ownership

AISim separates request replay, engine behavior, and forward-pass timing. Replay owns virtual time and worker composition; the engine owns scheduling and cache state; the performance model supplies compute-time estimates. Offload transfers advance on the simulation clock without moving tensors. [A16] [A2]

| Component | State and responsibility | Interface relevant to multi-tier modeling |
| --- | --- | --- |
| Replay deployment | Worker topology, placement, virtual-time progression | Creates deployment-scoped tier registries and connects them to engines [A14] |
| vLLM host adapter | Per-request prefix lookup, destination reservations, admission dependencies | `start_load`, `advance`, `on_admitted`, and request completion/cancellation [A3] |
| `HostTier` | G2 block residency, pending transfers, pins, eviction order | Store/load submission, completion, and residency events [A2] |
| `G2Registry` | One shared pool and its participant contract | `join` checks layout, capacity, and shared bandwidth agreement [A4] |
| Transfer service | Bytes remaining, readiness times, directional link budgets | FIFO service for private G2; fair sharing for shared pools [A2] [A5] |
| Dynamo integration | Engine adaptation and routing-facing observations | Wraps an AISim core; real KVBM transfer execution remains a separate subsystem [D1] [D2] [D3] |

A G2 block is identified by a sequence hash. Residency belongs to the tier; routing information is a derived view of that residency. A placement decision therefore cannot guarantee that the block will still be available at admission. The adapter rechecks availability, and its load path releases a G1 reservation if the host lookup no longer succeeds. [A2] [A3]

### Admission and transfer invariants

| Invariant | Enforcement in the existing implementation |
| --- | --- |
| A queued store is not yet a resident block | `HostTier::finish` changes `PendingStore` to `Resident` at D2H completion [A2] |
| A host hit cannot exceed available G1 destination capacity | `start_load` reserves G1 blocks before scheduling H2D and returns `CapacityBlocked` if reservation fails [A3] |
| In-flight copies cannot be treated as completed reuse | Load state and source dependencies delay admission or reuse until the required completion [A3] |
| Shared capacity is counted once | Participants join the same tier under an equal pool contract [A4] |
| Equal-time transfer events have a defined order | `HostTier::advance` applies stores before loads, then orders by transfer ID [A2] |

These are code-enforced simulation rules. Their end-to-end correctness still requires the tests in the validation section.

## Existing implementation mechanisms

### G1/G2 storage and restoration

The vLLM adapter observes completed blocks and offers eligible blocks for host storage according to the selected connector profile. A later request looks up its reusable prefix. If restoration is possible, `start_load` reserves GPU destinations, waits for conflicting source-copy dependencies, and submits H2D work. Completion activates the loaded prefix for admission. Concurrent transfers or insufficient GPU capacity can defer the request. [A3]

Host capacity increases the amount of reusable KV retained between requests; it does not remove the requirement to fit restored blocks in G1. Restoration reduces recomputation only when its transfer and admission costs are preferable to recomputing the missing prefix. That performance trade-off is a hypothesis to measure, not an established speedup. [A3] [A9]

Connector profiles encode different policies. `offloading_v0_24` primarily stores prompt blocks, while `simple_cpu_v0_32` also stores decode blocks and uses different eviction and preemption behavior. The documented v0.32 deviations include recomputation of output blocks after preemption in the simple-CPU model. Consequently, connector choice must remain fixed within a policy comparison. The upstream documentation reports no running-vLLM comparison for these profiles. [A13]

### Capacity and bandwidth model

For a block of (b) tokens and (q) KV bytes per token, the model uses:

\[
S_{\mathrm{block}} = bq, \qquad C_{\mathrm{G2}} = N_{\mathrm{blocks}}bq.
\]

`HostClient::new` computes this geometry. Capacity and transfer bytes use the per-shard KV representation; a tensor-parallel multiplier must not be added implicitly. [A4] [A13]

For private G2, `HostTier::submit` and `FifoLane::submit` give the following completion rule for positive bandwidth:

\[
t_{\mathrm{done}} = \max(t_{\mathrm{lane}},\ t_{\mathrm{eligible}} + L)
+ \frac{S}{10^6 B}.
\]

Here, time is in milliseconds, (S) is bytes, (B) is decimal GB/s, and (L) is first-byte latency. H2D and D2H have separate lanes. A configured bandwidth of zero means unlimited service. Shared G2 instead recalculates max-min fair rates under both per-client and aggregate directional caps. [A2] [A5]

The supplied single-worker fixture uses four-token blocks and 250,000 bytes per token: 1 MB per block, 3 MB of G1 KV capacity, and 8 MB of G2 capacity. Its expected eight-token restoration moves 2 MB, whose isolated service time is 2 ms at 1 GB/s or 200 ms at 0.01 GB/s. These are arithmetic consequences of fixture parameters, not measured TTFT values; queueing and dependencies add delay. [A15] [A9]

The model abstracts bandwidth and latency. It does not establish PCIe transaction behavior, NUMA/CXL topology, or contention between independent transfer subsystems. `FairTransfers` explicitly leaves budgets with its callers. Reusing this class in two paths does not make them share a physical link. [A5]

### Shared G2 and peer-cache retrieval

`cluster_shared` supplies one deployment-wide host pool. Its contract includes KV layout, tensor-parallel size, block geometry, capacity, and shared bandwidth. Incompatible participants are rejected. This supports Case 1 as a shared-capacity and contention model, with one authoritative residency state. [A4]

KVCR instead connects private G2 caches. A source hint identifies where a missing prefix may reside; the registry tracks source availability, pins, transfer progress, and delivery into the target G2. H2D restoration then brings those blocks into G1. Tests specify source-bandwidth sharing and waits for an active source pass. The documented AgentX path provides no such hints, so enabling KVCR there does not produce remote pulls. [A7] [A11] [A13]

For comparisons across (N) private ranks, total host capacity is (N C_{\mathrm{private}}); shared capacity is (C_{\mathrm{shared}}), counted once. Equal-capacity comparisons require (C_{\mathrm{shared}}=N C_{\mathrm{private}}), with aggregate bandwidth controlled separately. Otherwise resource increases confound the effect of sharing. This normalization follows from pool ownership. [A4]

### G3 staging and Dynamo KVBM

AISim's G3 adapter stores blocks behind G2 and stages restored blocks through G2 before H2D loading. It therefore models a storage hierarchy, with staging capacity and transfer dependencies, rather than direct attention access to storage. [A6]

Dynamo KVBM has a broader execution subsystem: `OffloadEngine` coordinates G1→G2, G2→G3, and G2→G4 pipelines; `PhysicalWorker` owns layouts and a transfer manager, with object storage handled separately. These are references for physical migration semantics. They do not establish equivalent G4 or KVBM-policy support in AISim, whose reviewed engine configuration has no separate G4 tier. [D1] [D2] [A1]

## Capability boundaries

All entries below describe static implementation support, not reproduced runtime behavior.

| Composition                                       | Supported boundary                                                      | Restriction                                                                                                       |
| ------------------------------------------------- | ----------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| vLLM G2                                           | Local or shared pool; prefix caching enabled                            | Additional connector profiles are restricted to local aggregated use [A1]                                         |
| Agentic G2 in AISim                               | Offline aggregated or P/D pools; positive replica counts; attention DP1 | Static workers; G3 rejected; speculation excluded except a restricted single-worker local-G2 MTP combination [A8] |
| G3 replay                                         | Aggregated vLLM, attention DP1, G2 enabled, default connector           | No P/D or agentic composition [A1] [A14] [A8]                                                                     |
| KVCR                                              | Private G2 on aggregated or prefill workers                             | No shared G2, G3, or decode-role fetch [A1]                                                                       |
| SGLang HiCache                                    | Separate local host-cache path with prefix caching                      | Aggregated scope; it is not the vLLM connector path [A1]                                                          |
| Agentic G2 through Dynamo mocker                  | One aggregated worker, or one prefill plus one decode worker            | Narrower worker-count and speculation gates than AISim [D4]                                                       |
| Shared G2 through Dynamo's grouped live scheduler | Offline replay required by this path                                    | Live `cluster_shared` configuration is rejected [D5]                                                              |

Dynamo's mocker dependency is separately pinned; it does not automatically use the sibling AISim checkout. Adapter compatibility must be demonstrated before combining their capabilities. The package versions and source identities are recorded in Appendix A. [D3] [D6]

## Required extensions

The following modules are proposed research work. Their interfaces and behavior are not implemented or validated by this report.

| Research target | Existing foundation and gap | Proposed module boundary | Required correctness check |
| --- | --- | --- | --- |
| KV/expert contention | Transfer budgets are owned separately [A5] | A shared resource-budget owner used by KV and expert-transfer clients | Simultaneous clients cannot exceed one link's configured rate |
| MoE expert offloading | Dispatch/combine operators model token communication; no expert-weight residency lifecycle was identified in the engine configuration or inspected offload paths [A1] [A3] [A12] | Expert identity and residency, per-layer demand input, load/eviction policy, and compute dependency tracking | Expert execution waits for required weights; cancellation releases reservations; weights and KV obey the same G1 capacity limit |
| Direct execution from a slower tier | Current host restoration reserves G1 destinations [A3] | Memory-access costs in compute timing, distinct from migration timing | Resident slow-tier reads incur access cost without an artificial full restore |
| Agentic G3 | G3 adapter exists, but the runner rejects this composition [A6] [A8] | Extend workload compatibility and staging tests | Preserve dependency order, isolate replay identities, and avoid restore/eviction livelock |
| Agentic peer retrieval | KVCR exists but AgentX supplies no source hints [A7] [A13] | Hint production and routing integration | Stale hints fall back safely; source bandwidth and target capacity remain bounded |

Expert-demand data is an unresolved input. A request-level agentic trace must not be assumed to contain layer-wise expert selections. Until such data or a justified demand model is supplied, no expert-offloading performance claim is supported. Similarly, whether a shared link becomes the dominant bottleneck is an unverified hypothesis to test after integrating resource budgets.

## Technical decisions and trade-offs

These recommendations preserve the accepted Case 2-first scope; they are proposals for implementation, not newly accepted architecture decisions.

| Decision | Recommendation and evidence | Cost or condition for revisiting |
| --- | --- | --- |
| Baseline execution path | Use AISim engine-only replay with one vLLM worker, TP1, attention DP1, prefix caching, and local G2. The supplied fixture exercises the required restoration path [A15] [A9] | Does not validate Dynamo routing; add the adapter when routing becomes an experimental variable |
| Implementation sequence | Reproduce G1/G2 before changing tier mechanics. Existing reservation and completion rules already cover the basic KV case [A2] [A3] | A target backend's measured semantics may require connector changes |
| Case 1 baseline | Start with `cluster_shared` when the question concerns pooled capacity/bandwidth [A4] | Use private G2 plus KVCR when placement, source selection, or network transfer is the research variable [A7] |
| Timing calibration | Use fixed timing for functional controls, then matching hardware profiles and real-backend measurements [A15] [A13] | Fixed timing cannot establish absolute latency or speedup |
| Expert-offload design | Add explicit expert state and compute dependencies; integrate shared capacity/link accounting [A1] [A5] [A12] | More engineering than a constant transfer penalty, but required to represent eviction, overlap, and contention |

Case 2's KV baseline and Case 1's shared-pool baseline mainly require configuration and validation work. Agentic remote fetch requires workload/routing integration; expert offloading and direct slow-tier execution require new state or timing models. This effort ordering is an architectural inference from the modules above, not a delivery-time estimate.

## Validation criteria

The existing suite provides concrete acceptance criteria. None of the following runtime outcomes is claimed as locally verified.

| Check | Evidence already present | Acceptance criterion for reproduction |
| --- | --- | --- |
| Agentic restore | `test_weka_g2_cli_python_and_native_agree` [A9] | Four completions; resumed request reuses eight host tokens and zero G1 tokens; CLI, Python, and native reports agree |
| Bandwidth/capacity causality | `test_weka_g2_restore_has_causal_bandwidth_and_capacity_controls` [A9] | Slower H2D delays admission and TTFT; one-block G2 removes the restore hit; no-offload control increases prefill work |
| Shared ownership | `host_offload_scopes.rs` [A10] | Cross-rank reuse, one pool's capacity, fresh replay isolation, and rejection of incompatible contracts |
| Peer-transfer behavior | `kvcr_replay.rs` [A11] | Hint-driven restoration, source waits, and sharing of source bandwidth |
| Hardware fidelity | Connector documentation records unvalidated parity [A13] | Compare matching backend/model/hardware runs; report TTFT, TPOT, throughput, and transfer behavior separately |

After functional reproduction, sweep G1/G2 capacity, H2D/D2H bandwidth, and first-byte latency independently. Hold workload, scheduler, connector, and compute timing fixed. Measure latency distributions, completed-request throughput, committed prefill work, host reuse, occupancy, and exposed transfer counters. These are proposed experiments. A production-trace selection and hardware-error acceptance threshold remain open; neither is inferred from the small fixture.

## Appendix A: source and evidence record

| Repository | Commit | Working tree at November 16 recheck |
| --- | --- | --- |
| AISim | `c85b08623fc5fb8c6c6600619251d7fbf775bb1f` | Clean |
| Dynamo | `b20fe6fe94021b854597965c7305931175e8f482` | Clean |

AISim declares `aisim-core` version `0.15.0`. Dynamo pins `aisimulate-core = 0.13.0-dev.202610290000000087`. The source revisions are unchanged from the original report; no simulator code was modified for this revision. [D6]

| Evidence category | Status |
| --- | --- |
| Static source analysis | Implementation paths and explicit guards inspected; citations identify their scope |
| Test specifications | Assertions inspected; this does not establish test passage |
| Locally verified simulation behavior | None |
| Hardware experiments | Not run; no performance, accuracy, or resource-use results |
| Dynamo/AISim integration build | Not completed |
| Derived arithmetic | Fixture block size, capacity, and isolated transfer times calculated from source parameters; not measurements |

## Appendix B: reproduction and prior test attempt

Run from `src/aisim` after following its source-installation instructions and building the Python/native runtime. The two fixture commands are preserved as reproduction commands; they have not been executed successfully in this report.

```bash
aisim predict --stack engine --config examples/cli/agentx-g2-local.yaml --capture-per-request --output-dir /tmp/mirage-agentx-g2-local --format json
aisim predict --stack engine --config examples/cli/agentx-g2-shared-pd.yaml --capture-per-request --output-dir /tmp/mirage-agentx-g2-shared --format json
```

The local fixture uses the Weka trace `tests/e2e/configs/unified_cli/fixtures/traces/weka-g2-restore.jsonl`, the bundled tiny model, trace timestamps, and one agentic lane. It sets fixed prefill/decode timing to 2/1 ms, G1/G2 to 3/8 blocks, and both transfer directions to 1 GB/s. Its `h200_sxm` hardware field does not turn fixed timings into H200 measurements. [A15]

The earlier targeted test attempt, on November 15 on the local macOS host, was:

```bash
cargo test --offline -p aisim-core --test host_offload_scopes --test kvcr_replay
```

It exited with code 101 before running any test binary:

```text
error: no matching package named `anyhow` found
location searched: crates.io index
required by package `aisim-core v0.15.0`
```

This is a dependency-resolution blocker, not a test failure demonstrating incorrect simulation behavior. The attempt was not rerun for this editorial revision. No simulator result artifacts were produced; toolchain versions were not recorded in the original attempt and are not reconstructed here.

For subsequent experiments, record full source and timing-profile revisions, dependency versions, configuration, trace identity and request count, warmup, concurrency, seeds where sampling applies, and artifact paths. Keep deterministic fixtures separate from workload benchmarks. Choose the real trace and hardware-error threshold before interpreting benchmark results.

## Appendix C: source references

Source links identify the fixed revisions in Appendix A. Function anchors are included where a single entry point is useful.

- [A1: Configuration and validation](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/config.rs) · `aisim/crates/core/src/engine/config.rs`.
- [A2: Host capacity, residency, and transfer timing](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/host_offload/tier.rs#L273) · `aisim/crates/core/src/engine/host_offload/tier.rs`.
- [A3: vLLM store, restore, and admission](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/scheduler/vllm/host_offload.rs#L599) · `aisim/crates/core/src/engine/scheduler/vllm/host_offload.rs`.
- [A4: Private and shared G2 ownership](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/host_offload/registry.rs#L38) · `aisim/crates/core/src/engine/host_offload/registry.rs`.
- [A5: Bandwidth sharing](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/offload_transfer.rs#L30) · `aisim/crates/core/src/engine/offload_transfer.rs`.
- [A6: G3 staging and restoration](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/scheduler/vllm/g3_offload.rs) · `aisim/crates/core/src/engine/scheduler/vllm/g3_offload.rs`.
- [A7: Peer G2 transfer registry](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/kvcr.rs) · `aisim/crates/core/src/engine/kvcr.rs`.
- [A8: Agentic and runner compatibility gates](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/python/aisim/src/aisim/sweeper/replay.py#L356) · `aisim/python/aisim/src/aisim/sweeper/replay.py`.
- [A9: Agentic G2 regression tests](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/tests/test_agentx_g2.py#L77) · `aisim/tests/test_agentx_g2.py`.
- [A10: Shared-pool regression tests](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/tests/host_offload_scopes.rs) · `aisim/crates/core/tests/host_offload_scopes.rs`.
- [A11: Peer-transfer regression tests](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/tests/kvcr_replay.rs) · `aisim/crates/core/tests/kvcr_replay.rs`.
- [A12: MoE communication timing](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/perfmodel/operators/moe_dispatch.rs) · `aisim/crates/core/src/perfmodel/operators/moe_dispatch.rs`.
- [A13: Connector semantics and fidelity caveats](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/docs/replay/engine/kv-cache.md) · `aisim/docs/replay/engine/kv-cache.md`.
- [A14: Replay topology validation](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/replay/engine.rs) · `aisim/crates/core/src/replay/engine.rs`.
- [A15: Single-worker agentic fixture](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/examples/cli/agentx-g2-local.yaml) · `aisim/examples/cli/agentx-g2-local.yaml`.
- [A16: Simulation component boundaries](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/README.md) · `aisim/crates/core/README.md`.
- [D1: KVBM offload pipelines](https://github.com/ai-dynamo/dynamo/blob/b20fe6fe94021b854597965c7305931175e8f482/lib/kvbm-engine/src/offload/engine.rs) · `dynamo/lib/kvbm-engine/src/offload/engine.rs`.
- [D2: Physical transfers and tier handles](https://github.com/ai-dynamo/dynamo/blob/b20fe6fe94021b854597965c7305931175e8f482/lib/kvbm-engine/src/worker/physical.rs) · `dynamo/lib/kvbm-engine/src/worker/physical.rs`.
- [D3: Dynamo-to-AISim engine adapter](https://github.com/ai-dynamo/dynamo/blob/b20fe6fe94021b854597965c7305931175e8f482/lib/mocker/src/engine_adapter.rs#L29) · `dynamo/lib/mocker/src/engine_adapter.rs`.
- [D4: Dynamo agentic replay gates](https://github.com/ai-dynamo/dynamo/blob/b20fe6fe94021b854597965c7305931175e8f482/lib/mocker/src/replay/offline/entrypoints.rs#L46) · `dynamo/lib/mocker/src/replay/offline/entrypoints.rs`.
- [D5: Live shared-G2 restriction](https://github.com/ai-dynamo/dynamo/blob/b20fe6fe94021b854597965c7305931175e8f482/lib/mocker/src/grouped_scheduler.rs) · `dynamo/lib/mocker/src/grouped_scheduler.rs`.
- [D6: Pinned simulation-core dependency](https://github.com/ai-dynamo/dynamo/blob/b20fe6fe94021b854597965c7305931175e8f482/Cargo.toml) · `dynamo/Cargo.toml`.

[A10]: https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/tests/host_offload_scopes.rs
[A11]: https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/tests/kvcr_replay.rs
[A12]: https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/perfmodel/operators/moe_dispatch.rs
[A13]: https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/docs/replay/engine/kv-cache.md
[A1]: https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/config.rs
[A2]: https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/host_offload/tier.rs#L273
[A3]: https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/scheduler/vllm/host_offload.rs#L599
[A4]: https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/host_offload/registry.rs#L38
[A5]: https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/offload_transfer.rs#L30
[A6]: https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/scheduler/vllm/g3_offload.rs
[A7]: https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/kvcr.rs
[A8]: https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/python/aisim/src/aisim/sweeper/replay.py#L356
[A9]: https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/tests/test_agentx_g2.py#L77
[D1]: https://github.com/ai-dynamo/dynamo/blob/b20fe6fe94021b854597965c7305931175e8f482/lib/kvbm-engine/src/offload/engine.rs
[D2]: https://github.com/ai-dynamo/dynamo/blob/b20fe6fe94021b854597965c7305931175e8f482/lib/kvbm-engine/src/worker/physical.rs
[D3]: https://github.com/ai-dynamo/dynamo/blob/b20fe6fe94021b854597965c7305931175e8f482/lib/mocker/src/engine_adapter.rs#L29
[D4]: https://github.com/ai-dynamo/dynamo/blob/b20fe6fe94021b854597965c7305931175e8f482/lib/mocker/src/replay/offline/entrypoints.rs#L46
[D5]: https://github.com/ai-dynamo/dynamo/blob/b20fe6fe94021b854597965c7305931175e8f482/lib/mocker/src/grouped_scheduler.rs
[D6]: https://github.com/ai-dynamo/dynamo/blob/b20fe6fe94021b854597965c7305931175e8f482/Cargo.toml
[A14]: https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/replay/engine.rs
[A15]: https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/examples/cli/agentx-g2-local.yaml
[A16]: https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/README.md
