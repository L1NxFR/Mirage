---
weight: 4
content_lang: zh-CN
title: 两级 DRAM 实现对五条要求的核查
subtitle: ""
date: 2026-11-27T09:00:36+08:00
lastmod: 2026-11-27T09:00:36+08:00
author: Claude
draft: true
description: 通过读代码和跑实验，逐项核查 i163v 上的两级 DRAM 实现是否满足五条要求：引擎内实现、真实硬件参数、可容纳场景、仿真完整性、真实 trace。
tldr: |
  只有第 1 条基本满足：两级模型写在 AISim 的 vLLM 调度器里，等待会推迟后续准入（实测）。第 2、5 条不满足：所有运行都用 EXI 内部架构表加假设，负载都是脚本生成的 4–32 个定长请求，专家路由和 top-k 是带种子的均匀随机抽取。第 3 条部分满足：扫描和 EP8 都强制检查且可行，但单卡 Pro 用了 805.7 GB 二级，容量检查也不含 KV。第 4 条部分满足：链路排队、写回、预取都有代码和测试，但调度器不感知一级容量，一级溢出会让整次仿真中止。
categories: []
tags: [two-tier-dram, aisim, audit]
show_toc: true
---

## 结论

核查对象是 i163v 上 `~/Mirage/src`：AISim 子模块分支 `two-tier-dram-engine`（`436cf43`），Mirage 分支 `two-tier-dram-replay`（`7416213`）。两处工作区都没有未提交改动。

| 要求 | 结论 | 主要依据 |
| --- | --- | --- |
| 1. 改的是 AISim 内部的仿真与调度逻辑 | 基本满足 | 改动在 `scheduler/vllm/core.rs` 和 `engine/two_tier.rs`；实测等待推迟后续准入。调度器不感知一级容量 |
| 2. 使用已有两级内存产品的硬件参数 | 不满足 | 所有运行都用 `exi_3ddram`；系统文件 6 个字段来自内部架构表，10 个是假设 |
| 3. 只建模硬件放得下的场景 | 部分满足 | 4,608 个扫描点和 EP8 都强制检查且可行；单卡 Pro 用 805.7 GB 二级；检查不含 KV |
| 4. 仿真效果真实，影响因素在代码里 | 部分满足 | 链路排队、写回、预取有代码和测试；路由与 top-k 是合成的；多项争用未建模 |
| 5. 使用真实 trace | 不满足 | 负载是脚本生成的 4–32 个定长请求；i163v 上没有找到真实 trace 文件 |

## 第 1 条：引擎内实现

| 检查项 | 结论 | 证据 |
| --- | --- | --- |
| 结果来自引擎内路径 | 通过 | `sweep.py` 和 `ep.py` 都调用 `aisim predict --stack engine`，配置为 `kv_cache.two_tier_dram`。计划内 4,608 个点的记录全部带 AISim `436cf43`（实测） |
| 改动位置 | 通过 | `git diff c85b086..HEAD --stat`：16 个文件、2,785 行。`two_tier.rs` 2,075 行，`scheduler/vllm/core.rs` +123，`generalized/engine.rs` +32 |
| 等待反馈到调度 | 通过 | `resolve_pass` 用两级模型返回的结束时间替换原生结束时间。Flash、12 个请求的实测见下表。2 个回放级测试通过 |
| 调度器感知一级容量 | **不通过** | 见下文 |
| 8 卡每个 rank 都仿真 | 通过（代码与单元测试） | 每个 rank 有自己的 `TwoTierState`；没有本地请求的 rank 走 `two_tier_idle_pass`，group pass 取最慢 rank 的结束时间。trace 和命中数只来自 rank 0 |
| 没有离线改写 trace | 通过（静态审阅） | `sweep.py` 的 `compact_trace` 和 `ep.py` 只读 trace 做汇总，不改时间。`render.py` 未读 |
| 代码可复现 | 部分 | 本地 `src/aisim` 子模块指向 `436cf43`，提交在本地存在；远端 `origin` 上没有任何分支包含它，仍未推送 |

调度反馈实测（DeepSeek-V4-Flash，一级 36 GB 逐层轮换，二级 148.5 GB 强制检查，12 个 16K 请求每 50 ms 到一个，各输出 16 token，`max_sequences` 4）：

