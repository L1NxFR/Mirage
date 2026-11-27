---
title: 二级 DRAM 原理介绍
description: ""
subtitle: ""
tldr: ""
author:
  - Nan Lin
date: 2026-11-27T10:11:43.580+08:00
lastmod: 2026-11-27T10:48:01.575+08:00
draft: false
content_lang: zh-CN
tags: []
show_toc: true
weight: 1
---
关键词：两级 DRAM、数据搬运与计算重叠、稀疏 Attention、预取、MoE

本文说明两级 DRAM 在 decode 阶段的数据放置与执行流程。模型采用带 indexer 的稀疏 Attention，以及位于 Attention 之后的 MoE。预测 KV 和专家属于可选优化，本文不将其视为已经实现的功能。

![](../../Attachments/Pasted%20image%2020261127031458.png)

## 两级 DRAM

### 内存硬件与数据放置

本方案采用两级 DRAM。一级提供高带宽，保存计算工作集和缓存。二级提供较大容量，保存完整数据。

| 存储层级 | 硬件与特点 | 存储内容 |
| --- | --- | --- |
| 一级 DRAM（Tier 1） | 3D-stacked DRAM，带宽高、容量小 | 当前算子所需的权重和 KV、indexer 索引数据、预取缓冲、热 KV、热专家权重，以及激活和计算临时数据 |
| 二级 DRAM（Tier 2） | LPDDR，带宽相对较低、容量大 | 模型权重和历史 KV 的完整副本，接收新生成 KV 的写回 |


分布式推理中，模型权重/KV Cache 可能分布在不同 rank 中。

### 单层推理流程

假设当前执行第 $l$ 层。

0. **Tier 1 DRAM** 已经准备好 Attention 和 indexer 所需的权重、和（在前一层执行的）预测的当前层执行 Sparse Attention 所会需要的 Top-k Expert. 部分 Hot KV Cache 已在缓存里。
1. 进行当前层的 compute 和如有需要的 on-demand loading
	1. 执行 KV indexer（MoE router 同理），确定这次 attention 需要的 top-k KV index 和 Expert index.
		1. 如果已经在 Tier 1 DRAM，则直接复用
		2. 如果不在，则需要从 Tier 2 DRAM on-demand load
	2. 所需 KV Cache（Expert 同理）到达后，执行 attention/MoE
2. 在此同时，进行对下一级的预取
	1. Prefetch 下一层一定会用到的权重
	2. Predict and prefetch 下一层 KV Cache 和 Experts

### 与当前层计算重叠的预取

预取（prefetch）在使用数据之前发起搬运，目的是用计算时间隐藏传输时间。预取分为两类：

- **已知需求的预取**：在当前层计算期间，提前搬入下一层确定需要、但尚未驻留一级的权重和 indexer 索引数据。
- **基于预测的预取**：在下一层实际的 indexer 或 router 结果产生前，预测所需的 Attention KV 或专家权重，并提前搬入一级。

预测预取是可选优化。实际选择结果产生后，系统仍需检查数据是否齐全，并按需补齐缺失部分。预测命中但传输未完成时，计算仍要等待。

预取、按需加载和 KV 写回共享搬运链路。它们可以与计算重叠，但传输之间会竞争带宽。调度策略需要避免后台预取拖延当前计算所需的数据。

### KV 写回与缓存复用

当前 token 的 KV 在一级生成，并按本方案写回二级，供后续 decode step 使用。

已使用的 KV 和专家权重可以继续留在一级，形成热 KV 缓存和热专家缓存。后续访问命中时，不再从二级搬运。

一级空间不足时，系统回收工作缓冲或淘汰缓存。正在使用或传输中的数据需要保护。对于二级已有有效副本的只读数据，淘汰一级副本无需再次写回。

## 潜在问题

| 问题 | 对执行的影响 |
| --- | --- |
| 预测准确性 | 漏掉实际需要的数据会触发按需加载。搬入未使用的数据会浪费带宽和容量。 |
| 预取时机 | 预取过晚，计算仍需等待。预取过早，数据会长时间占用一级空间。 |
| 搬运与计算重叠 | 当前层计算时间不足以覆盖搬运时间时，剩余传输延迟会暴露在执行路径上。 |
| 共享链路竞争 | 按需加载、预取和 KV 写回相互争用带宽，调度顺序会影响等待时间。 |
| 一级容量与淘汰 | 工作集、预取缓冲和热缓存争用空间。预取可能挤掉后续仍需复用的数据。 |




