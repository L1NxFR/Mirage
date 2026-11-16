---
content_lang: en
title: 2026-11-16-Weekly Meeting
date: 2026-11-16
draft: false
show_toc: true
---
## Overview



Last week, Yucheng and I discussed two simulation scenarios for studying KV-cache management under agentic workloads.
- **Case 1: KV-cache sharing across multiple workers.**
- **Case 2: Two-level memory within a single GPU worker.**

I am going to introduce for each case
1. Its key components and modeling challenges.
2. Existing solutions and AI-SIM simulator capabilities.
3. Required extensions, including missing behaviors and potential implementation challenges.

and planned work for the coming week.


## Case 1: KV-cache sharing across multiple workers


Case 1 considers
- Multi-worker LLM serving for multi-turn agentic workloads under **distributed LLM serving**.
- Successive requests often share long context prefixes. 
- Each worker consists of one or more GPUs and associated host memory, with KV caches stored in GPU HBM and host DDR.

Key aspects.
- Request Routing.
- KV-cache placement, strategy difference on recomputing or retrieving.


Siloed cache vs Shared DDR cache.
- Siloed cache
	- A worker can reuse only its own KV cache
	- Routing a request to another worker may therefore require recomputing a prefix already cached elsewhere. 
- Shared DDR cache
	- GPU HBM remains private.
	- A worker can retrieve reusable KV from a shared host-memory pool or another worker’s DDR.
	- Allows requests to be distributed across workers while retaining access to cached prefixes, introducing a trade-off between KV-transfer costs, recomputation, and queueing.