| 运行 | 有效复制带宽 | 第 2、5、12 个请求的准入时间 | 全部完成 |
| --- | --- | --- | --- |
| AISim 原生 | — | 203、829、2,275 ms | 2,499 ms |
| 两级，带宽无限 | 无限 | 203、829、2,275 ms | 2,499 ms |
| 两级 | 880 GB/s | 372、1,642、4,445 ms | 5,066 ms |
| 两级 | 220 GB/s | 880、4,111、11,026 ms | 12,881 ms |

三次两级运行都是 55 个 pass，batch 组成相同，只有时间被推后。这个负载受 `max_sequences` 限制，所以 batch 组成不变是预期结果。

调度器不感知一级容量，有两处证据：
- **KV 容量被放开**：`scenarios.py` 的 `config_for` 把 KV 容量固定为 40,000 块（vLLM 每块 64 token，共 256 万 token），注释写明目的是让 AISim 的单级内存检查不起作用。这个数是手工设定的，与一级、二级容量都无关。
- **一级溢出中止仿真**：一级空间不够时，`make_room` 先淘汰专家和热 KV，都淘汰完就报错。实测 Flash、32 个 60K 请求、一级 8 GB：运行中途报 `tier 1 overflow while reserving a layer's non-expert weights: needs 8.02 GB, has 8.00 GB`，引擎进入 poisoned 状态，整次仿真失败。真实系统会推迟准入或抢占，这里没有对应逻辑。

树外的事后重计时实现 `src/two-tier-dram`（`--stack two_tier_dram`）仍在仓库里，[初期目标记录](../agent-two-tier-dram-initial-goal/)的“AISim 扩展”一节仍在描述它。没有结果引用它，但应删除或明确标为废弃。

## 第 2 条：硬件参数

| 检查项 | 结论 | 证据 |
| --- | --- | --- |
| 参数出处 | **不通过** | `systems/exi_3ddram.yaml` 文件头写明来源是 EXI-3DDRAM 内部架构表。标 TABLE 的字段 6 个，标 ASSUMPTION 的 10 个 |
| 真实产品预设 | **不通过** | [硬件调研](../../related-work/two-tier-dram-hardware-parameters/)给出了 GH200、GB200、Vera Rubin、MI355X 的可填数值，但列为后续工作，没有任何运行使用 |
| 一、二级之间的互连 | **不通过** | `link_bytes_per_ms = tier2_bandwidth_gbps × copy_efficiency × 1e6`，没有互连带宽项 |
| 数值依据 | 部分 | 复制效率 0.8 和每次传输 2 µs 类比自 GH200 实测与 PCIe，不是 EXI 的测量。18 TB/s 一级和 2.2 TB/s LPDDR6 没有已发布产品支撑（调研结论） |
| EP8 结果的取值 | **不通过** | `ep.py` 的 10 个两级运行中，只有 `survey` 用 1.1 TB/s × 0.8、2 µs；其余用 EXI 图示值 2.2 TB/s × 1.0、开销 0 |
| 计算模型 | **不通过** | 所有运行用 `database_mode: SOL` 的解析 roofline，访存效率 1.0、固定延迟 0；`sweep.py` 的 `FIXED` 注明调研建议的 0.8 未应用 |

## 第 3 条：可容纳场景

| 检查项 | 结论 | 证据 |
| --- | --- | --- |
| 扫描点全部强制检查 | 通过 | 4,608 个点中 4,368 个完成且 `tier2_feasible` 为真，240 个被拒绝（96 个二级 128 GB，144 个 Pro 一级放不下常驻权重）。没有反事实点（实测） |
| EP8 全部强制检查 | 通过 | 10 个两级运行的 `config.json` 都是 `enforce`、192 GB，每卡 128.7 GB；128 GB 运行被拒绝 |
| 二级容量在硬件可选范围内 | **不通过**（单卡 Pro） | 约 2,112 个完成的 Pro 点（按计划对称推算）用 805.7 GB 二级，超出架构表的 64–512 GB。按要求应去掉单卡 Pro，只保留 Flash 和 EP8 |
| 二级容量检查包含 KV | **不通过** | `card_weights_bytes` 只算权重。实测 Flash 二级 148.5 GB、权重 148.486 GB，余量 0.014 GB，同一次运行写回了 4.6 GB 的 KV |
| 一级峰值预算 | 部分 | scratch、全局权重、非专家权重、常驻 KV、专家、热 KV、待写回 KV 都计入并强制；通信缓冲未计入；scratch 4 GB 是假设 |
| 长上下文 | 未运行 | `context_length` 为 131,072，扫描最长输入 32,768；200K 和 1M 没有跑过 |
| 732 GB 与 805.7 GB 对齐 | 未检查 | 本次没有逐项核对模型清单 |
| 替代模型 | 确认受限 | `build_profile` 只接受 DeepSeek-V4 结构，可用的只有 Pro 和 Flash |

