# two-tier-dram：两级 DRAM decode 模型（AISim 扩展）

把研究记录《初期目标：两级 DRAM 下的预取与热 KV 缓存》里的两级内存做成 AISim 的一个 stack 和一个配置段。它是树外扩展：不修改 `src/aisim`，通过 AISim 的 entry point 接入。

```sh
aisim predict --stack two_tier_dram --config CONFIG.yaml --output-dir OUT
```

## AISim 负责什么，扩展负责什么

| 来自 AISim | 扩展新增 |
| --- | --- |
| 读取 trace、调度请求、每个 token 的输出时刻（engine replay 及其原生 artifacts） | 把每个 decode step 拆成逐层时间线 |
| 模型几何：层数、每层是 CSA 还是 HCA、每层专家数、每 token 路由的专家数、`index_topk` | 一级容量账本：scratch、非专家权重、常驻 KV、专家缓存、热 top-k KV、脏 KV |
| 字节数：每个算子的权重、KV 条目、indexer 条目、每序列 KV | 一条共享链路：按需读取、预取和写回争用带宽 |
| 计算时间：`EngineHandle.decode_step_per_op` 的逐算子时延 | 专家 LRU 缓存、top-k KV LRU 缓存、可选的逐层权重换入与专家预取 |

AISim 的 replay 结果原样返回，两级结果并列给出。扩展不改 AISim 的 pass 时长，所以等待不会反馈给调度。这对不重叠的请求是准确的；发现多个请求同时 decode 时，runner 直接报错。

## 每层发生什么

```text
[非专家权重在一级？] → 选 top-k（仅 CSA 层）→ 取入缺失的 KV → attention
    → 路由 → 取入缺失的专家 → MoE
```

- **一级**：scratch；模型的全局权重；非专家权重（全部常驻，或只保留当前层并预取下一层）；每步都要完整读取的 KV（滑动窗口，以及 HCA 层的压缩 KV）；路由专家的 LRU 缓存；top-k KV 的 LRU 缓存。
- **二级**：全部权重和完整 KV。
- 每个 step 结束时，新 token 的 KV 以脏数据写入一级，再排队写回二级。

## 安装

需要已构建的 AISim 开发环境（见 `src/aisim/DEVELOPMENT.md`）。把本包以 editable 方式装进 AISim 的 venv：

```sh
cd src/aisim
uv pip install --python python/aisim/.venv/bin/python -e ../two-tier-dram
```

之后 `aisim` 能发现 stack `two_tier_dram` 和配置段 `two_tier_dram`。在 `src/aisim` 里重新 `uv sync` 会移除它，需要再装一次。

## 配置

在一份普通的 AISim prediction 配置上加顶层段 `two_tier_dram`。引擎必须是 aggregated；`ais_perf_model` 用 `op_level`，这样 replay 的时延和扩展用的逐算子时延是同一套定价。

```yaml
engine:
  mode: aggregated
  model: sgl-project/DeepSeek-V4-Pro-FP8
  hardware: b200_sxm
  backend: vllm
  context_length: 262144
  ais_perf_model: {estimation_mode: op_level, database_mode: SOL}
  workers:
    aggregated:
      parallelism: {replicas: 1, tensor: 1, attention_data: 1}
      kv_cache: {capacity: {type: fixed, blocks: 40000}}
traffic: { ... }                 # 单个请求，或互不重叠的请求
two_tier_dram:
  tier1_gb: 96
  link_gbps: 64
  trace_dir: ./two-tier-out      # 写入 trace.json、summary.json、replay.html
```

模型的 1579 GB 权重放不进一张卡，这正是两级设计的前提。`kv_cache.capacity: fixed` 用来绕开 AISim 的单层显存检查。

| 字段 | 默认 | 含义 |
| --- | --- | --- |
| `tier1_gb` / `scratch_gb` | 96 / 4 | 一级容量；其中留给激活等的 scratch |
| `tier2_gb` | 2048 | 二级容量，必须放得下全部权重和完整 KV |
| `link_gbps` / `link_overhead_ms` | 64 / 0.01 | 共享链路的带宽；每次传输的固定开销 |
| `link_policy` | `demand_first` | `demand_first`：按需读取抢占预取和写回；`fifo`：不抢占 |
| `base_weights` | `resident` | `resident`：非专家权重全部常驻一级；`layer_prefetch`：只留当前层并预取下一层（方案 A） |
| `expert_cache_gb` | 自动 | 专家缓存上限；不填则用一级剩余的空间 |
| `expert_overlap` | 0.5 | 一层在相邻 step 路由到同一专家的概率（合成） |
| `expert_prefetch` | `none` | `last_step`：预取下一层上一步用过、但已不在缓存里的专家 |
| `hot_kv_entries` | 65536 | 热 top-k KV 缓存的条数上限；0 表示用完即丢 |
| `topk_overlap` | 0.75 | 一层在相邻 step 保留每条 top-k 的概率（合成） |
| `max_decode_steps` | 3 | 每个请求最多重计时的 decode step 数 |
| `seed` | 0 | 合成选择的随机种子 |
| `trace_dir` | 不写 | 输出目录 |

运行时 runner 打印一行对比（两级每 token 时延与 AISim 原生时延）。`prediction.json` 仍是 AISim 的原生报告，两级结果在 `trace_dir` 里。

## 场景与回放

```sh
python3 src/two-tier-dram/scenarios.py            # 9 个场景，输出到 src/two-tier-dram/output/
python3 src/two-tier-dram/scenarios.py --only baseline --show
```