Representative Work.
- LMCache P2P. ![](data:image/svg+xml;charset=utf-8,%3Csvg%20font-family%3D%22-apple-system%2C%20%26quot%3Bsystem-ui%26quot%3B%2C%20%26quot%3BSegoe%20UI%26quot%3B%2C%20sans-serif%22%20font-weight%3D%22430%22%20data-d-component%3D%22svg%22%20fill%3D%22currentColor%22%20style%3D%22color%3Argb\(31%2C%2035%2C%2040\)%22%20viewBox%3D%220%200%20342%20227%22%20width%3D%22100%25%22%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%3E%3Crect%20x%3D%225%22%20y%3D%226%22%20width%3D%22158%22%20height%3D%22179%22%20rx%3D%2210%22%20fill%3D%22%2364748b%22%20fill-opacity%3D%22.06%22%20stroke%3D%22%2394a3b8%22%2F%3E%3Crect%20x%3D%22179%22%20y%3D%226%22%20width%3D%22158%22%20height%3D%22179%22%20rx%3D%2210%22%20fill%3D%22%2364748b%22%20fill-opacity%3D%22.06%22%20stroke%3D%22%2394a3b8%22%2F%3E%3Ctext%20x%3D%2284%22%20y%3D%2224%22%20font-size%3D%2212%22%20text-anchor%3D%22middle%22%20fill%3D%22currentColor%22%20font-weight%3D%22600%22%3EWorker%20A%3C%2Ftext%3E%3Ctext%20x%3D%22258%22%20y%3D%2224%22%20font-size%3D%2212%22%20text-anchor%3D%22middle%22%20fill%3D%22currentColor%22%20font-weight%3D%22600%22%3EWorker%20B%3C%2Ftext%3E%3Crect%20x%3D%2219%22%20y%3D%2234%22%20width%3D%22130%22%20height%3D%2245%22%20rx%3D%226%22%20fill%3D%22%230d9488%22%20fill-opacity%3D%22.15%22%20stroke%3D%22%230d9488%22%2F%3E%3Crect%20x%3D%22193%22%20y%3D%2234%22%20width%3D%22130%22%20height%3D%2245%22%20rx%3D%226%22%20fill%3D%22%230d9488%22%20fill-opacity%3D%22.15%22%20stroke%3D%22%230d9488%22%2F%3E%3Ctext%20x%3D%2284%22%20y%3D%2252%22%20font-size%3D%2211%22%20text-anchor%3D%22middle%22%20fill%3D%22currentColor%22%3EGPU%20HBM%3C%2Ftext%3E%3Ctext%20x%3D%2284%22%20y%3D%2267%22%20font-size%3D%2210%22%20text-anchor%3D%22middle%22%20fill%3D%22currentColor%22%3EKV%20of%20prefix%20P%3C%2Ftext%3E%3Ctext%20x%3D%22258%22%20y%3D%2252%22%20font-size%3D%2211%22%20text-anchor%3D%22middle%22%20fill%3D%22currentColor%22%3EGPU%20HBM%3C%2Ftext%3E%3Ctext%20x%3D%22258%22%20y%3D%2267%22%20font-size%3D%2210%22%20text-anchor%3D%22middle%22%20fill%3D%22currentColor%22%3EKV%20missing%20%E2%86%92%20restored%3C%2Ftext%3E%3Cpath%20d%3D%22M84%2079%20V109%20M258%20109%20V79%22%20stroke%3D%22%230d9488%22%20stroke-width%3D%221.6%22%2F%3E%3Cpath%20d%3D%22M80%20104%20L84%20110%20L88%20104%20M254%2085%20L258%2079%20L262%2085%22%20fill%3D%22none%22%20stroke%3D%22%230d9488%22%20stroke-width%3D%221.6%22%2F%3E%3Crect%20x%3D%2219%22%20y%3D%22110%22%20width%3D%22130%22%20height%3D%2255%22%20rx%3D%226%22%20fill%3D%22%2364748b%22%20fill-opacity%3D%22.13%22%20stroke%3D%22%2394a3b8%22%2F%3E%3Crect%20x%3D%22193%22%20y%3D%22110%22%20width%3D%22130%22%20height%3D%2255%22%20rx%3D%226%22%20fill%3D%22%2364748b%22%20fill-opacity%3D%22.13%22%20stroke%3D%22%2394a3b8%22%2F%3E%3Ctext%20x%3D%2284%22%20y%3D%22127%22%20font-size%3D%2211%22%20text-anchor%3D%22middle%22%20fill%3D%22currentColor%22%3ELocal%20CPU%20DDR%3C%2Ftext%3E%3Ctext%20x%3D%2284%22%20y%3D%22143%22%20font-size%3D%2210%22%20text-anchor%3D%22middle%22%20fill%3D%22currentColor%22%3ELMCache%20A%3C%2Ftext%3E%3Ctext%20x%3D%2284%22%20y%3D%22157%22%20font-size%3D%2210%22%20text-anchor%3D%22middle%22%20fill%3D%22currentColor%22%3EStores%20KV\(P\)%3C%2Ftext%3E%3Ctext%20x%3D%22258%22%20y%3D%22127%22%20font-size%3D%2211%22%20text-anchor%3D%22middle%22%20fill%3D%22currentColor%22%3ELocal%20CPU%20DDR%3C%2Ftext%3E%3Ctext%20x%3D%22258%22%20y%3D%22143%22%20font-size%3D%2210%22%20text-anchor%3D%22middle%22%20fill%3D%22currentColor%22%3ELMCache%20B%3C%2Ftext%3E%3Ctext%20x%3D%22258%22%20y%3D%22157%22%20font-size%3D%2210%22%20text-anchor%3D%22middle%22%20fill%3D%22currentColor%22%3EFetches%20KV\(P\)%3C%2Ftext%3E%3Cpath%20d%3D%22M150%20138%20H191%22%20stroke%3D%22%232563eb%22%20stroke-width%3D%222.5%22%20stroke-dasharray%3D%225%203%22%2F%3E%3Cpath%20d%3D%22M185%20133%20L192%20138%20L185%20143%22%20fill%3D%22none%22%20stroke%3D%22%232563eb%22%20stroke-width%3D%222%22%2F%3E%3Ctext%20x%3D%22171%22%20y%3D%22128%22%20font-size%3D%229%22%20text-anchor%3D%22middle%22%20fill%3D%22%232563eb%22%3ERDMA%3C%2Ftext%3E%3Crect%20x%3D%2273%22%20y%3D%22194%22%20width%3D%22196%22%20height%3D%2227%22%20rx%3D%227%22%20fill%3D%22%2364748b%22%20fill-opacity%3D%22.1%22%20stroke%3D%22%2394a3b8%22%2F%3E%3Ctext%20x%3D%22171%22%20y%3D%22211%22%20font-size%3D%2210.5%22%20text-anchor%3D%22middle%22%20fill%3D%22currentColor%22%3ECoordinator%3A%20peer%20discovery%20only%3C%2Ftext%3E%3Cpath%20d%3D%22M84%20185%20V194%20M258%20185%20V194%22%20stroke%3D%22%2394a3b8%22%20stroke-width%3D%221.3%22%20stroke-dasharray%3D%223%203%22%2F%3E%3C%2Fsvg%3E)
- Mooncake. ![](../Attachments/Pasted%20image%2020261116044436.png) ![](../Attachments/Pasted%20image%2020261116044923.png)
### Key components

