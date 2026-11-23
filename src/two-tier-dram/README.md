# two-tier-dram：两级 DRAM decode 模型（AISim 扩展）

## 开发版本：0.1.0.dev1

本次提交保存当前研究原型，基于 `9c92314`，尚未完成正确性修复与硬件校准。

已复现、留待后续修复的问题：

- `per_layer` 与 `last_step` 预取组合会保留未被使用的预测专家，影响“无跨步缓存”的对照语义。
- 专家缓存仅够一层时，预取可能占满不可淘汰的槽位，使按需访问报容量错误。
- 二级容量检查只覆盖初始 KV，未计入 decode 生成期间的 KV 增长。

本次仅标记开发版本并记录已知问题，不修改模拟逻辑，不重跑测试或实验。此前审阅在 `9c92314` 上重跑的 35 项测试通过，补充边界检查复现了上述三个问题。预取对照需在修复后重新验证。

把研究记录《初期目标：两级 DRAM 下的预取与热 KV 缓存》里的两级内存做成 AISim 的一个 stack 和一个配置段。它是树外扩展：不修改 `src/aisim`，通过 AISim 的 entry point 接入。

```sh
aisim predict --stack two_tier_dram --config CONFIG.yaml --output-dir OUT
```

**结果的资格。** 所有结果都是模型输出，不是 EXI-3DDRAM 的性能预测，原因有四：

1. 官方 DeepSeek-V4-Pro 权重为 806.6 GB，超过 EXI 图示单卡 LPDDR 的最大 512 GB，单卡不可行。对照实验以“反事实”方式运行，并在结果中标为不可行。
2. 路由专家与 top-k 的跨步重合度是合成参数。
3. 复制效率与每次传输的固定开销是假设值。
4. EXI 的计算时间来自 AISim 的解析 roofline，未经校准。

## 硬件输入与来源

硬件量在配置中写成带单位的字符串（`"36 GB"`、`"2.2 TB/s"`、`"10 us"`），在 `config.py` 入口统一换算为字节、字节/秒和秒，模型内部不再出现无单位的带宽或容量。GB 与 GiB、TB/s 与 Tb/s 分开解析：GB = 1e9 B，GiB = 2^30 B，Tb/s = 1.25e11 B/s。每个硬件字段都记录来源，页面上按来源着色。

| 参数 | EXI 图示（`exi_figure`） | 来源 |
| --- | --- | --- |
| 一级容量 `tier1_capacity` | 36 GB | EXI-3DDRAM 架构表 |
| 一级读带宽 `tier1_bandwidth`（计算读一级） | 18 TB/s | 架构表（zHBM / 3D DRAM） |
| 二级容量 `tier2_capacity` | 128 GB | 架构表默认值；范围 64–512 GB |
| 二级标称带宽 `tier2_bandwidth` | 2.2 TB/s | 架构表 LPDDR6 1.1–2.2 TB/s 的上端 |
| 复制效率 `copy_efficiency` | 1.0 | **假设**：理想复制 |
| 每次传输固定开销 `transfer_overhead` | 0 s | **假设**：表中未给出 |
| 卡间带宽 `interconnect_bandwidth` | 1.6 TB/s（双向合计） | 架构表，**Ask**，未确定；TP1 下未使用 |
| scratch | 4 GB | **假设**：激活与临时空间 |

四种带宽各自独立：

- **一级读带宽**：决定计算时间。只用于 AISim 系统规格 `systems/exi_3ddram.yaml` 的 `mem_bw` 以及争用上界的计算，不参与搬运。
- **二级标称带宽**：LPDDR6 的标称值。
- **有效复制带宽** = 二级标称带宽 × 复制效率：二级到一级的搬运速率，所有传输共用这一条链路。
- **卡间带宽**：只记录，单卡模型不使用。

其他预设：

- `exi_96gb_explore`：同 EXI 图示，只把一级改为 96 GB。96 GB 来自原设计文档，**不是** EXI 图示配置，页面和结果中分开标注。
- `legacy_64gbps`：上一版（提交 e86bfad）的假设，**已撤回**，只用于历史对照。具体为：一级 96 GB、二级 2048 GB（为装下 1579 GB 模型而虚构）、64 GB/s、10 µs，计算用 B200。

图中未确定或未给出的项：

- 有效复制带宽与内部互连限制；
- 每次传输的固定开销；
- `>24 TB/s` 与 `150 GB+ per Compute Tile`，属于 Ask，未使用；
- BF16、INT8、FP32 算力，以及计算是否能直接读二级。

FP4 6.13 PF、FP8 2.95 PF 已写入 EXI 系统规格，但在 batch 1 decode 下不起作用（见下）。

## 计算时间的来源

