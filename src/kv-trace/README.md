# kv-trace：AISim KV Cache 行为回放

运行 AISim `predict`，取出原生的 block 级 KV 事件，渲染成可逐帧播放、可嵌入 Dashboard 的 HTML 动画。动画展示 G1（GPU HBM）与 G2（Host DRAM）中每个 block 的状态、token 填充、D2H/H2D 传输，以及每个请求的阶段。

不修改上游 AISim 代码。AISim 运行时自带 `run_replay_with_artifacts_json`，与 CLI 默认的 `run_replay_json` 共用同一个 replay 循环，额外返回 `kv_events` 与 `host_offload_events`。`capture.py` 走正常的 supervised `aisim predict`，通过 `PYTHONPATH` 和 `KV_TRACE_OUT` 加载 `_hook/sitecustomize.py`，在 AISim 的子进程里换上这个函数。

## 依赖

- 已构建的 AISim 开发环境：`src/aisim/python/aisim/.venv`。构建方法见 `src/aisim/DEVELOPMENT.md`，需要 Python 3.11–3.13 和 Rust：

  ```sh
  cd src/aisim && uv sync --project python/aisim --extra dev --python 3.12
  ```

- `scenarios.py` 与 `render.py` 只依赖 Python 标准库；页面是单个离线 HTML 文件。

## 运行

```sh
python3 src/kv-trace/scenarios.py                       # 全部场景，输出到 src/kv-trace/output/
python3 src/kv-trace/scenarios.py --only slow-d2h       # 只跑指定场景
python3 src/kv-trace/scenarios.py --publish dashboard/site/content/Attachments/kv-cache-replay.html
```

`scenarios.py` 依次执行以下步骤：

1. 为每个场景生成 `config.json` 和 mooncake `trace.jsonl`。
2. 调用 `capture.py` 运行 AISim。
3. 按场景的 `expect` 检查 TTFT、G2 复用 token 数和是否被拒绝。任何不符都以退出码 1 结束，并打印 `MISMATCH`。
4. 调用 `render.py` 生成 `output/kv-cache-replay.html`。

`--publish` 把页面复制到指定位置，供 Dashboard 嵌入。

页面参数：`?scenario=<slug>` 打开指定场景；放进 iframe 或带 `?embed` 时隐藏页头，并通过 `postMessage({kvReplayHeight})` 通知父页面调整高度。Dashboard 用 `embed-html` shortcode 嵌入，语法见文档写作语法指南。

## 场景

公共参数：
- vLLM 后端，TP1。
- block_size 4，每 block 1 MB。
- G1 3 block，G2 8 block，D2H/H2D 1 GB/s。
- fixed timing，prefill 2 ms。
- 请求 9 token 输入、1 token 输出；R3 是 R1 的下一轮（12 token，共享 R1 的前 2 个整块）。页面在请求名下标出这种关系，由共享的 block hash 自动推出。

| slug | 改动 | 预期（回归检查） |
| --- | --- | --- |
| `baseline` | 无 | TTFT 2/2/4/2 ms；R3 从 G2 复用 8 token |
| `g2-pressure` | G2 4 block，H2D 0.05 GB/s | R3 TTFT 42 ms；t=300 G2 驱逐 R2 的块 |
| `slow-d2h` | D2H 0.016 GB/s（存 2 MB 要 125 ms） | TTFT 2/29/58/22.5 ms：复用仍在被 D2H 读取的源 block，触发栅栏 |
| `g2-one-block` | G2 1 block | store 结构性放不下，G2 复用为 0 |
| `aligned-full-hit` | prompt 8 token，G1 2 block | R3 只记复用 4 token；载入的第 2 块被整块重算 |
| `h2d-blocks-peer` | max_sequences 2，H2D 0.05 GB/s，R4 在 210 ms 到达 | R4 先于 R3 完成；R3 TTFT 42 ms |
| `prompt-exceeds-g1` | G1 2 block | 请求被拒绝；AISim 退出码 1（预期） |

新增场景时，在 `SCENARIOS` 里加一项，写明 `expect`。`kv`、`sched` 中相对基线改动的参数会自动以黄色标在页面顶部。

## 推断项与限制

`render.py` 用原生事件重建槽位占用，并断言不超过配置容量。以下三点是推断，页面上已标注：

1. **"写入中"block 数**：按引擎准入规则计算，`token_blocks − max(复用块, H2D 载入块)`。
2. **G1 驱逐时刻**：vLLM 在 pass 结束时发布驱逐事件，这里画在导致它的那次准入。排在该 pass 自身 `stored` 之后发布的驱逐属于后续调度，保持原时刻。
3. **传输区间**：传输条只在 `completes_at_ms − 字节/带宽` 之后推进，此前是排队或等栅栏。

适用范围：
- 仅支持 aggregated、vLLM、单 DP rank。这是 artifact 路径本身的限制。
- 每个请求只有 1 个输出 token。
- 不考虑 PP>1。
- G2 槽位位置只是显示用的，模型本身没有物理地址。

## 实验记录

- 时间：2026-11-23（北京时间）。
- 代码：Mirage `19dfc18` 加本地未提交改动。`src/aisim` 是 submodule 指针 `c85b086`，但本地目录不是 git 检出，按当前源码快照对待。aisim 版本 0.15.0。
- 环境：Darwin arm64，Python 3.12.12（uv 管理），cargo 1.100.0。
- 随机性：trace 回放，fixed timing，无随机种子依赖。
- 检查：7 个场景的 `expect` 与容量断言全部通过。页面已在浏览器中逐事件核对。没有运行 AISim 自带的测试。
