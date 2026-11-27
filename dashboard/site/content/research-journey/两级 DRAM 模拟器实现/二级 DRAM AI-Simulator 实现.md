---
title: 二级 DRAM AI-Simulator 实现
description:
subtitle: ""
tldr:
author:
  - Nan Lin
  - Codex
  - Claude
date: 2026-11-27T10:44:57.680+08:00
lastmod: 2026-11-27T12:40:33.390+08:00
draft: false
content_lang: zh-CN
tags: []
show_toc: true
weight: 3
---

## 实现概览


把 **单张 GPU 的两级内存状态放进 AISim 的 vLLM 调度器**。

每张 GPU 有一个 `TwoTierState`，维护小容量、高带宽的 Tier 1，大容量的 Tier 2，以及二者之间的共享传输链路。
	1. 计算使用 Tier 1 中的数据；
	2. 当前层缺少的权重或 KV 从 Tier 2 取入，数据到达后继续计算。


## 内存模型

### 权重更细粒度划分


通过 `build_profile()` 将权重按用途拆成三类：

- 全局权重，如 embedding 和 logits，计入一级常驻空间。
- 每层非专家权重，这里指路由专家以外的层内权重，包括 attention、router、norm 和 shared expert，按常驻或逐层预取策略放置。
- 路由专家权重，以一个专家为缓存和搬运单位。

通过 profile 同时记录 KV entry、indexer entry、sliding window 的大小。


### Tier 1 Memory

`TwoTierState::tier1()` 按六项统计一级占用：

```text
一级占用 = scratch + 全局权重 (e.g. Embedding)
         + 当前驻留或正在装入的非专家权重
         + 本 batch 的常读 KV
         + 专家缓存
         + 热 top-k KV 缓存
         + 尚未写回完成的新 KV
```


`scratch` 是由 `scratch_gb` 预留的计算临时空间；全局权重是 embedding、logits 等层外权重。这两部分合并为第一项，所以代码总共统计六项。

常读 KV 包括本 batch 的 sliding-window KV、HCA 完整压缩 KV 和 CSA indexer cache；热 top-k KV 则是 CSA 稀疏 attention 按需取入并缓存的条目。HCA 表示高度压缩 attention，CSA 表示压缩稀疏 attention。

非专家权重提供两种放置方式：

| 策略               | 一级占用与执行方式                                                                      |
| ---------------- | ------------------------------------------------------------------------------ |
| `resident`       | 所有层的非专家权重保持常驻                                                                  |
| `layer_prefetch` | 按当前层与下一层轮换；初始专家空间预算预留两份最大层权重，实际账本按当前 bundle 计数；当前层用完后释放，下一层预取可与计算重叠 |

## 计算模型

基础计算时间复用 AISim 原生性能模型。配置系统的一级内存带宽会影响这份基础时间；两级模型在此基础上模拟数据搬运和等待。

`decode_step_per_op()` 给出参考上下文下各算子的时间，再归并为 `attention_fraction`、`moe_fraction`、`tail_fraction`。每个实际 pass 的总时间仍由 AISim 根据该 pass 的 batch 与上下文定价；两级模型按上述比例分配到各层。

设 AISim 给出的 pass 时间为 `T_native`，模型有 `L` 层，则每层的基础时间为：

```text
T_attention = T_native × attention_fraction / L
T_MoE       = T_native × moe_fraction / L
T_tail      = T_native × tail_fraction
```

`T_attention` 和 `T_MoE` 是每层的时间，`T_tail` 是整轮只计一次的剩余时间。时间比例由参考上下文下的 profile 确定，每轮按实际 `T_native` 缩放。


## Runtime Pipeline

**在一个 pass 内，调度器选出一批 token，并让它们走完一次模型前向计算。** 


```text
选出本轮请求与 token
    ↓
取得本轮基础计算时间 T_native
    ↓
更新本 batch 的常读 KV 占用
    ↓
依次处理第 0 层、第 1 层……最后一层
    ├─ 等本层非专家权重就绪，并提交下一层预取
    ├─ 等本层所需 KV 就绪，再执行 attention
    └─ 等本层所需专家就绪，再执行 MoE
    ↓
执行层外剩余计算 tail
    ↓
将本轮新 KV 计入待写回空间，提交后台写回
    ↓
返回本轮结束时间，调度器据此安排后续 pass
```



## Pipeline 具体实现

`schedule_pass()` 选出本轮实际执行的请求，并保存它们的数据需求：

| 请求阶段    | 保存的字段                                              | 两级模型如何使用                         |
| ------- | -------------------------------------------------- | -------------------------------- |
| Prefill | `new_tokens`：本轮处理的新 token 数；`prefix_tokens`：已有前缀长度 | 计算需要读取的前缀 KV、访问的专家集合和新增 KV 量     |
| Decode  | `context`：本轮使用的上下文长度                               | 计算常读 KV 占用、CSA 的可选 KV 范围和新增 KV 量 |

