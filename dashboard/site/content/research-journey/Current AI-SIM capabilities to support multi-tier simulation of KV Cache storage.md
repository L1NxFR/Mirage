---
content_lang: en
title: Current AI-SIM capabilities to support multi-tier simulation of KV Cache storage
date: 2026-11-15
lastmod: 2026-11-15
draft: false
show_toc: true
description: Code review of multi-tier simulation support against the November 13 meeting requirements.
tldr: |
  The checked-out AISim already models local GPU–host KV offloading, shared host caches, and a restricted storage tier. Start Case 2 with its existing single-worker G1/G2 agentic fixture; expert offloading and direct execution from a second memory tier remain extension work. Dynamo provides implementation references and routing integration, but its checked-out replay interface has narrower support than the local AISim source.
---

## Research questions

The [November 13 meeting](../../meetings/2026-11-13-weekly-meeting/) asked for a comparison of two cases: shared KV cache across workers (Case 1), and a single GPU with two-level memory for KV cache followed by MoE experts (Case 2). It prioritized Case 2, scheduling and performance, and evaluation with agentic traces. This report supplies the code review and recommendation for the ten-minute sync. It does not report completed implementation or performance experiments.

**The current code supports the KV-offloading subset of Case 2.** The meeting's “not supported” description is too broad for this checkout. The existing model copies cached KV from GPU memory to host memory and restores it before execution. If “second-level memory” instead means memory from which attention or expert kernels execute directly, that behavior is not established by these offload paths and needs a separate model.

## Source baseline

| Repository | Reviewed commit | Local source changes |
| --- | --- | --- |
| AISim | `c85b08623fc5fb8c6c6600619251d7fbf775bb1f` | None reported by Git |
| Dynamo | `b20fe6fe94021b854597965c7305931175e8f482` | None reported by Git |

Review date: November 15, 2026. Findings below come from local implementations, validators, and test assertions. Source links are pinned to these commits. The existing meeting note is unchanged.

## Capability assessment

| Capability | AISim implementation | Boundary relevant to Mirage |
| --- | --- | --- |
| Single-worker GPU–host KV offload | G1 capacity plus G2 residency, eviction, store/load events, and transfer timing | vLLM path requires prefix caching; host-resident KV is restored to G1 before use |
| Shared host cache | `cluster_shared` creates one deployment-owned G2 pool | Participants must agree on cache layout and pool parameters |
| Private-cache peer fetch | KVCR transfers a prefix from another rank's G2 | Requires source hints and private G2; incompatible with G3; no peer pulls in the documented AgentX path |
| Third storage tier | G3 stores blocks and stages them through G2 | Aggregated vLLM, attention DP1, default offload connector; agentic replay rejects G3 |
| SGLang host cache | Separate `sglang.hicache` configuration | Local aggregated scope; not the same path as vLLM `host_offload` |
| Agentic workload with G2 | Local or shared G2; aggregated or P/D pools | Offline, vLLM, static pools, attention DP1; output is qualified `functional_only` |
| MoE expert offload | No expert-residency or migration lifecycle found in reviewed engine paths | MoE compute/communication timing does not provide expert placement, eviction, or load scheduling |
| Direct execution from a slower tier | Not established by the reviewed paths | Current KV restoration requires GPU capacity; this is not a generic two-level execution-memory model |

The restrictions are enforced in `EngineConfig` and runner validation, rather than being configuration suggestions. [A1](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/config.rs)[A8](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/python/aisim/src/aisim/sweeper/replay.py)

### Local G1/G2: what is already modeled

`HostTier` tracks resident and pending blocks, capacity, eviction order, and in-flight transfers. `HostClient::new` derives block bytes from block size and KV bytes per token. The vLLM adapter decides when blocks are stored, which prefix can be restored, and when a request can proceed. Its `start_load` reserves G1 destination blocks and can return capacity-blocked or deferred states. A large host cache therefore does not let an active request bypass GPU capacity constraints. [A2](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/host_offload/tier.rs)[A3](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/scheduler/vllm/host_offload.rs)[A4](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/host_offload/registry.rs)

The configurable timing inputs include separate H2D and D2H bandwidths and a first-byte delay. Private G2 uses a FIFO lane per direction. Shared G2 uses max-min fair service under both client and pool bandwidth limits. Zero bandwidth means unlimited service in this model, not a disabled link. These mechanics support capacity/bandwidth sensitivity studies without adding a new transfer simulator. [A2](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/host_offload/tier.rs)[A5](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/offload_transfer.rs)

