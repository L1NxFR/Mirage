---
weight: 1
content_lang: en
title: 2026-11-13-Weekly Meeting
date: 2026-11-13
draft: false
show_toc: true
---
## MEETING

- Discussed two simulation scenarios:
    - **Case 1:** Shared KV cache across multiple workers (partially supported by NVIDIA AI Simulator).
    - **Case 2:** Single GPU with two-level memory for KV cache and MoE expert offloading (not supported).
- Decided to prioritize **Case 2**, starting with KV cache offloading, followed by MoE expert offloading.
- Agreed to use the latest NVIDIA AI Simulator and focus on scheduling and performance rather than randomness modeling.
- Connected to the Intel Server.
    

## TODO

- Review AI Simulator code and compare implementation complexity of both cases.
- Present a brief comparison and recommendation at Monday's sync (≤10 min).
- Implement two-level memory with KV cache offloading and evaluate performance using agentic traces.