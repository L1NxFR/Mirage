---
author: Claude
title: AISim KV Cache 行为回放：G1/G2 block 级 trace
description: 用 AISim 原生 replay artifacts 记录一次 G1⇄G2 offload 的 block 级事件，并做成可逐帧播放的动画，核对 store、load、准入与驱逐的建模方式。
date: 2026-11-23T01:15:01+08:00
lastmod: 2026-11-23T01:53:32+08:00
content_lang: zh-CN
draft: true
show_toc: true
weight: 2
tldr: |
  `aisim predict` 能导出 block 级的 G1/G2 事件，不需要改上游代码；下方可直接播放 7 个场景的动画。常规场景证实：G2 命中必须先完成 H2D 才能准入，传输时间全部计入 TTFT；H2D 前先在 G1 预留目标 block；D2H 在后台完成；只有写满的 block 会被存储或复用。极端场景发现：D2H 稍慢于请求间隔时，复用仍在被 D2H 读取的 G1 block 会触发栅栏，推迟计算或 H2D（TTFT 2 → 29 / 58 ms）；整块对齐的 prompt 完全命中时，H2D 搬回的最后一块会被整块重算；G2 小于一次 store 时一块都不存；prompt 大于 G1 时直接拒绝。fixed timing 下复用看不出收益，本次只验证因果链路。
---

## 研究问题

[上一篇能力报告]({{< relref "Current AI-SIM capabilities to support multi-tier simulation of KV Cache storage.md" >}}) 和后续的代码阅读，都只是静态分析：G1/G2 的容量、store/load 时序、准入与驱逐。本次实际运行 AISim，回答两个问题：

1. 能否在不改上游代码的前提下，拿到逐 block、带虚拟时间戳的 KV 行为 trace？
2. trace 中的行为与静态分析的结论是否一致？包括 store 时机、H2D 与准入的先后、驱逐对象。

本次不考虑 PP>1。

## 方法

AISim 运行时自带 `run_replay_with_artifacts_json`。它与 CLI 默认调用的 `run_replay_json` 共用同一个 replay 循环，额外返回以下数据：

- `kv_events`：G1 与 G2（`host_pinned`）中 block 的可见和移除。
- `host_offload_events`：`store_prepared`、`store_submitted`、`store_completed`、`load_queued`、`load_completed`、`evicted`，带 `completes_at_ms`。

工具放在 `src/kv-trace/`，用法见该目录的 README：

| 文件 | 作用 |
| --- | --- |
| `scenarios.py` | 场景目录：生成 config 与 mooncake trace，逐个运行，按预期 TTFT 与 G2 复用量做回归检查，再渲染 |
| `capture.py` + `_hook/sitecustomize.py` | 走正常的 supervised `aisim predict`；在 AISim 的子进程里把 `run_replay_json` 换成带 artifacts 的版本，保存 `trace.json` |
| `render.py` + `template.html` | 用原生事件重建 G1/G2 槽位与请求阶段，断言占用不超过容量，生成可嵌入的离线 HTML 动画 |

```sh
python3 src/kv-trace/scenarios.py --publish dashboard/site/content/Attachments/kv-cache-replay.html
```

这条路径受 artifact 路径本身的限制，只支持 aggregated topology，详细 artifact 只在单 DP rank 上有意义。

## 配置

场景沿用上游示例 `examples/cli/agentx-g2-local.yaml` 的引擎参数，请求改写为 mooncake trace（每行一个独立请求，便于构造并发）。常规请求序列：

- R1：hash [1,2,3]。
- R2：hash [11,12,13]，用来挤掉 R1 在 G1 的前缀。
- R3：**R1 的下一轮**。输入 = R1 的 9 个 prompt token + 1 个输出 token + 2 个新 token = 12 token，hash [1,2,30]：与 R1 共享前 2 个整块，第 3 块含本轮新内容，是新 block。
- R4：hash [21,22,23]。

除 R3 外每个请求 9 个 token 输入，全部 1 个输出，到达间隔 100 ms。动画在请求名下方标出"↳ R1 的下一轮"，关系由共享的 block hash 自动推出。

公共参数：
- vLLM 后端，TP1。
- block_size 4，`bytes_per_token` 250000，即每 block 1 MB。
- G1 固定 3 个 block。
- fixed timing：prefill 2 ms，decode 1 ms。
- G2 为 `dp_rank_local`，D2H 1 GB/s，首字节延迟 0。