| 计算基线 | 含义 |
| --- | --- |
| **EXI-SOL** | AISim 的解析 roofline，使用 `systems/exi_3ddram.yaml`：一级 18 TB/s、FP8 2.95 PF、FP4 6.13 PF，其余字段为标注的假设。每个算子取 max(计算 / 峰值, 字节 / 带宽)。batch 1 decode 的所有算子都受内存带宽限制，所以 EXI-SOL 相对 B200 正好快 18 / 7.7 = 2.34 倍。这是 roofline 的结果，不是按峰值 FLOPS 缩放。未经实测校准。 |
| **B200（混合）** | AISim 的 `b200_sxm` 计算时间配合 EXI 两级内存假设。runner 会检测并标为“混合实验，不是该硬件的预测”。 |

`runner.compute_basis` 比较 AISim 定价所用的 `mem_bw` 与两级配置的 `tier1_bandwidth`，相差 1% 以上即判为混合实验。

## 模型与工作负载

| 模型 | 专家量化 | 总权重 | 路由专家 | 非专家 |
| --- | --- | --- | --- | --- |
| `deepseek-ai/DeepSeek-V4-Pro`（官方，本版主工作负载） | w4a8 mxfp4 | 806.6 GB | 774 GB | 32 GB |
| `nvidia/DeepSeek-V4-Pro-NVFP4` | nvfp4 | 902 GB | 870 GB | 32 GB |
| `sgl-project/DeepSeek-V4-Pro-FP8`（上一版使用） | fp8_block | 1579 GB | 1547 GB | 32 GB |

研究记录容量表中的 732 GB 与“路由专家 720 GB”对应 4 bit 专家。按 mxfp4 每 32 个值加一个缩放字节（4.25 bit），720 GB 约为 765 GB，与 AISim 的 774 GB 接近（推断）。上一版用 FP8 模型，专家体积翻倍。

即使用官方模型，806.6 GB 也超过 EXI 单卡二级的 128 GB（最大 512 GB）。未实现多卡分片前不能直接除以 GPU 数量：`tier2_capacity_check: enforce`（默认）报“单卡不可行”并停止；`counterfactual` 继续运行，但每个结果都带不可行标记。

36 GB 的一级在扣除 4 GB scratch 后放不下 32 GB 非专家权重，所以 EXI 图示配置必须逐层轮换非专家权重（`base_weights: layer_rotation`）。96 GB 时可以常驻。

## 策略

| 字段 | 取值 |
| --- | --- |
| `base_weights` | `resident`：全部常驻；`layer_rotation`：只保留当前层，并预取下一层 |
| `expert_cache` | `lru`：跨 step 的 LRU 缓存；`per_layer`：层结束即释放，无跨步复用 |
| `expert_prefetch` | `none`；`last_step`：预取下一层上一步用过、但已不在缓存的专家 |
| `hot_kv_entries` | 热 top-k KV 的 LRU 条数上限；0 表示用完即丢 |
| `expert_overlap` / `topk_overlap` | 合成的跨步重合度 |
| `link_policy` | `demand_first`：按需读取抢占预取和写回；`fifo` |

专家缓存的规则（`tests/test_model.py` 覆盖）：

- 未满时只积累不淘汰，每个（层, 专家）只占一个位置。
- 满后按 LRU 淘汰，占用不超过上限。
- 正在传输的专家和当前层使用中的专家不可淘汰；已到达但还没用到的预取专家可以淘汰。
- 缓存满后占用保持不变，内容仍在替换。页面同时显示占用、上限、累计淘汰数和本 step 命中率，以便区分这两件事。

## 输出

- `trace.json`：硬件与来源、计算基线、可行性、指标，以及逐 step 统计。逐 step 统计包括计算、各类等待、按类型的搬运字节、链路利用率、专家和 KV 命中率、淘汰数、缓存占用和一级占用。`trace_detail: full` 时另含事件与逐事件快照。
- 阶段判定：
  - step 1 为冷启动；
  - 在出现第一次淘汰之前为“缓存填充”；
  - 之后为“淘汰中”；
  - 只有最后 6 个 step 都已过填充阶段、且波动不超过 5% 时，才报告稳态值，否则明确写“未达到稳态”。
- 没有建模复制写入一级与计算读一级的争用，`tier1_contention_bound_ms` 给出上界：重叠时间 × 有效复制带宽 / 一级带宽。

## 运行

安装（需已构建的 AISim 开发环境）：

```sh
cd src/aisim
uv pip install --python python/aisim/.venv/bin/python -e ../two-tier-dram
```

完整实验与回放页面（约 3 分钟，每次都是一次 AISim 预测）：

```sh
python3 src/two-tier-dram/scenarios.py
```

结果写入 `output/sweep.md`、`output/sweep.json` 和 `output/two-tier-dram-replay.html`。脚本只检查与结论无关的逻辑关系（带宽越高不会越慢、开销越大不会越快、链路极快时回到 AISim 原生时延、旧配置复现旧数值、不可行配置被报告），不预设结论。

测试：

```sh
cd src/two-tier-dram
../aisim/python/aisim/.venv/bin/python -m unittest discover -s tests -v
```

