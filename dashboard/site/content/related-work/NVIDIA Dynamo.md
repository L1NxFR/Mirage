---
content_lang: en
title: NVIDIA Dynamo
subtitle: ""
date: 2026-11-15
lastmod: 2026-11-15
author: ""
draft: false
description: An overview of NVIDIA Dynamo and its distributed inference serving capabilities.
tldr: |
  NVIDIA Dynamo coordinates inference engines across GPUs and nodes. It provides request routing, disaggregated serving, data transfer, and scaling, while backends such as vLLM, SGLang, and TensorRT-LLM execute the model.
categories: []
tags: []
show_toc: true
weight: 0
---

## Overview

[NVIDIA Dynamo](https://github.com/ai-dynamo/dynamo) is an open-source distributed inference framework developed by NVIDIA. It combines a Rust runtime with Python components and interfaces to coordinate model serving across multiple GPUs and nodes.

Running several inference workers introduces decisions beyond executing a model: which worker should receive a request, how work should be divided between workers, and when more capacity is needed. Dynamo manages these decisions around inference engines such as vLLM, SGLang, and TensorRT-LLM.

For a single model on one GPU, an inference engine alone is often sufficient. Dynamo becomes useful when a deployment needs routing, coordination, or independent scaling across workers. See the [project README](https://github.com/ai-dynamo/dynamo#readme) for its intended use cases.

## How it works

![NVIDIA Dynamo architecture](../Attachments/Pasted%20image%2020261115200138.png)

A frontend accepts API requests and passes them to the serving workers through Dynamo's routing layer. Each worker uses an inference backend to run the model and generate tokens. Results stream back through the frontend.

In aggregated serving, a worker performs both prefill and decode. In disaggregated serving, separate worker pools handle these phases. Prefill workers process input tokens; decode workers receive the resulting state and generate output tokens. Dynamo coordinates this handoff, with NIXL providing data transfer in supported configurations.

A separate control path monitors runtime metrics and adjusts worker counts. In Kubernetes deployments, the Dynamo Operator applies the desired deployment state. The [architecture documentation](https://docs.dynamo.nvidia.com/dynamo/v1.6.0/knowledge-base/concepts/architecture) describes request flow, service discovery, and communication between components.

## Relationship with inference engines

Dynamo and the inference backend operate at different levels of a deployment:

| Layer | Responsibility |
| --- | --- |
| Dynamo | Selects workers, coordinates serving stages, and manages deployment capacity |
| vLLM / SGLang / TensorRT-LLM | Executes the model, batches work within the engine, and manages backend-specific execution |
| GPU kernels and libraries | Perform the numerical computation |

For example, a Dynamo deployment using vLLM still runs vLLM inside its inference workers. Dynamo routes a request to a worker; vLLM schedules its computation and executes the model. Selecting TensorRT-LLM instead changes the backend responsible for execution.

## Main capabilities

| Capability | Description |
| --- | --- |
| Request routing | Selects workers using load and, where enabled, reusable prefix information |
| Disaggregated serving | Separates prefill and decode into independently scalable pools |
| Autoscaling | Uses the Planner to adjust capacity based on workload metrics and service targets |
| Data transfer | Uses NIXL to move inference state between workers and memory domains |
| Cache management | Supports reuse and offloading through compatible backend integrations |
| Distributed runtime | Provides service discovery, request transport, event delivery, and worker lifecycle management |
| Deployment management | Supports local execution and Kubernetes orchestration |

The [overall architecture](https://docs.nvidia.com/dynamo/dev/knowledge-base/overview) explains how these components interact. Components and deployment modes are configurable; a deployment need not enable every capability.

## Development status and limitations

As reviewed on November 15, 2026, Dynamo has versioned documentation and published releases; this introduction uses the v1.6.0 architecture reference alongside the main README and development documentation. Development documentation can include features beyond a selected release.

Backend integrations have different feature coverage. Model support, parallelism, multimodal inputs, and combinations of serving features must be checked against the chosen backend and Dynamo version. Disaggregation also introduces transfer and coordination costs, so its performance benefit depends on the workload and hardware.

Use the [release history](https://github.com/ai-dynamo/dynamo/releases) and the backend support matrix linked from the README when choosing a deployment configuration.
