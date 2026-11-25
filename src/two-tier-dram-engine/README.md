# two-tier-dram-engine：两级 DRAM 闭环实验（AISim 引擎内）

两级 DRAM 的第二种实现：把模型写进 AISim 的 vLLM 调度器，等待直接计入每个 pass 的时长，并推迟下一个 pass（闭环）。第一种实现 `src/two-tier-dram` 是树外 stack，事后重计时，只支持单请求；这里支持多请求、batch 和排队。

引擎代码在 AISim 子模块的分支 `two-tier-dram-engine` 上（i163v 的 `~/Mirage/src/aisim`，未推送）。本目录只有实验脚本和回放页面。

## AISim 中的改动

| 文件 | 改动 |
| --- | --- |
| `crates/core/src/engine/two_tier.rs`（新增） | 两级模型：一级账本、专家 LRU、top-k KV LRU、共享链路（按需优先或 FIFO、每次传输固定开销）、逐层状态机、逐 pass 的 JSONL trace |
| `crates/core/src/engine/scheduler/vllm/core.rs` | `schedule_pass` 记下本 pass 的 prefill 块与 decode 请求；`resolve_pass` 在 AISim 定价后调用两级模型，用它返回的结束时间替换原生结束时间 |
| `crates/core/src/engine/config.rs`、`common/protocols.rs`、`scheduler/rank.rs`、`mod.rs` | `EngineConfig.two_tier_dram` 字段、校验与传递 |
| `python/aisim/src/aisim/two_tier.py`（新增） | `kv_cache.two_tier_dram` 的配置模型；从 AISim 的模型注册表和 op-level 性能模型生成 profile（层结构、字节数、attention／MoE／其余的时间比例） |
| `python/aisim/src/aisim/config/engine.py`、`compiler.py` | 配置字段、互斥校验、把 profile 写进 rank payload |
| `crates/core/tests/two_tier_dram.rs`（新增） | replay 级测试：链路无限快时与原生时间线一致；链路慢时等待推迟后续请求的准入 |

### 每个 pass 发生什么

1. AISim 照常定价，得到这个 pass 的时长（已考虑 batch 和上下文）。
2. 两级模型按 profile 的比例把这段时间分到每层，再逐层模拟：
   - CSA 层：每个 decode 请求选 top-k，缺失的条目从二级取入。
   - prefill 块：从二级读取前缀 KV。
   - MoE：本 pass 所有 token 路由到的专家取并集，缺失的从二级取入。
3. 返回的结束时间就是这个 pass 的结束时间，调度器据此安排下一个 pass。
4. 写回和预取在 pass 之间继续在链路上进行。

prefill 块有 N 个 token 时，每层路由到的专家数取期望去重数 `E·(1-(1-k/E)^N)`，几千个 token 就接近全部 384 个。

## 构建

```sh
cd src/aisim && git checkout two-tier-dram-engine
export PATH=$HOME/.cargo/bin:$PATH
cd python/aisim && uvx --from "maturin>=1.12,<2" maturin develop --release --uv   # 约 19 分钟
```

## 配置

```yaml
engine:
  workers:
    aggregated:
      parallelism: {replicas: 1, tensor: 1, attention_data: 1}
      kv_cache:
        capacity: {type: fixed, blocks: 40000}   # 现在表示二级里的 KV 容量
        two_tier_dram:
          tier1_gb: 96
          link_gbps: 64
          trace_path: ./two-tier.jsonl           # 每个 pass 一行；前 trace_passes 个带逐层细节
```

字段：

| 字段 | 默认 | 含义 |
| --- | --- | --- |
| `tier1_gb` / `scratch_gb` / `tier2_gb` | 96 / 4 / 2048 | 一级容量、其中的 scratch、二级容量 |
| `link_gbps` / `link_overhead_ms` | 64 / 0.01 | 链路带宽、每次传输的固定开销 |
| `link_policy` | `demand_first` | 也可以是 `fifo` |
| `base_weights` | `resident` | 也可以是 `layer_prefetch`（方案 A） |
| `expert_cache_gb` | 自动 | 不填则用一级剩余空间 |
| `expert_overlap` / `topk_overlap` | 0.5 / 0.75 | 合成的跨步重合度 |
| `expert_prefetch` | `none` | 也可以是 `last_step`（只用空闲位置） |
| `hot_kv_entries` | 65536 | 热 top-k KV 缓存条数 |
| `profile_context_tokens` | 65536 | 测 attention／MoE 时间比例时用的上下文长度 |
| `trace_path` / `trace_passes` | 不写 / 200 | trace 文件；带逐层细节的 pass 数 |

限制：
- 只支持 vLLM、TP1，以及 DeepSeek-V4 一类模型。
- 不能与 `host_offload`、`hicache`、`g3_offload`、`kvcr`、`state_cache` 或投机解码同时使用。

## 场景与回放

```sh
python3 src/two-tier-dram-engine/scenarios.py --show
```

脚本运行 6 个场景，每种负载另跑一次不带 `two_tier_dram` 的原生版本。它检查跨场景关系，然后生成 `output/two-tier-dram-engine-replay.html`。

页面包括：
- 每个请求在两级下与原生下的时间线；
- pass 列表；
- 带逐层细节的 pass 的动画：一级占用、61 层缓存概览、当前层的专家和 KV、共享链路。