`scenarios.py` 的默认配置 `BASE_TWO_TIER` 仍是 `tier2_capacity_check: counterfactual`，它的 7 个场景都是反事实运行，输出还在 `output/` 下，README 的配置示例也写着 `counterfactual`。这些没有出现在文档结果里，但脚本应改成可行配置或删除。`output/sweep/points` 下另有 4,404 个不在当前计划内的旧缓存文件，其中有记录为 `0366873+dirty` 的点。

## 第 4 条：仿真完整性

| 因素 | 代码 | 测试 | 实测灵敏度 |
| --- | --- | --- | --- |
| 逐层预取与计算重叠 | `pass_inner` 的 `LayerPrefetch` 分支 | 无专门测试 | 36 GB 下等非专家权重 1,831 ms；96 GB 常驻为 0 |
| 共享链路排队 | `enqueue`、`pick`、`progress_link` | 间接 | `fifo` 对 `demand_first`：等待从非专家权重转到 KV 和专家，完成时间 12,210 对 11,940 ms |
| KV 写回 | `Kind::Writeback` | `writeback_runs_between_passes` | 链路上有 3.5–4.9 GB 写回量 |
| prefill 从二级读前缀 KV | `Kind::PrefillKv` | 间接 | 链路上有 0.4–0.5 GB |
| 每次传输开销 | `link_overhead_ms` | 无 | 0 到 0.1 ms：完成时间 11,920 到 12,960 ms，单调 |
| 二级带宽 | `link_bytes_per_ms` | `unlimited_link_returns_the_native_time` | 1.1、2.2、4.4 TB/s：11,940、7,450、5,213 ms，单调 |
| 专家缓存策略 | `Lru`、`LayerPartition` | 4 个测试 | 见初期目标记录 |
| 专家路由 | **合成** | — | 见下文 |
| 热 KV 与 top-k | **合成** | — | 见下文 |
| 专家预取 `last_step` | 有 | `prefetch_stays_within_a_layers_share` | **无效果**：Pro 36 GB、Pro 96 GB、Flash 36 GB 三个锚点上完成时间都不变 |
| 复制写入与计算读取争用一级带宽 | **无** | — | 只报告一个上界 `contention_ub_ms`，不计入时间 |
| EP 通信与搬运争用 | **无** | — | 链路是每个 rank 独立的，与 AISim 的通信定价无关 |
| 直接读二级 | **无** | — | 模型要求先复制到一级 |
| 传输并发 | **无** | — | 一条串行链路，一次一个传输 |

以上灵敏度数字取自缓存的扫描点：Pro，4 个 16K 请求错峰到达，输出 64 token，LRU。

几项具体问题：
- **专家路由是合成的**。`two_tier.rs` 文件头写明选中的 top-k 和路由专家都是合成的：每个请求以配置的概率保留上一步的选择，其余均匀抽取。prefill 用期望去重数公式。真实路由的热专家倾斜没有体现，而它决定专家缓存的收益。结果对这个参数很敏感：Pro 96 GB 常驻时，`expert_overlap` 从 0 到 1，完成时间从 9,917 降到 6,871 ms（−31%）。
- **当前负载评估不了热 KV 缓存**。热 KV 命中从 0 次变到 6,421,206 次，完成时间都是 11,940 ms；等 KV 只占 9 ms。原因是 KV 条目字节数小：按需取 KV 的搬运量只有几 GB，而同类扫描点的专家搬运量有数千 GB。
- **时间分配是近似的**。`pass_inner` 把 AISim 给出的 pass 总时间按固定比例平均分到每一层。比例取自 batch 1、65,536 上下文的一次 decode，也用于 prefill pass。总计算时间不变，受影响的是预取能利用的窗口。
- **一级带宽没有扫描**。计算通过系统文件的 `mem_bw` 读一级，只有 18 TB/s 一个值。
- **运行间不确定性**。只改二级容量（min 对 1,024 GB）不应影响结果，但 Flash 的完成时间为 2,432 对 2,435 ms，专家命中数也不同。差异约 0.1%，小于上面所有效应。