每个场景都是一次真实的 `aisim predict --stack two_tier_dram`。脚本把结果与场景的 `expect` 和跨场景关系逐项比较，不符则打印 `MISMATCH` 并以退出码 1 结束，然后生成 `output/two-tier-dram-replay.html`。页面是单个离线文件，可以放进 iframe。

查看页面（在远端运行时）：

```sh
cd src/two-tier-dram/output && python3 -m http.server 8765     # 远端
ssh -L 8765:localhost:8765 i163v                               # 本地，打开 http://localhost:8765/two-tier-dram-replay.html
```

场景使用 DeepSeek-V4-Pro-FP8、b200_sxm、vLLM、SOL，一个 200K 上下文的请求，重计时 3 个 decode step。AISim 原生每 token 6.54 ms。

| 场景 | 改动 | 两级每 token (ms) | 观察 |
| --- | --- | --- | --- |
| `baseline` | 无 | 385 / 203 / 184 | 专家搬运决定时延；等专家 751 ms，等 KV 1.3 ms |
| `reconcile` | 链路 1e6 GB/s，开销 0 | 6.56 / 6.55 / 6.55 | 搬运代价趋零时回到 AISim 原生时延 |
| `sticky-experts` | 专家重合度 0.9 | 385 / 45 / 46 | 时延对路由稳定性很敏感 |
| `small-tier1` | 一级 48 GB | 385 / 385 / 385 | 缓存 179 位，一个 step 要用 366 个专家，命中 0 |
| `small-tier1-prefetch` | 一级 48 GB，专家预取 | 385 / 574 / 551 | 预取不准，占用关键路径上的链路，反而更慢 |
| `no-hot-kv` | 热 KV 关闭 | 385 / 203 / 184 | 每 token 只多 0.18 ms，KV 不是瓶颈 |
| `link-overhead` | 每次传输开销 0.5 ms | 430 / 247 / 229 | 等 KV 从 1.3 涨到 45 ms，小而频繁的读取看开销 |
| `layer-prefetch` | 非专家权重逐层换入 | 823 / 640 / 621 | 182 次预取全部迟到；一层 0.46 GB 要 7.2 ms，一层计算 0.1 ms |
| `tier1-too-small` | 一级 36 GB | 运行中止 | 常驻项之后放不下一层的 6 个专家 |

这些数字依赖两个合成参数（专家与 top-k 的跨步重合度）和假设的链路参数，用来说明机制和量级，不是性能结论。

## 测试

```sh
cd src/two-tier-dram
../aisim/python/aisim/.venv/bin/python -m unittest discover -s tests -v
```

- `tests/test_model.py`（14 个）：用小的合成 profile 检查模型行为，不依赖 AISim。包括一级不超容量、数据到达前不计算、链路不超带宽、冷启动 step 的时延等于原生时延加搬运字节除以带宽、缓存小于一个 step 的工作集时零命中。
- `tests/test_aisim.py`（4 个）：需要 AISim。检查 stack 与配置段已注册、profile 的 step 时延等于 AISim 的逐算子之和、profile 的权重字节加总等于 AISim 的权重清单、链路极快时回到 AISim 原生时延。

## 文件

| 文件 | 作用 |
| --- | --- |
| `pyproject.toml` | 包定义与两个 entry point |
| `two_tier_dram/adapter.py` | 配置段适配器（config-adapter ABI v3），只支持 `predict` |
| `two_tier_dram/runner.py` | stack 的 runner：包装 AISim 的 engine runner，取 artifacts，重计时，写出 trace |
| `two_tier_dram/profile.py` | 从 AISim 读取模型几何、字节数和逐算子时延；另有测试用的合成 profile |
| `two_tier_dram/model.py` | 两级模型：账本、链路、逐层状态机、事件与快照 |
| `two_tier_dram/config.py` | 配置与 profile 的数据结构 |
| `two_tier_dram/render.py`、`template.html` | 回放页面 |
| `scenarios.py` | 场景目录与回归检查 |

## 口径与限制

- 只支持 DeepSeek-V4 一类的模型（压缩稀疏注意力加 MoE）；其他模型会报错。
- AISim 对一个算子只给所有层的合计时延，逐层时间是按层数均摊的，没有 CSA 与 HCA 层之间的差异。
- top-k 条目和路由专家是合成的：每层以给定概率保留上一步的每个选择，其余均匀抽取。AISim 不产生选中集合，真实的重合度需要 indexer 和 router 的统计数据。
- 开环：两级等待不改变 AISim 的调度。只支持互不重叠的请求（batch 1），每个请求单独从冷缓存开始。
- 单个 aggregated worker、TP1、EP1；没有多 GPU 分片。
- 链路只有带宽和每次传输的固定开销；没有建模小块分散读取的有效带宽下降，也没有往一级写入对计算读带宽的挤占。
- 被抢占的传输恢复时不重复计入固定开销。HCA 层的压缩 KV 和 indexer cache 在 `resident` 模式下视为常驻一级。
- AISim 给出的 DeepSeek-V4-Pro-FP8 权重是 1579 GB，研究记录的容量表按 732 GB 计算，量化口径待核对。

## 实验记录

- 时间：2026-11-23（北京时间），在 i163v 上运行。
- 代码：分支 `two-tier-dram-replay`；`src/aisim` 为 submodule `c85b086`，aisim 0.15.0，未修改。
- 环境：Linux，Python 3.12，AISim venv 由 uv 管理。
- 随机性：合成选择由 `seed` 决定，结果可复现。
- 检查：18 个测试、9 个场景的预期值和 5 条跨场景关系全部通过；回放页面在浏览器中核对过。
