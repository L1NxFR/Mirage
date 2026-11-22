# two-tier-dram：两级 DRAM decode 行为回放

一个独立的离散事件模型，对应研究记录《初期目标：两级 DRAM 下的预取与热 KV 缓存》的第一阶段：可配置的两级容量、带宽、延迟、传输队列和逐层依赖，输出可检查的事件时间线。它生成可逐帧播放的 HTML 动画，展示两级内存里的内容和每一种搬运行为。

- **一级（3D-stacked DRAM）**：小而快，计算直接读取。存放当前层的权重与 indexer KV、下一层的预取缓冲、热 attention KV 缓存和 scratch。
- **二级（LPDDR）**：大而慢。存放全部权重和完整 KV。
- **共享链路**：预取、按需读取和写回共用一条链路，争用带宽。

每个 decode step 的每一层按这个顺序执行：权重是否在一级 → indexer → 选 top-k → 取入缺失的 KV → attention → MoE。

模型不依赖也不修改 AISim，只用 Python 标准库（3.10+）。

## 运行

```sh
python3 src/two-tier-dram/scenarios.py                    # 全部场景，输出到 src/two-tier-dram/output/
python3 src/two-tier-dram/scenarios.py --only slow-link   # 只跑指定场景
cd src/two-tier-dram && python3 -m unittest -v test_model # 行为测试
```

输出：

| 文件 | 内容 |
| --- | --- |
| `output/two-tier-dram-replay.html` | 动画页面，单个离线文件，可直接打开，也可放进 iframe |
| `output/<slug>/trace.json` | 该场景的配置、指标、事件日志、逐事件状态快照、计算与链路的时间段 |

`scenarios.py` 运行每个场景后，把结果与该场景的 `expect`（每 token 时延、KV 命中率、等待时间等）以及跨场景关系逐项比较。任何不符都打印 `MISMATCH` 并以退出码 1 结束，这时不生成页面。

查看页面（在远端机器上运行时）：

```sh
cd src/two-tier-dram/output && python3 -m http.server 8765   # 远端
ssh -L 8765:localhost:8765 i163v                              # 本地，然后打开 http://localhost:8765/two-tier-dram-replay.html
```

## 文件

| 文件 | 作用 |
| --- | --- |
| `model.py` | `Config` 与 `simulate()`：两级内存、共享链路、逐层计算状态机，运行时断言不变量 |
| `scenarios.py` | 场景目录、预期值与跨场景关系检查、生成页面 |
| `template.html` | 动画页面模板 |
| `test_model.py` | 行为测试：容量守恒、数据到达前不计算、链路不超带宽、关闭预取与缓存后退化为基线等 |

## 场景

基线参数：4 层、3 个 decode step、12 个上下文 token、top-k 4、跨步重合度 0.75；每层权重 8 MB、indexer KV 1 MB、每条 KV 0.5 MB、scratch 2 MB；一级 32 MB；链路 4 MB/ms，每次传输固定开销 0.2 ms；每层计算 1 + 2 + 3 = 6 ms，纯计算每 token 24 ms。

| slug | 改动 | 每 token (ms) | 观察 |
| --- | --- | --- | --- |
| `prefetch-hot-kv` | 无 | 29.25 / 25.2 / 25.0 | 冷启动后接近纯计算 |
| `on-demand` | 关预取、关热 KV | 36.6 | 每层等权重和 KV |
| `prefetch-only` | 关热 KV | 29.25 / 26.8 / 26.8 | 权重等待消失，KV 等待仍在 |
| `hot-kv-only` | 关预取 | 36.6 / 35.0 / 34.8 | 权重搬运是主要代价 |
| `zero-overlap` | 重合度 0 | 同 `prefetch-only` | 缓存占空间但零命中 |
| `lru-thrash` | 热 KV 软上限 16 条 | 同 `prefetch-only` | 容量等于一步工作集时，跨层 LRU 抖动，零命中 |
| `prefetch-crowds-kv` | 一级 28 MB | 同 `prefetch-only` | 预取缓冲挤占热 KV，零命中 |
| `slow-link` | 链路 1 MB/ms | 51.6 / 39.9 / 41.6 | 11 次预取全部迟到 |
| `slow-link-fifo` | 链路 1 MB/ms，FIFO | 76.9 / 53.8 / 51.7 | 按需取 KV 排在预取后，等 KV 93.4 ms |
| `tier1-too-small` | 一级 22 MB | 运行中止 | 脏 KV 未写回、无法淘汰，容量不足 |

数值是模型在玩具参数下的输出，用来说明机制，不是性能结论。新增场景时在 `SCENARIOS` 里加一项并写明 `expect`；相对基线改动的参数会在页面上用黄色标出。

## 模型范围与简化

- 单请求、batch 1；每层的计算时间是固定配置值，没有接入 AISim 的性能模型。
- 只实现方案 A（逐层预取）。一层的权重与 indexer KV 作为一个整体搬运，不区分专家，没有实现方案 B（热专家常驻）。
- top-k 由合成的重合度参数生成：每层以 `overlap` 的概率保留上一步的每个选中 token，其余换成该层从未选过的上下文 token。只从初始上下文中选；新生成 token 的 KV 只建模为“写入一级（脏）＋写回二级”。
- 链路策略有两种：`demand_first`（按需读取可抢占预取和写回）和 `fifo`（不抢占）。被抢占的传输恢复时不重复计入固定开销。
- 没有建模随访问粒度变化的有效带宽、往一级写入对计算读取带宽的挤占，也没有计算直接读取二级的路径。
- 一级放不下预取缓冲时跳过预取，到时按需取入。一级放不下某一步必需的数据时，运行中止并返回已有的 trace。这是一种简单策略，没有尝试取消预取来腾空间。
- 多 GPU、多请求调度以及与 AISim vLLM 调度器的集成不在本阶段范围内。

## 运行时检查的不变量

- 一级占用（scratch、当前层、预取缓冲、热 KV）在每次分配后都不超过容量。
- 一层在其权重到达前不开始；attention 在所选 KV 全部到达前不开始。
- 链路搬运的字节数不超过带宽乘以忙碌时间；同一时刻只服务一个传输。
- 二级放不下完整模型与 KV 时，在运行前拒绝。