动画顶部用黄色标出每个场景相对基线改动的 AISim 参数（显示"基线 → 本场景"）。

| 场景 | 相对基线的改动 |
| --- | --- |
| 基线 | 无（G2 8 block，D2H/H2D 1 GB/s） |
| G2 压力 + 慢 H2D | G2 4 block，H2D 0.05 GB/s |
| 慢 D2H | D2H 0.016 GB/s（存 2 MB 要 125 ms，比请求间隔 100 ms 稍长） |
| G2 小于一次 store | G2 1 block |
| 整块对齐完全命中 | prompt 8 token（2 个整块），G1 2 block；R3 原样重发 R1 的 prompt（不是下一轮） |
| H2D 与并发请求争抢 | max_sequences 2，H2D 0.05 GB/s，R4 改为 210 ms 到达的 4 token 请求 |
| prompt 大于 G1 | G1 2 block，只有 R1 |

## 实验与观察

下面的动画可直接播放：选场景，点 ▶ 播放，或用 ⏭ / 方向键逐个事件前进。每个格子下方的小方块是该 block 已填的 token 数。

{{< embed-html src="../Attachments/kv-cache-replay.html" title="AISim KV Cache 行为回放（7 个场景）" height="1000" >}}

### 常规场景结果

| 请求 | 基线 TTFT | G2 压力场景 TTFT | 首次准入复用 |
| --- | --- | --- | --- |
| R1 | 2 ms | 2 ms | 无 |
| R2 | 2 ms | 2 ms | 无 |
| R3 | 4 ms | 42 ms | 8 token 来自 G2 |
| R4 | 2 ms | 2 ms | 无 |
| 平均 | 2.5 ms | 12 ms | |

### 基线事件序列（摘自 `trace.json`）

| t (ms) | 事件 | 含义 |
| --- | --- | --- |
| 0 | `store_prepared` R1·b0, R1·b1 | 调度这一步就选出 2 个完整 prompt block，在 G2 预留为 PendingStore；第 3 个 block 未写满，不存 |
| 2 | G1 `stored`；`store_submitted`，`completes_at_ms=4` | prefill pass 结束，block 落定可命中；D2H 2 MB / 1 GB/s = 2 ms |
| 4 | `store_completed`；`host_pinned stored` | G2 block 变为 Resident |
| 102 | G1 `removed` R1·b0, R1·b1；G1 `stored` R2 | R2 需要 3 个 G1 block，驱逐 R1 的前缀 |
| 200 | G1 `removed` R2·b1；`load_queued`，`completes_at_ms=202` | R3 在 G2 命中：先驱逐 1 个 block，在 G1 预留 2 个目标 block，再排队 H2D |
| 202 | `load_completed`；G1 `stored` R1·b0, R1·b1；`store_prepared` R3·b2 | H2D 完成，`first_admit_ms=202`，R3 这时才准入；本轮新写的第 3 块在 G2 预留 |
| 204 | G1 `removed` R2·b0；G1 `stored` R3·b2；R3 输出 | 只计算第 3 块的 4 个 token（R1 的最后 1 个 token + 本轮 3 个），写满后落定 |
| 205 | `store_completed` R3·b2 | G2 里接上这段会话的前缀链 R1·b0 → R1·b1 → R3·b2 |
| 300–304 | R4 的驱逐、store 与 D2H | R4 驱逐 G1 里的 3 个缓存 block；G2 共 7/8 block，没有发生驱逐 |

G2 压力场景的差异：
- H2D 窗口变为 200→240 ms，R3 在 240 ms 准入，242 ms 输出。
- 240 ms 存 R3·b2 时 G2 已满（4/4），驱逐 R2·b1；300 ms 存 R4 时驱逐 R2·b0 和 R1·b1。R1·b1 被逐出后，R3·b2 留在 G2 却失去父块；按前缀查找遇缺即停，它已无法命中（推断，本场景没有请求去查它）。

### 为什么 9 token 的请求占 3 个"写入中"格子

一个 9 token 的 prompt 需要 ceil(9/4) = 3 个 G1 block：引擎的 `admission_requirement` 按 `known_tokens.div_ceil(block_size)` 分配（`kv_manager/vllm_backend.rs:515`）。trace 印证了这一点：R2 在 102 ms 准入时驱逐了 R1 的 2 个 block，而 G1 当时还空 1 格；如果只要 2 个 block，驱逐 1 个就够了。3 个 block 中前 2 个写满、prefill 结束时落定并存入 G2；第 3 个只有 1 个 token，不落定、不存 G2，请求结束时释放。动画用 token 小方块和"未写满·不落定"标出这一块。

