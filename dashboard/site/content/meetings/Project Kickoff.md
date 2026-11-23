---
weight: 1
content_lang: en
title: Project Kickoff
date: 2026-11-12
draft: false
show_toc: true
tldr: "**Project Goal**: Shared/Distributed Memory Architecture for KV Cache with Agentic Traces"
---
## Project Goal

Shared/Distributed Memory Architecture for KV Cache with Agentic Traces

## Problem

**Understand Shared/Distributed Memory Architecture for KV Cache with Agentic Traces.**

Below is a high-level architecture study. We want to quickly understand the **capacity/bandwidth trade-off** with two levels of memory and KV-cache placement.

## Case 1: Shared vs. Siloed KV-Cache Memory

### DynoSim — Setup Model

- ![NVIDIA — GB200 NVL72 rack/NVLink topology diagram](https://developer-blogs.nvidia.com/wp-content/uploads/2026/05/nvidia-gb200-nvl72-rack.webp) — [source article](https://developer.nvidia.com/blog/achieving-peak-system-and-workload-efficiency-on-nvidia-gb200-nvl72-with-slurm-block-scheduling/). Shows the rack's compute trays and switch interconnects.
- ![Netpreme — shared external KV-memory diagram, Figure 4](https://netpreme.com/images/blog/xm-sparse/transparent/figure-4.png) — [source article](https://netpreme.com/blog/xm-sparse-sglang-hisparse-netpreme-xmem). Illustrates shared X-Mem storage and KV-cache fetching.
    


### One Use Case

A useful abstraction is to define a **worker** as one attention data-parallel worker: a group of GPUs that together hold one copy of the attention weights and own the KV cache needed for the requests routed to that group. A worker can consist of one or more GPUs and corresponding CPUs.

If a token's KV cache is not found in GPU or CPU memory, it is recomputed. This does not affect the final conclusions. If two workers see requests with overlapping prefixes, useful KV cache may reside in a peer worker's GPU HBM or host memory. Therefore, it may be better to share host memory across workers for the KV cache—with GPUs from one worker having access to the KV cache in a peer worker's host memory—rather than use siloed KV-cache memory for each worker.

The **siloed setup** does not share the KV cache in HBM or DDR across workers, while the **shared setup** shares the DDR KV cache across workers. We can run the first request of each session during warm-up to populate the KV cache. For the remaining requests, a worker performs:

1. KV retrieval for prefix matches in the KV cache.
2. Prefill computation to “mid-fill” the remaining context.
3. Decode.

In the siloed setup, load-balance routing spreads a session's requests across workers, resulting in each worker serving requests for many more sessions than otherwise, forcing massive KV-cache thrashing and recomputations.

**Need to Study:** KV-overlap routing works better for agentic workloads. It sends requests to the worker holding the longest matching prefix, keeping each session on one worker. This improves locality, thus minimizing KV recomputations, but can oversubscribe workers and increase queueing delays.

The **shared setup** decouples load balancing from cache ownership, allowing the scheduler to balance load while preserving high cache locality.

Related work: [Netpreme — XM-Sparse: Pushing the Throughput Frontier of Sparse Attention with Netpreme X-Mem™](https://netpreme.com/blog/xm-sparse-sglang-hisparse-netpreme-xmem).

_(Netpreme and other folks are looking at this.)_

## Case 2: Two-Level Memory Within a Single GPU

We have two levels of memory within a single GPU. The goal here is to understand the second-level bandwidth trade-off relative to the first level.

Similar to the first use case, this also tackles the problem of **MoE expert-weight placement and KV-cache offloading in second-tier memory**. If we have simulation infrastructure to study these two-level scenarios, we can understand the trade-off.

Today, in slides, we have done some Excel-based modeling to study these.


## Simulation Infrastructure for Both Use Cases

### Model

**Pick a model.**

### Benchmark

**NVIDIA AIPerf agentic code generator** can generate realistic agentic traces, including prefix sharing across sessions and delays for tool execution or human input.

We can use it to create **1,000+ sessions** with high KV reuse (**98.9%**, similar to the AgentX inference benchmark) and wide variation in turn count, ranging from **1 to 204 turns per session**. Each session has a maximum length of **128,000 tokens or more**.

Official generator documentation: [NVIDIA AIPerf — Agentic Code Dataset Generator](https://docs.nvidia.com/aiperf/tutorials/datasets-inputs/agentic-code-dataset-generator).

### DynoSim Routing Policies

NVIDIA DynoSim with a **vLLM backend**, instrumented to collect metrics, with support added for the following routing policies:

- **Load-balance:** Route the request to the worker with the minimum mid-fill load.
- **KV overlap:** Route the request to the worker with the largest matching KV cache available.
    

See vLLM deployments and agentic-serving discussion: [vLLM x AgentX: Optimizing for Real-World Agentic Serving](https://vllm.ai/blog/2026-09-08-vllm-agentx).

## References 

- [NVIDIA — DynoSim: Simulating the Pareto Frontier](https://developer.nvidia.com/blog/dynosim-simulating-the-pareto-frontier)
- [NVIDIA — DynoSim simulation model documentation](https://docs.dynamo.nvidia.com/dynamo/knowledge-base/concepts/simulation/simulation-model)
- [NVIDIA AIPerf — Agentic Code Dataset Generator](https://docs.nvidia.com/aiperf/tutorials/datasets-inputs/agentic-code-dataset-generator)
- [vLLM x AgentX: Optimizing for Real-World Agentic Serving](https://vllm.ai/blog/2026-09-08-vllm-agentx)
- [Netpreme — XM-Sparse, SGLang HiSparse, and X-Mem](https://netpreme.com/blog/xm-sparse-sglang-hisparse-netpreme-xmem)
    