测试结果：`cargo test -p aisim-core --lib two_tier` 18 个通过；`cargo test -p aisim-core --test two_tier_dram` 2 个通过。初期目标记录写的 11 个单元测试已过时。本次没有运行 aisim-core 的全部库测试。

## 第 5 条：真实 trace

| 检查项 | 结论 | 证据 |
| --- | --- | --- |
| 请求到达与长度 | **不通过** | `run_aisim` 和 `ep.py` 的 `run` 用脚本写出 mooncake 格式文件。扫描是 4 个请求，EP8 是 8 或 32 个；长度固定为 4,096、16,384 或 32,768，输出 8 或 64 |
| 真实 trace 文件 | **不通过** | 在 i163v 的 `~`、`/data`、`/mnt` 下（深度 6）没有找到 Mooncake、BurstGPT 或 Azure 的 trace 数据文件 |
| 加载能力 | 具备 | AISim 的 `TraceFormat` 支持 `mooncake`、`mooncake-delta`、`agentic_mooncake`，真实 Mooncake trace 可以直接加载 |
| 专家路由 trace | **不通过** | 引擎没有读入路由记录的入口。`src/kv-trace` 是 AISim KV 事件的回放可视化，不采集路由 |
| top-k 选择 trace | **不通过** | 同上，由 `pick_set` 合成 |
| 前缀共享 | **不通过** | 每个请求的 `hash_ids` 都不同，没有任何前缀复用 |

## 建议的修复顺序

第 1、2 步已完成，见[真实 Mooncake 请求 trace 与 GB200 参数下的结果](../two-tier-dram-mooncake-trace/)。请求负载已换成真实 trace，硬件已换成 GB200 的产品参数和 AISim 实测性能数据库；专家路由和 top-k 仍是合成的，GB200 的复制带宽是推算值。

1. 换负载：用公开 Mooncake trace 的一个时间窗口替换脚本生成的请求，记录来源、版本和窗口。
2. 换硬件：按硬件调研里的 GH200 或 GB200 预设加系统文件和 `two_tier_dram` 取值，计算改用 AISim 自带的实测性能数据库，链路取 min(二级带宽, 互连单向带宽)。
3. 去掉单卡 Pro：单卡只保留 Flash，Pro 只在 EP8 下出现。二级容量检查加上 KV。
4. 路由与 top-k：给引擎加读入路由记录的入口。拿不到真实记录之前，结论只能写成对 `expert_overlap` 的区间。
5. 让调度器感知一级容量：一级放不下时推迟准入，而不是中止仿真。
6. 清理：删除或废弃 `src/two-tier-dram` 和 `scenarios.py` 的反事实场景，清掉旧缓存点。

## 实验记录

- **代码**：AISim `436cf43`（分支 `two-tier-dram-engine`），Mirage `7416213`（分支 `two-tier-dram-replay`），i163v，无本地修改。
- **缓存数据分析**：`/tmp/tt-audit/analyze.py`，读 `src/two-tier-dram-engine/output/sweep/points` 中计划内的 4,608 个点。
- **新实验**：`/tmp/tt-audit/exp.py`（调度反馈）和 `/tmp/tt-audit/exp2.py`（一级压力），都通过 `scenarios.run_aisim` 调用 `aisim predict --stack engine`。模型 DeepSeek-V4-Flash，`hardware: exi_3ddram`，SOL，二级 148.5 GB 强制检查，1.1 TB/s × 0.8，2 µs，种子 0。输出在 `/tmp/tt-audit/runs` 和 `exp.json`、`exp2.json`。
- **一级压力结果**：32 个 60K 请求每 10 ms 到一个。原生 27,351 ms；一级 36 GB 为 32,678 ms；12 GB 为 32,724 ms；8 GB 中途溢出失败；6 GB 启动时被拒绝。
- **局限**：新实验各跑一次，没有重复；脚本和输出在 `/tmp`，没有进仓库；负载同样是脚本生成的，只用于验证机制，不是研究结果。`render.py`、`template.html` 和 `two_tier.rs` 的 trace 输出部分没有细读。