### 极端边界场景

| 场景 | TTFT（R1–R4） | 观察 |
| --- | --- | --- |
| 慢 D2H | 2 / 29 / 58 / 22.5 ms | 同一个栅栏出现三次：R2 复用 R1 的 D2H 源 block，prefill 等到 127 ms；R3 的 H2D 目标是 R2 的 D2H 源，H2D 从 254 ms 才开始传；R4 驱逐正在存的 R3·b2，等到 320.5 ms。准入都没有被挡 |
| G2 小于一次 store | 2 / 2 / 2 / 2 ms | 每次 store 都报 `capacity_retry`（`structurally_unfittable=true`），G2 从未写入，也不会只存一部分。R3 无法恢复，只能从头重算 |
| 整块对齐完全命中（R3 重发 R1） | 2 / 2 / 4 ms | 完全命中时必须重算最后一个 token，按整块回退，只记复用 4 token（`apply_prefix_recompute`）。但 H2D 搬回了 2 个 block，第 2 块随后被整块重算，1 MB 的 H2D 是浪费。真实 vLLM connector 是否同样如此，待核实 |
| H2D 与并发请求争抢 | 2 / 2 / 42 / 2 ms | R3 的 2 个 H2D 目标 block 占住 G1 的 2/3 长达 40 ms，但不阻塞别人：R4 在 210 ms 直接准入，比先到的 R3 先完成。R3 在 240 ms 准入时反过来驱逐 R4 刚落定的 block |
| prompt 大于 G1 | 被拒绝 | 请求在到达时刻被拒绝（`rejected`），没有任何 KV 事件，不会借 G2 分批。AISim 以退出码 1 结束并提示 No requests completed，这是预期结果 |

### 与静态分析的对照

| 静态结论 | trace 证据 | 判定 |
| --- | --- | --- |
| G2 命中时先完成 H2D 再准入，H2D 时间计入 TTFT | `first_admit_ms` 等于 `load_completed` 的时刻（202 / 240）；TTFT 4 → 42 ms | 一致 |
| `start_load` 先在 G1 预留目标 block，空间不足时驱逐 | 200 ms 时 G1 `removed` 与 `load_queued` 同时发生 | 一致 |
| store 在调度时选 block、pass 结束时提交 D2H，完成后才算 Resident | `store_prepared` 0 → `store_submitted` 2 → `store_completed` 4 | 一致 |
| 私有链路耗时 = 字节数 / 带宽，首字节延迟 0 | 2 MB @ 1 GB/s = 2 ms；@ 0.05 GB/s = 40 ms | 一致 |
| v0.24 默认只存完整的 prompt block | 每个请求只存 2 个 block，第 3 个未写满的 block 不存 | 一致 |
| G2 默认 `CohortLru` 驱逐 | 压力场景中驱逐的是最久未访问的 R2 block | 与 LRU 一致；本场景不足以区分 cohort 细节 |

### 栅栏是什么

"慢 D2H"场景里的栅栏，就是 **D2H 还没读完时复用它的源 block** 所触发的读后写依赖（AISim 的 source-reuse fence）：

- **创建**：G1 block 被选为 store 源时挂上依赖，依赖 ID 就是这次 D2H 的 transfer id（`cache/vllm_block_pool.rs:47-63`、`attach_source_reuse_dependency` :1113）。
- **不挡分配**：默认 connector `offloading_v0_24` 下，源 block 照常回到 LRU，可被驱逐、复用，依赖跟着容量转给新主人（`take_fresh_capacity` :1289-1296）。准入和分配当场完成。
- **挡写入**：新主人若拿它来计算，`fence_allocation` 把整个 rank 的 `compute_not_before_ms` 抬到 D2H 完成时刻（`scheduler/vllm/host_offload.rs:1055-1076`）；若拿它当 H2D 目标，`start_load` 把这次 H2D 的开始推迟到 D2H 完成（:631-641）。
- **解除**：D2H 完成时 `satisfy_source_reuse_dependency`（:1161）。