#### Dynamo KV Router

> Reference: [Scaling multi-node LLM inference with NVIDIA Dynamo and NVIDIA GPUs on AKS (Part 3)](https://blog.aks.azure.com/2026/03/16/dynamo-on-aks-part-3)

![Dynamo KV Router making a solution in real time](https://blog.aks.azure.com/assets/images/dynamo_kv_aware_router_diagram-a2d6faf5ae2d256754a733c2365b7413.png)

Dynamo considers two factors simultaneously when routing requests
- **Cache locality:** How much of the request's prefix is already cached on each worker, reducing redundant prefill computation.
- **Worker load:** How busy each worker is, accounting for potential queueing delays.

The router balances prefix reuse against load distribution. A worker with the highest cache hit rate is not necessarily the best choice if it is heavily loaded.

#### KV Cache Manager

The cache manager tracks which prefix blocks are available in GPU HBM and host DDR. It handles cache lookup, storage, and eviction under limited memory capacity.

- **Siloed cache:** Each worker can reuse only its own cached KV.
- **Shared cache:** A worker can also retrieve KV stored outside its local cache.

For simulation, we need to track cache capacity, prefix matches, block locations, and eviction policies. A cached prefix may be evicted between routing and execution, so the worker must check its availability again before use.

Components.
- vLLM `KVCacheManager` manages GPU KV blocks inside each worker
- Dynamo KVBM, LMCache, Mooncake Store

#### KV Transfer Engine

The transfer engine moves reusable KV to the GPU that will execute the request.

- **Local reuse:** Local DDR → GPU HBM.
- **Peer reuse:** Peer DDR → local DDR → GPU HBM, for a staged transfer design.

For simulation, we need to model transfer size, bandwidth, latency, and contention between concurrent transfers. Retrieving cached KV is beneficial only when its cost is lower than the computation it avoids.

LMCache P2P and Mooncake Transfer Engine provide implementation references.

Components
- Dynamo NIXL
- Mooncake Transfer Engine

#### Worker Scheduler and Execution

After routing, the request joins the selected worker’s queue. The worker schedules KV restoration, prefill, and decode while respecting GPU memory capacity and batching limits.

- Reuse the available prefix after any required transfers complete.
- Run prefill for the remaining uncached input.
- Run decode to generate output tokens.

For simulation, we need to capture queueing, memory admission, batching, and computation time. A cache hit does not guarantee low latency if the worker is busy or the transfer is slow.


### Current AI-SIM capabilities

> Below `G1` and `G2` represents GPU and CPU/Host Memory, correspondingly HBM and DDR DRAM.


**Incomplete modeling and integration of KV-cache location information**
- KV blocks are tracked in a logical pool without explicit placement on individual physical devices.
- Consequently, fetch costs are not derived from the block’s physical location and the corresponding communication path.
- In peer-transfer mode, source-worker identities are supported, but the current agentic request path does not select and propagate the source hint required to trigger a fetch.

**AISim KVCR (KV Cache Runner) does not consider compute-communication overlapping.**

## Case 2: Two-level memory within a single GPU worker

Case 2 considers

- A single GPU worker with two memory tiers: GPU HBM and host DDR.
- Multi-turn agentic workloads whose reusable KV cache may exceed HBM capacity.

### Key components

1. **KV-cache placement and eviction**
2. **KV transfer and worker scheduling**


### Current AI-SIM capabilities

AI-SIM already provides the core mechanisms for Case 2 (updated just 2 weeks ago!): 
- two-tier KV-cache capacity management, 
- prefix lookup and reuse, 
- cache eviction, 
- HBD <-> host DDR transfer and timing,
- concurrent transfer contention and Overlapping (Relatively simple)
- scheduler integration
- agentic workload

## TODOs

- [ ] Verify AI-SIM modeling, benchmark its accuracy
- [ ] Replay trace to find in-consistency
- [ ] (Perhaps) Start to benchmark Case 1?