The offload model advances logical blocks through virtual time. It does not move tensors or simulate PCIe transactions, cache coherence, NUMA placement, or a CXL fabric. Each transfer subsystem owns its budgets; sharing one fairness implementation does not establish a single physical-link budget across KV transfers, P/D transfers, and future expert loads. A shared-link contention model would need explicit integration. [A5](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/offload_transfer.rs)

Connector choice matters. The default `offloading_v0_24` and the two v0.32 profiles use different store and eviction rules. The source documentation states that these profiles were not compared against a running vLLM instance and records semantic deviations. Existing functionality is a starting point for validation, not evidence of measured fidelity. [A13](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/docs/replay/engine/kv-cache.md)

### Case 1: shared storage versus distributed fetch

`G2Registry::join` creates one host pool and checks each participant's layout, block geometry, capacity, and shared bandwidth contract. All participants access the same residency state. Tests cover cross-rank reuse, shared P/D pools, fresh-pool isolation, and rejection of incompatible roles. This is enough to begin a shared-capacity/shared-bandwidth study. It does not model arbitrary network topology or failure recovery. [A4](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/host_offload/registry.rs)[A10](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/tests/host_offload_scopes.rs)

KVCR models a different arrangement: separate G2 caches with explicit transfers between them. Its registry tracks source availability, in-flight pulls, transferred bytes, and source wait time. Tests inspect source contention and hinted remote restoration. This is a useful basis for a distributed-cache study, but source selection must supply hints. Agentic G2 support alone does not make remote fetch active. [A7](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/kvcr.rs)[A11](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/tests/kvcr_replay.rs)[A13](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/docs/replay/engine/kv-cache.md)

### G3 and agentic traces

The G3 adapter implements stores and staged restoration through G2. Configuration validation requires G2 and the default vLLM connector; replay further restricts G3 to aggregated attention-DP1 execution. The Python capability gate rejects agentic replay with G3. Studying three-tier agentic workloads would therefore require extending and testing this composition. [A1](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/config.rs)[A6](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/scheduler/vllm/g3_offload.rs)[A8](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/python/aisim/src/aisim/sweeper/replay.py)

For G2, the local AISim validator permits positive worker counts in aggregated or P/D pools, with attention DP1 and no scaling policy. The simplest starting configuration disables speculation; a restricted single-worker local-G2 MTP exception exists but is unnecessary for the meeting's objective. [A8](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/python/aisim/src/aisim/sweeper/replay.py)

The existing agentic fixture has a parent request, a child that displaces the parent's GPU prefix, and a later parent continuation. Its tests assert four completed requests, eight host-reused tokens on restoration, and zero G1 reuse at that admission. They also assert that reducing H2D bandwidth delays TTFT, shrinking G2 removes the hit, and disabling offload increases committed prefill work. These are inspected test expectations, not results reproduced in this review. [A9](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/tests/test_agentx_g2.py)

## What Dynamo contributes