栅栏是 rank 级的：同一 pass 里无关请求也会一起推迟。`connector: simple_cpu_v0_32` 或 `scope: cluster_shared` 改用 holding 模式，源 block 在 D2H 完成前不进入空闲池或 LRU，表现为请求排队、无法准入，而不是"已准入·栅栏"（`config.rs:736-749`、`host_offload.rs:430-434`）。`offloading_v0_24` 建模成 fencing 而非 holding，仓库中没有找到依据，也尚未对照 vLLM 源码核实。

G2 里的 PendingStore 是另一套机制：它只影响 lookup（`offloading_v0_24` 下返回 Deferred），与 G1 栅栏无关。

### 推断项

`render.py` 用原生事件重建槽位占用，7 个场景都通过了容量断言。以下三点是推断，页面中已标注：

1. **"写入中"block**：AISim 不为尚未落定的 G1 block 发事件。数量按引擎准入规则推出：`token_blocks − max(复用块, H2D 载入块)`；整块对齐完全命中时，载入但不计复用的那块画成"整块重算"。
2. **G1 驱逐时刻**：vLLM 在 pass 结束时发布 G1 驱逐事件，例如 204 ms，但驱逐发生在导致它的那次准入，例如 202 ms，动画画在准入时刻。在同一时刻、排在该 pass 自身 `stored` 之后发布的驱逐属于后续调度（如慢 D2H 场景 200 ms 为 H2D 预留的驱逐），保持原时刻。按发布时刻绘制会让 G1 占用超过容量。
3. **传输区间与栅栏**：传输条只在 `completes_at_ms − 字节/带宽` 之后推进，此前是排队或等栅栏；"已准入·栅栏"阶段是准入到 `first_token − prefill_ms` 之间。

## 局限

- **复用收益未体现**：fixed timing 下，重算 1 个 token 和重算 9 个 token 都是 2 ms，所以 G2 恢复只会增加 H2D 时间。本次只验证因果链路，不说明 offload 是否划算。要评估收益，需要换用随 token 数变化的 timing 模型和真实规模的模型。
- **覆盖范围窄**：只有 1 个 worker、单 DP rank、私有 G2、输出长度 1。没有覆盖 decode 阶段的 block 增长、抢占、`cluster_shared`、G3、P/D 和 KVCR。
- **检查范围**：`scenarios.py` 对每个场景断言 TTFT、G2 复用量和是否拒绝，`render.py` 断言槽位占用不超过容量，页面在浏览器中逐事件核对过。这些属于冒烟测试与回归检查；未运行 AISim 自带测试。
- **代码版本**：Mirage `19dfc18` 加本地未提交改动。`src/aisim` 是 submodule 指针 `c85b086`，但本地目录不是 git 检出，无法确认工作树是否干净，按当前源码快照对待；aisim 版本 0.15.0。环境为 Darwin arm64、Python 3.12.12（uv）、cargo 1.100.0。本次构建在 `src/aisim/python/aisim/.venv` 下生成了虚拟环境。trace 回放，无随机种子依赖。
- **产物位置**：`src/kv-trace/output/`，包含各场景的 config、trace、`trace.json` 和 AISim 输出，可由 `scenarios.py` 重新生成；嵌入页面的副本在 `Attachments/kv-cache-replay.html`。

## 结论与下一步

结论：
- AISim 现有的 artifact 接口足以拿到 G1/G2 的 block 级 trace。
- 常规场景的行为与静态分析一致：先加载再准入、预留优先、D2H 在后台进行、只复用完整 block、G2 按 LRU 驱逐。
- 极端场景暴露了静态阅读不易看出的耦合：D2H 只要稍慢于请求间隔，就会通过源 block 栅栏推迟后续请求的计算和 H2D；对齐 prompt 完全命中会产生无效 H2D；G2 的 LRU 会先逐出父块，留下无法命中的子块。

下一步：
1. 换用 AIC 或其他随 KV 长度变化的 timing 模型，按模型实际规模设置 `bytes_per_token`，评估 G2 复用相对重算的收益与带宽临界点。
2. 扩展 `render.py`，支持多输出 token 的 decode 过程和抢占，覆盖 decode 阶段的 block 增长。
3. 用 `cluster_shared` 多 worker 场景，观察共享池 max-min 带宽分配。这需要先确认 artifact 路径在多 worker 下的限制。
4. 对照 vLLM offloading connector 源码，核实两点：整块对齐完全命中时是否也会先 H2D 再重算最后一块；store 未完成时源 block 是靠 stream 同步复用（fencing）还是延迟释放（holding）。若不一致，在 AISim 记录差异。