`resolve_pass()` 从 AISim 性能模型取得本轮的 `T_native`，再把开始时间、请求列表和 `T_native` 交给 `TwoTierState::run_group_pass()`。单 GPU 场景只使用这张卡上的请求。




### 按当前 batch 更新常读 KV 占用

`pass_inner()` 根据本轮请求的上下文长度，计算 sliding-window KV、HCA 压缩 KV 和 CSA indexer cache 的总占用，并更新一级容量 metadata。


随后开始逐层执行。下面三步对每一层重复一次。

### 每层第一步：准备非专家权重，发起下一层预取

本层非专家权重包括 attention、router、norm 和 shared expert 等权重。`bundle` 就是这一层非专家权重的集合。

采用 `resident` 时，这些权重已经按常驻计入一级，直接进入 attention 阶段。采用 `layer_prefetch` 时，根据当前状态处理：

| 本层权重状态 | 状态机执行的动作 | 当前层是否等待 |
| --- | --- | --- |
| 已在一级，`Resident` | 直接使用 | 不等待 |
| 已提交预取，仍为 `Loading` | 将现有传输标为 urgent，提升它在按需优先队列中的优先级 | 等待剩余传输完成 |
| 一级中没有，也没有在途传输 | 预留一级空间，提交 `demand_base` 读取任务 | 等待本次读取完成 |

本层权重就绪后，提交下一层非专家权重的 `prefetch_base` 任务。当前层执行 attention 和 MoE 时，链路可以继续搬运下一层权重。最后一层预取的是下一轮所需的第 0 层。

如果启用了 `expert_prefetch: last_step`，此时还会开始预取下一层专家。

### 每层第二步：准备 KV，再执行 attention

对于 CSA 稀疏 attention 的 decode 请求，状态机执行以下过程：

1. 根据上下文长度和压缩比确定可选的 compressed KV entry 范围。
2. 为该请求选出本轮 top-k entry，并查询一级热 KV 缓存。
3. 对缺失条目预留一级空间，将同层缺失条目合并为 `demand_kv` 传输任务。
4. 等本层所需的 KV 读取任务完成，再推进 `T_attention` 的计算时间。
5. attention 完成后解除这些 KV 条目的 pin，使其之后可以被淘汰。

这里的 top-k 集合由带种子的访问模型生成。`topk_overlap` 是保留上一轮所选条目的概率，其余位置从可选范围中抽取。它控制跨步访问局部性。

对于 prefill，请求已有的压缩前缀按 `floor(prefix_tokens / compress_ratio) × kv_entry_bytes` 计读取字节数，提交 `prefill_kv`，读完后执行 attention。HCA 压缩 KV、sliding-window KV 和 CSA indexer cache 的一级占用已经在 pass 开始时计入。

### 每层第三步：准备专家，再执行 MoE

状态机先确定本层需要哪些专家，再对本 batch 的需求去重。例如，请求 A 需要专家 `{1, 3}`，请求 B 需要 `{3, 5}`，本层只需准备 `{1, 3, 5}`，专家 3 的权重可以供两个请求共同使用。

查询专家缓存后，已驻留专家直接使用；正在预取的专家等待已有传输完成；缺失专家提交 `demand_expert`。参与当前组计算的专家被 pin，直到这组 MoE 计算结束才解除 pin。

若一级一次容纳不了本层全部所需专家，就将专家分组。例如，本层需要 12 个专家、当前最多容纳 4 个，则依次处理三组：

```text
第 1 组：准备专家 → 等待缺失权重到达 → 执行这一组 MoE → 解除 pin
第 2 组：准备专家 → 等待缺失权重到达 → 执行这一组 MoE → 解除 pin
第 3 组：准备专家 → 等待缺失权重到达 → 执行这一组 MoE → 解除 pin
```

模型按各组专家数量分配本层的 `T_MoE`。解除 pin 表示“允许后续淘汰”，缓存仍可保留这些专家以供复用。

decode 的专家集合通过 `expert_overlap` 控制跨步重合。对含 N 个新 token 的 prefill 块，先按均匀路由计算期望去重数，再四舍五入、限制在合法范围内并抽取相应数量的专家：

```text
预期专家数 = E × [1 − (1 − k/E)^N]
E：本层专家总数；k：每个 token 选择的专家数
```

本层结束时，`lru` 保留全局 LRU 管理的缓存；`layer_partition` 清理该层超过份额的专家。采用 `layer_prefetch` 时，释放刚用完的本层非专家权重，保留已预取的下一层权重，然后进入下一层。

### 全部层结束：执行 tail，提交 KV 写回

所有层完成后，再推进一次 `T_tail`，表示前面未分入 attention 和 MoE 的层外剩余计算。


提交写回后，本轮返回计算结束时间。


## 结果

{{< embed-html src="../../Attachments/two-tier-dram-tpot-curves.html" title="TPOT 与 L1↔L2 带宽、一级容量（单卡 DeepSeek-V4-Pro，batch 8）" height="1150" >}}