Dynamo contains real multi-tier cache-management code. `OffloadEngine` owns G1→G2, G2→G3, and G2→G4 pipelines. `PhysicalWorker` owns layout handles and a transfer manager; object storage has a separate path. These implementations provide reference behavior for migration, staging, and resource lifetimes. They do not imply that AISim simulates all Dynamo tiers or policies. In particular, no separate G4 configuration was found in the reviewed AISim engine configuration. [D1](https://github.com/ai-dynamo/dynamo/blob/b20fe6fe94021b854597965c7305931175e8f482/lib/kvbm-engine/src/offload/engine.rs)[D2](https://github.com/ai-dynamo/dynamo/blob/b20fe6fe94021b854597965c7305931175e8f482/lib/kvbm-engine/src/worker/physical.rs)[A1](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/config.rs)

Dynamo's mocker also wraps an AISim core through `engine_components` and `engine_factory`. That integration must be assessed separately from the downloaded AISim repository. [D3](https://github.com/ai-dynamo/dynamo/blob/b20fe6fe94021b854597965c7305931175e8f482/lib/mocker/src/engine_adapter.rs)

| Integration check | Local code finding | Consequence |
| --- | --- | --- |
| Dependency version | Dynamo pins `aisimulate-core = 0.13.0-dev.202610290000000087`; local AISim declares `aisim-core` version `0.15.0` | The sibling checkout is not automatically the core used by Dynamo |
| Agentic G2 worker count | Dynamo's offline gate requires one worker per active role; local AISim accepts multiple replicas | Do not transfer AISim's multiworker claim to this Dynamo entrypoint |
| Live shared G2 | Dynamo's grouped live scheduler rejects `cluster_shared` | Use offline replay for this reviewed path |

These differences are visible in dependency declarations and validators. No compatibility build of the two checkouts was completed. Start with AISim's engine-only runner; integrate Dynamo routing only when the experiment needs it and after checking the dependency/API boundary. [D4](https://github.com/ai-dynamo/dynamo/blob/b20fe6fe94021b854597965c7305931175e8f482/lib/mocker/src/replay/offline/entrypoints.rs)[D5](https://github.com/ai-dynamo/dynamo/blob/b20fe6fe94021b854597965c7305931175e8f482/lib/mocker/src/grouped_scheduler.rs)[D6](https://github.com/ai-dynamo/dynamo/blob/b20fe6fe94021b854597965c7305931175e8f482/Cargo.toml)[A8](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/python/aisim/src/aisim/sweeper/replay.py)

## Implementation complexity and recommendation

The estimates below concern engineering scope inferred from code, not measured development time.

| Work item | Relative effort | Reason |
| --- | --- | --- |
| Case 2: reproduce local G1/G2 KV offload | Low initial code effort | Existing fixture, scheduler integration, and regression tests |
| Case 1: shared G2 capacity/bandwidth study | Low to moderate | Existing pool; requires controlled placement and fair capacity normalization |
| Case 1: topology-aware peer fetch with agentic traffic | Moderate to high | Hint generation, transfer composition, and validation need work |
| Case 2: second-tier direct execution | High | Requires execution access costs and resource constraints beyond restore-before-compute |
| Case 2: MoE expert offloading | High | Requires expert identities, residency, demand, loads, eviction, and compute dependencies |

Keep the meeting's Case 2-first order, but start by reproducing the existing KV model. Case 1's shared-pool baseline can then reuse the workload and measurements. Neither basic KV scenario requires writing a new simulator from scratch.

For MoE, the reviewed operator models price token dispatch/combine communication. They do not establish per-expert residency or weight migration. A proposed extension needs a per-layer expert-demand sequence, explicit weight sizes and tier capacities, transfer scheduling, and stalls when required experts are absent. Request traces alone may not contain expert selections. If KV and experts share a host link, they must contend for the same modeled budget; simply adding two independent transfer times would miss that interaction. This is proposed work, not an implemented capability. [A12](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/perfmodel/operators/moe_dispatch.rs)

## Evaluation plan

1. Reproduce the local G2 fixture and its no-offload, small-capacity, and slow-bandwidth controls. Keep one worker, TP1, attention DP1, prefix caching, fixed timing, and no speculation. Confirm request completion and the expected causal changes before using hardware timing data.
2. Sweep G1 capacity, G2 capacity, directional bandwidth, and first-byte latency independently. Record TTFT distributions, completion time, throughput, committed prefill tokens, host reuse, pool occupancy, and transfer counters where exposed. Keep workload, timing source, and scheduling parameters fixed.
3. Replay a pinned agentic dataset with matching model/hardware timing data. Record trace provenance, request count, dependency structure, warmup, concurrency, source revisions, profile revisions, and seeds when sampling is used. Report this separately from the four-request fixture.
4. Compare private and shared G2 at equal total host capacity and stated aggregate bandwidth. With N private ranks, the total capacity is N times the per-rank capacity; a shared pool counts capacity once. Otherwise a capacity increase could be mistaken for a sharing benefit.
5. Validate selected cases against an actual serving backend before making hardware-performance claims. Extend expert offloading only after the KV baseline has passed these checks.

The upstream smoke commands below run from `src/aisim` after its documented source installation. They are proposed reproduction commands and were not executed successfully during this review.

```bash
aisim predict --stack engine --config examples/cli/agentx-g2-local.yaml --capture-per-request --output-dir /tmp/mirage-agentx-g2-local --format json
aisim predict --stack engine --config examples/cli/agentx-g2-shared-pd.yaml --capture-per-request --output-dir /tmp/mirage-agentx-g2-shared --format json
```

## Verification and limits

Static review covered the configurations, host-transfer engine, vLLM adapter, shared-pool registry, G3 and KVCR paths, agentic guards, Dynamo adapter, and KVBM transfer components. Both downloaded repositories were clean at review time.

The following targeted test command was attempted from `src/aisim`:

```bash
cargo test --offline -p aisim-core --test host_offload_scopes --test kvcr_replay
```

It exited with code 101 because the offline Cargo cache lacked `anyhow`. No test binary ran. Reproduction requires resolving the pinned Rust dependencies and building the source environment. Agentic CLI tests, real-GPU validation, and performance/resource measurements remain unrun. No simulator or Dynamo code was changed.

This review establishes implementation paths and explicit restrictions. It does not establish numerical accuracy, speedup, or full Dynamo–AISim compatibility.

## Code references

References below link to the exact reviewed revisions. Paths are relative to each downloaded repository.

- [A10: Shared-pool regression tests](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/tests/host_offload_scopes.rs): `aisim/crates/core/tests/host_offload_scopes.rs`.
- [A11: Peer-transfer regression tests](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/tests/kvcr_replay.rs): `aisim/crates/core/tests/kvcr_replay.rs`.
- [A12: MoE communication timing](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/perfmodel/operators/moe_dispatch.rs): `aisim/crates/core/src/perfmodel/operators/moe_dispatch.rs`.
- [A13: Connector semantics and fidelity caveats](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/docs/replay/engine/kv-cache.md): `aisim/docs/replay/engine/kv-cache.md`.
- [A1: Configuration and validation](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/config.rs): `aisim/crates/core/src/engine/config.rs`.
- [A2: Host capacity, residency, and transfer timing](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/host_offload/tier.rs): `aisim/crates/core/src/engine/host_offload/tier.rs`.
- [A3: vLLM store, restore, and admission](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/scheduler/vllm/host_offload.rs): `aisim/crates/core/src/engine/scheduler/vllm/host_offload.rs`.
- [A4: Private and shared G2 ownership](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/host_offload/registry.rs): `aisim/crates/core/src/engine/host_offload/registry.rs`.
- [A5: Bandwidth sharing](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/offload_transfer.rs): `aisim/crates/core/src/engine/offload_transfer.rs`.
- [A6: G3 staging and restoration](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/scheduler/vllm/g3_offload.rs): `aisim/crates/core/src/engine/scheduler/vllm/g3_offload.rs`.
- [A7: Peer G2 transfer registry](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/crates/core/src/engine/kvcr.rs): `aisim/crates/core/src/engine/kvcr.rs`.
- [A8: Agentic and runner compatibility gates](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/python/aisim/src/aisim/sweeper/replay.py): `aisim/python/aisim/src/aisim/sweeper/replay.py`.
- [A9: Agentic G2 regression tests](https://github.com/ai-dynamo/aisim/blob/c85b08623fc5fb8c6c6600619251d7fbf775bb1f/tests/test_agentx_g2.py): `aisim/tests/test_agentx_g2.py`.
- [D1: KVBM offload pipelines](https://github.com/ai-dynamo/dynamo/blob/b20fe6fe94021b854597965c7305931175e8f482/lib/kvbm-engine/src/offload/engine.rs): `dynamo/lib/kvbm-engine/src/offload/engine.rs`.
- [D2: Physical transfers and tier handles](https://github.com/ai-dynamo/dynamo/blob/b20fe6fe94021b854597965c7305931175e8f482/lib/kvbm-engine/src/worker/physical.rs): `dynamo/lib/kvbm-engine/src/worker/physical.rs`.
- [D3: Dynamo-to-AISim engine adapter](https://github.com/ai-dynamo/dynamo/blob/b20fe6fe94021b854597965c7305931175e8f482/lib/mocker/src/engine_adapter.rs): `dynamo/lib/mocker/src/engine_adapter.rs`.
- [D4: Dynamo agentic replay gates](https://github.com/ai-dynamo/dynamo/blob/b20fe6fe94021b854597965c7305931175e8f482/lib/mocker/src/replay/offline/entrypoints.rs): `dynamo/lib/mocker/src/replay/offline/entrypoints.rs`.
- [D5: Live shared-G2 restriction](https://github.com/ai-dynamo/dynamo/blob/b20fe6fe94021b854597965c7305931175e8f482/lib/mocker/src/grouped_scheduler.rs): `dynamo/lib/mocker/src/grouped_scheduler.rs`.
- [D6: Pinned simulation-core dependency](https://github.com/ai-dynamo/dynamo/blob/b20fe6fe94021b854597965c7305931175e8f482/Cargo.toml): `dynamo/Cargo.toml`.
