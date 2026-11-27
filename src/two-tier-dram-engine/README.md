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
  hardware: exi_3ddram                       # 计算按一级带宽定价
  ais_perf_model: {estimation_mode: op_level, database_mode: SOL, systems_paths: [src/two-tier-dram/systems, default]}
  workers:
    aggregated:
      parallelism: {replicas: 1, tensor: 1, attention_data: 1}
      kv_cache:
        capacity: {type: fixed, blocks: 40000}   # 现在表示二级里的 KV 容量
        two_tier_dram:
          tier1_gb: 36
          tier2_bandwidth_gbps: 2200
          tier2_capacity_check: counterfactual   # 805.7 GB 的模型放不进 128 GB 二级
          trace_path: ./two-tier.jsonl           # 每个 pass 一行；前 trace_passes 个带逐层细节
```

字段（默认值为 EXI-3DDRAM 图示配置）：

| 字段 | 默认 | 含义 |
| --- | --- | --- |
| `tier1_gb` / `scratch_gb` / `tier2_gb` | 36 / 4 / 128 | 一级容量、其中的 scratch、二级容量 |
| `tier2_bandwidth_gbps` / `copy_efficiency` | 2200 / 1.0 | 二级标称带宽；有效复制带宽是两者的乘积 |
| `link_overhead_ms` | 0 | 每次传输的固定开销 |
| `tier2_capacity_check` | `enforce` | 二级放不下权重时拒绝运行；`counterfactual` 照常运行并标为不可行 |
| `link_policy` | `demand_first` | 也可以是 `fifo` |
| `base_weights` | `resident` | 也可以是 `layer_prefetch`（逐层轮换非专家权重） |
| `expert_cache_gb` | 自动 | 不填则用一级剩余空间 |
| `expert_overlap` / `topk_overlap` | 0.5 / 0.75 | 合成的跨步重合度 |
| `expert_prefetch` | `none` | 也可以是 `last_step`（只用空闲位置） |
| `expert_policy` | `lru` | `lru`：全部层共用一个最久未用列表；`layer_partition`：每层平分专家槽位，层内最久未用，超出份额的专家用完即弃 |
| `hot_kv_entries` | 65536 | 热 top-k KV 缓存条数 |
| `profile_context_tokens` | 65536 | 测 attention／MoE 时间比例时用的上下文长度 |
| `seed` | 0 | 合成路由与 top-k 的种子 |
| `trace_path` / `trace_passes` | 不写 / 200 | trace 文件；带逐层细节的 pass 数 |

限制：
- 只支持 vLLM、每卡 TP1，以及 DeepSeek-V4 一类模型；专家并行要求 `moe_expert` 等于 `attention_data`。
- 不能与 `host_offload`、`hicache`、`g3_offload`、`kvcr`、`state_cache` 或投机解码同时使用。

## 场景与回放

```sh
python3 src/two-tier-dram-engine/scenarios.py --show
```

脚本运行 8 个场景（其中一个预期被拒绝），每种负载另跑一次不带 `two_tier_dram` 的原生版本。它检查跨场景关系，然后生成 `output/two-tier-dram-engine-replay.html`。

页面包括：
- 每个请求在两级下与原生下的时间线；
- pass 列表；
- 带逐层细节的 pass 的动画：一级占用、61 层缓存概览、当前层的专家和 KV、共享链路。

## 参数扫描

```sh
python3 src/two-tier-dram-engine/sweep.py            # 默认 32 并发
python3 src/two-tier-dram-engine/sweep.py --limit 6 --jobs 6 --out /tmp/sweep-smoke   # 冒烟测试
```

`sweep.py` 的 `AXES` 列出页面上的全部参数：
- 核心参数取全组合：模型、到达方式、输入长度、输出长度、一级容量、非专家权重放置、二级标称带宽、专家缓存策略（1728 个点）。
- 其余参数在锚点上逐个变化。锚点是每个模型 × 每种负载 × 一级 36 GB 逐层轮换／96 GB 常驻 × 两种缓存策略，二级 1.1 TB/s × 0.8；每个锚点另有一个 2.2 TB/s × 0.4 的点（另 2880 个点）。
- 每个模型的每种负载另跑一次原生版本。

模型是 AISim 注册表里两个 DeepSeek-V4 结构的模型（`two_tier_dram` 只支持这一类）：

| 模型 | 层数 | 每层专家 | 单个专家 | 非专家权重 | 单卡合计 | 最小可行二级 |
| --- | --- | --- | --- | --- | --- | --- |
| `deepseek-ai/DeepSeek-V4-Pro` | 61 | 384，top 6 | 33.0 MB | 32.0 GB | 805.7 GB | 805.7 GB |
| `deepseek-ai/DeepSeek-V4-Flash` | 43 | 256，top 6 | 12.6 MB | 10.0 GB | 148.5 GB | 148.5 GB |

`DeepSeek-V4.1-Flash` 的模型类没有压缩比和 top-k 索引字段，`two_tier_dram` 拒绝它。

所有点都开启二级容量强制检查（`tier2_capacity_check: enforce`），没有反事实点。二级容量默认取 `min`，即放得下该模型单卡权重的最小值（`sweep.py` 的 `MIN_TIER2_GB`；Pro 的 805.7 GB 超出架构表的 64–512 GB）；128 GB（EXI 图示值）的点应被拒绝。其余默认值取[硬件调研](../../dashboard/site/content/related-work/two-tier-dram-hardware-parameters.md)的 EXI 修正基线：二级 1.1 TB/s、复制效率 0.8、每次传输 2 µs。EXI 图示值（2.2 TB/s、1.0、0）作为扫描取值保留。

每个点是一次真实的 `aisim predict --stack engine` 运行。结果缓存在 `output/sweep/points/<id>.json`，重跑只补缺失的点；点的 id 包含容量检查方式，开启强制检查之前的缓存不会被复用；改了 AISim 或 profile 后删掉 `output/sweep/points` 再跑。每条记录带运行时的 AISim 提交，页面显示这些提交。i163v 上全部重跑约 30 分钟。并发太高时 AISim 启动会超时，脚本把这类失败重试 3 次，仍失败就停止；只有引擎自己的 `two_tier_dram:` 拒绝才记为被拒绝的点。

写页面前会检查：
- 两级完成时间不早于原生；
- 2.2 TB/s × 0.4 与 1.1 TB/s × 0.8 结果相同；
- 带宽升高不变慢；
- 二级 1024 GB 与最小可行容量时间相同；
- 二级 128 GB 全部被拒绝，最小可行容量的点没有因容量被拒绝；
- 所有完成的点二级可行；
- 每次传输加开销不变快；
- LRU 专家命中率低于 1% 的点，`layer_partition` 命中更多；
- Pro 一级 ≤ 36 GB 时非专家权重常驻被拒绝。

任何一项不通过就退出 1，不写页面。

页面 `output/sweep/two-tier-dram-sweep.html`（数据 gzip 后内嵌）：
- 左侧每个参数一组按钮；在当前组合下没算过的值显示为虚线，点击会跳到最近的已算点。
- 全局：完成时间、TTFT、decode 步长、复制量；每个请求的时间线；完成时间和 decode 步长随一级容量、二级带宽的变化；锚点上其余参数逐个变化的影响。
- 局部：每个 pass 的计算与等待构成；第一个 prefill pass 和稳态 decode pass 的逐层构成（附数据表）。

## 专家并行

```sh
python3 src/two-tier-dram-engine/ep.py
```

`ep.py` 在 `parallelism: {attention_data: 8, moe_expert: 8}` 下运行 EXI-3DDRAM 卡组：
- 每个 rank 是一张卡，持有非专家权重和 `e % 8 == rank` 的专家。
- 每个 group pass，各 rank 为全组 token 取自己的专家；没有本地请求的 rank 也要取，group pass 等最慢的 rank。
- 通信与计算由 AISim 原生 EP8 定价；rank 0 写 trace。

所有两级运行都开启二级容量强制检查，没有反事实运行：每卡需要 128.7 GB，二级取 192 GB；另有一个 128 GB 运行，检查它被拒绝。

参照是 AISim 原生 EP8 的同一负载。共 6 项检查：
- 带宽无限时与原生一致；
- 第一个 prefill 搬 96.7 GB；
- 每卡 128.7 GB；
- 128 GB 被拒绝；
- 所有结果可行；
- 1.1 TB/s × 0.8 比 2.2 TB/s 慢。

结果写入 `output/ep/summary.json`。

## 真实请求 trace 与真实硬件预设

```sh
python3 src/two-tier-dram-engine/trace.py                                   # GB200，conversation trace 的前 300 秒
python3 src/two-tier-dram-engine/trace.py --trace toolagent --duration-s 120 --speedup 0.25
python3 src/two-tier-dram-engine/trace.py --hardware exi --duration-s 120   # EXI 设计输入
python3 src/two-tier-dram-engine/trace.py --duration-s 15 --out /tmp/trace-smoke   # 冒烟测试，约 3 分钟
```

`trace.py` 用公开的 Mooncake FAST'25 请求 trace 驱动两级模型。trace 的来源、校验值和取得方法见 [`traces/mooncake-fast25/README.md`](traces/mooncake-fast25/README.md)；数据文件不入库。

### 负载

- 脚本从 trace 里截取 `[start-s, start-s + duration-s)` 的请求，只把第一个时间戳移到 0。输入输出长度和前缀块都不改。
- `--speedup X` 让请求以 X 倍速到达（AISim `trace_timestamps` 的 `speedup`）。默认 1，即 trace 原始到达率。小于 1 用来把负载降到部署能承受的水平，这样的结果必须标注为缩放过到达时间。
- 调度器的 `max_batched_tokens` 和 `max_sequences` 用 AISim 的 vLLM 默认值；前缀缓存开启。
- KV 容量取二级扣除权重后的剩余空间，按引擎 profile 的每 token KV 字节数折算（Flash 3,104 B，Pro 4,444 B）。调度器按这个容量接纳请求。

### 硬件预设

`--hardware gb200`（默认）是一个 NVIDIA GB200 计算托盘：4 颗 B200 加 2 颗 Grace。计算由 AISim 自带的 `gb200` 系统文件和实测（SILICON）性能数据库定价，后端 vLLM 0.24.0。

| 两级参数 | 取值 | 出处 |
| --- | --- | --- |
| 一级容量 | 198.67 GB | `gb200.yaml` 的 `mem_capacity`（nvidia-smi 报告 189,471 MiB） |
| scratch | 4.17 GB | `gb200.yaml` 的 `other_mem` 加 4 卡的 `nccl_mem` |
| 二级容量 | 240 GB／卡 | 每颗 Grace 480 GB LPDDR5X，带两颗 B200 |
| 复制带宽 | 225 GB/s × 0.75 | NVLink-C2C 双向 900 GB/s，两颗 B200 共享，每颗单向 225 GB/s（推算）；效率参照 Grace 调优指南的约 170 GB/s |
| 每次传输开销 | 2 µs | PCIe 实测 1–3 µs；没有查到 C2C 的数字 |

各项的来源链接见[硬件调研](../../dashboard/site/content/related-work/two-tier-dram-hardware-parameters.md)。

GB200 上的配置是 `pro-ep4`：DeepSeek-V4-Pro 做 4 路专家并行，每卡 225.4 GB，超过 HBM，放得进每卡的 LPDDR5X 份额。非专家权重常驻一级。运行有 `native`、`lru`、`partition` 三种。`native` 假设权重全在 HBM 里，这个部署实际放不下，只作计算时间的参照。

Flash 单卡（148.5 GB）和 Pro 8 卡（每卡 128.7 GB）在 B200 上直接放得进 HBM，不需要二级，所以没有列为 GB200 配置。H100 一类不支持这两个模型（AISim 支持矩阵为 `HW_INCOMPATIBLE`），所以没有 GH200 预设。

`--hardware exi` 是 EXI-3DDRAM 设计输入：`exi_3ddram` 系统文件上的解析 roofline（SOL），链路取调研修正基线（1.1 TB/s × 0.8，2 µs），二级每卡 192 GB。配置为 `flash-1card` 和 `pro-ep8`，各有原生、一级 36 GB 逐层轮换与 96 GB 常驻配 `lru`／`layer_partition` 共 5 种运行。

仍是合成的部分：专家路由和 top-k 选择（引擎内带种子的抽取，trace 里没有这些信息）。

### 检查与输出

写结果前会检查：
- 每次运行都成功，窗口内的请求全部完成；
- 所有两级运行二级可行；
- 引擎报告的每卡权重与扣除 KV 容量时用的值相同；
- 两级的 p50 TTFT 不早于原生。

结果写入 `output/trace/<hardware>-<trace>-<start>-<duration>[-x<speedup>]/summary.json`，其中记录硬件预设、倍速、窗口的行号范围、trace 的 SHA-256 和 AISim 提交。
