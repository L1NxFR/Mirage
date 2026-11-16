---
content_lang: en
title: AI-SIM
subtitle: ""
date: 2026-11-15
lastmod: 2026-11-15
author: ""
draft: false
description: An overview of NVIDIA AISim and its LLM serving simulation capabilities.
tldr: |
  AISim predicts LLM serving performance and compares deployment configurations without running a GPU serving cluster. It combines request-level simulation with performance models to estimate latency, throughput, and resource use across different workloads and inference backends.
categories: []
tags: []
show_toc: true
weight: 0
---

## Overview

[AISim](https://github.com/ai-dynamo/aisim) is an LLM serving simulator developed by NVIDIA under the ai-dynamo organization. It succeeds AIConfigurator (AIC), extending performance estimation and configuration search with request-level simulation. Its core is written in Rust, with Python interfaces for configuration and experiments.

AISim runs offline without a GPU serving cluster. Given a model, hardware configuration, and workload, it simulates how requests are queued, scheduled, and processed, then estimates metrics such as time to first token (TTFT), time per output token (TPOT), and throughput. It models execution time without generating model outputs or executing CUDA kernels during replay.

AISim can run independently of NVIDIA Dynamo. An optional integration connects it to Dynamo's router and planner to simulate request routing and worker allocation.

## How it works

AISim combines execution simulation with performance modeling. The execution layer tracks request arrivals, queues, batching, scheduling, and cache state. The performance layer estimates the time required for each forward pass using GPU measurements or operator-level models. Together, these layers model how workload changes and resource constraints affect serving performance.

Measured timings can be reused across replay experiments. Collecting new timing data still requires the corresponding GPU environment; running a simulation with existing data does not.

## Main capabilities

The following summary describes the local source revision `c85b08623`, reviewed on November 15, 2026. Feature availability depends on the backend, model, topology, and workload; separately supported features are not necessarily supported in combination.

| Capability | Description |
| --- | --- |
| Inference backends | Models serving behavior for vLLM, SGLang, and TensorRT-LLM |
| Request scheduling | Simulates queues, continuous batching, and backend-specific admission behavior |
| Parallelism | Models tensor, pipeline, data, and MoE expert parallelism within supported configurations |
| Deployment layouts | Supports aggregated serving and prefill/decode disaggregation |
| Cache management | Models prefix reuse, eviction, and supported host/storage offloading configurations |
| Workloads | Supports synthetic traffic, request traces, and qualified session or agentic workloads |
| Performance prediction | Estimates request latency, TTFT, TPOT, throughput, and resource use |
| Configuration search | Compares parallelism, batching, worker counts, and deployment layouts against performance targets |
| Dynamo integration | Provides optional adapters for routing and worker planning |

See the [feature support matrix](https://github.com/ai-dynamo/aisim/blob/main/docs/replay/features.md) for backend-specific restrictions and supported combinations.

## Development status and limitations

The local checkout includes releases tagged `v0.12.0`, `v0.12.1`, and `v0.13.0`. Development on `main` includes backend support, performance-model updates, multimodal simulation, and the package rename from `aisimulate` to `aisim`. The [README](https://github.com/ai-dynamo/aisim#readme) notes that source documentation may describe capabilities newer than the published package.

AISim includes automated tests and comparisons against GPU measurements. Prediction accuracy depends on the configuration, timing data, and workload. Forward-pass accuracy and end-to-end serving accuracy are separate: a good estimate of compute time does not by itself establish accurate queueing or request latency.

AISim is useful for comparing deployment choices and testing performance hypotheses before running GPU experiments. Its predictions still require validation against the target serving environment. Published versions and planned work are documented in the [release history](https://github.com/ai-dynamo/aisim/releases) and [Q4 roadmap](https://ai-dynamo.org/slides/aisim.html).