共 35 个测试：28 个模型测试，不依赖 AISim，覆盖单位、链路计时、容量不足、缓存积累与淘汰、保护规则、稳态判定；7 个 AISim 集成测试。

## 结果（2026-11-23，i163v）

工作负载：官方 DeepSeek-V4-Pro，200K 上下文，单请求，32 个 decode step；默认专家重合度 0.5，top-k 重合度 0.75。全部为反事实运行（单卡二级放不下模型）。

| 配置 | 冷启动 ms | 缓存满后 ms/token | 计算 | 等非专家权重 | 等专家 | 搬运 GB/token | 链路利用率 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 36 GB · 2.2 TB/s 理想 | 18.5 | 15.6（稳态） | 2.13 | 10.8 | 2.7 | 34.3 | 100% |
| 36 GB · 1.1 TB/s 理想 | 36.9 | 31.2（稳态） | 2.13 | 23.7 | 5.4 | 34.3 | 100% |
| 36 GB · 2.2 TB/s × 0.7（假设） | 26.4 | 22.3（稳态） | 2.13 | 16.3 | 3.8 | 34.3 | 100% |
| 96 GB · 2.2 TB/s 理想 | 7.6 | 4.7（未稳态，波动 13%） | 2.13 | 0 | 2.5 | 5.6 | 54% |
| 96 GB · 1.1 TB/s 理想 | 13.1 | 7.2（未稳态，波动 16%） | 2.13 | 0 | 5.1 | 5.6 | 70% |
| 旧假设 64 GB/s（已撤回） | 385.5 | 183.3 | 6.54 | 0 | 176.4 | 11.3 | 96% |

完整对照（固定开销、预取、缓存策略、热 KV、重合度、计算基线）见 `output/sweep.md`。

主要观察：

1. **36 GB 受链路带宽限制。** 每 token 时间 ≈ 搬运字节 ÷ 有效带宽（15.57 vs 15.59 ms），带宽减半时间正好翻倍。其中 82%（28.1 GB）是非专家权重的逐层轮换，路由专家只占 6.3 GB。
2. **96 GB 下非专家权重常驻。** 搬运只剩专家（5.6 GB/token），每 token ≈ 计算 2.13 + 专家字节 ÷ 带宽 2.54：专家要在路由之后才能取，取入与计算串行，链路只忙 54%。
3. **跨步专家 LRU 缓存有效。** 改成逐层释放后，36 GB 从 15.6 升到 18.4 ms，96 GB 从 4.7 升到 7.6 ms。
4. **热 top-k KV 的影响可以忽略。** 关闭前后每 token 差 ≤ 0.01 ms，KV 每 token 只有几 MB。KV 传输次数多（每 CSA 层一次），在固定开销为 10 µs 时贡献 0.3 ms。
5. **“按上一步路由预取专家”没有收益。**
   - 有 LRU 缓存时，上一步的专家总在缓存里，预取器 0 次触发。
   - 无缓存时反而更慢（36 GB：18.4 → 21.0 ms）。预测准确率约 50%，专家流量增加 44%；且一层计算只有 0.035 ms，6 个专家要 0.09 ms，绝大多数预取在使用时仍未到达。
6. **固定开销**：每 token 约 153 次（36 GB）或 92 次（96 GB）传输。10 µs 加约 1.5 / 0.9 ms，100 µs 加约 15 / 9 ms。
7. **计算基线**：36 GB 受链路限制，B200 与 EXI-SOL 只差 0.1 ms；96 GB 差 2.9 ms（7.56 vs 4.67）。
8. **争用上界**：36 GB 下复制与计算重叠造成的额外计算时间不超过约 0.26 ms/token，按有效带宽 / 一级带宽 = 12% 计算。这一项没有计入结果。

## 文件

| 文件 | 作用 |
| --- | --- |
| `two_tier_dram/config.py` | 单位解析、硬件预设与来源、策略、模型 profile |
| `two_tier_dram/model.py` | 两级模型：账本、链路、逐层状态机、逐 step 统计、稳态判定 |
| `two_tier_dram/profile.py` | 从 AISim 读取模型几何、字节数和逐算子时延，以及计算所用的一级带宽 |
| `two_tier_dram/runner.py`、`adapter.py` | AISim stack 与配置段 |
| `two_tier_dram/render.py`、`template.html` | 回放页面 |
| `systems/exi_3ddram.yaml` | EXI-3DDRAM 的 AISim 系统规格，逐字段标注来源 |
| `scenarios.py` | 实验目录、逻辑检查、对照表与页面 |

## 限制

- 开环：两级等待不反馈给 AISim 调度；只支持互不重叠的请求，每个请求从冷缓存开始。
- 单卡、TP1、EP1；没有多卡分片，所以 EXI 图示配置单卡不可行。
- 逐层计算时间按层数均摊 AISim 的算子合计时延。
- 链路只有带宽与固定开销，没有随访问粒度变化的有效带宽；复制与计算的一级带宽争用只给上界。
- 被抢占的传输恢复时不重复计入固定开销。
