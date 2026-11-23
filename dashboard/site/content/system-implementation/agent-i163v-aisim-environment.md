---
weight: 1
author: Codex
title: "[Agent] i163v AISim 基础环境与运行"
description: 已安装环境、运行入口与 GPU 两级内存建模的依赖边界。
date: 2026-11-23T00:06:18+08:00
lastmod: 2026-11-23T00:06:18+08:00
content_lang: zh-CN
draft: true
---

## 环境基线

以下安装状态来自用户提供的安装报告。本次 SSH 连接被远端重置，未重新验证服务器环境，也未安装或修改远端软件。

| 项目 | 配置 |
| --- | --- |
| 登录与目录 | `ssh i163v`，`~/Mirage/src/aisim` |
| AISim | `0.15.0`，报告中的提交为 `c85b08623fc5fb8c6c6600619251d7fbf775bb1f`，与当前 Mirage 子模块指针一致 |
| Python | 3.12，虚拟环境为 `python/aisim/.venv` |
| Rust | 1.96.0，通过用户级 rustup 安装；环境入口为 `~/.cargo/env` |
| Python 依赖 | 报告称按 `uv.lock` 的版本和哈希安装，AISim 为 editable 安装，Rust 扩展已编译 |
| Dynamo | 报告称未安装；目前使用 `--stack engine` |

报告记录 README 预测示例完成 100 个模拟请求，墙钟耗时约 12 秒，输出 TTFT、ITL 和吞吐指标。这是一次运行验证，不代表性能基准或内存模型精度验证。

## 日常运行

```bash
ssh i163v
cd ~/Mirage/src/aisim
source python/aisim/.venv/bin/activate
```

在当前目录创建 `prediction.yaml`：

```yaml
engine:
  mode: aggregated
  model: Qwen/Qwen3-32B-FP8
  hardware: h200_sxm
  backend: vllm
  workers:
    aggregated: {}
```

执行预测：

```bash
aisim predict --stack engine --config prediction.yaml --output-dir ./aisim-prediction
```

结果为 `aisim-prediction/prediction.json`。增加 `--export-html` 可生成离线 `report.html`；增加 `--capture-per-request` 可保存逐请求记录。这里的 `backend: vllm` 指模拟后端，不要求运行真实 vLLM 服务。

## 修改代码与检查

修改 Rust 代码后需要重新编译扩展。以下重装命令沿用安装报告；本次未远端执行：

```bash
cd ~/Mirage/src/aisim
source ~/.cargo/env
uv pip install --python python/aisim/.venv/bin/python \
  --index-url https://pypi.org/simple \
  --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple \
  --no-deps -e python/aisim
```

`--no-deps` 复用已安装的运行依赖，但构建隔离仍可能下载 maturin 等构建依赖。上述命令不等同于按锁文件完整重建环境。报告中的首次安装采用了锁定版本及哈希的单独安装流程。

i163v 当时访问 GitHub/PyPI 较慢；优先使用现有虚拟环境，避免直接 `uv sync` 或 `uv run` 触发重新同步。镜像也可能缺少 `tfp-nightly`，不能保证完全离线重建。

报告建议在 Python 包目录运行单元测试：

```bash
cd ~/Mirage/src/aisim/python/aisim
source .venv/bin/activate
python -m pytest -c pytest.ini tests -m unit -n 32
```

`-n 32` 是原报告使用的并发度，共享机器资源紧张时应降低。报告初次结果为 16,308 通过、96 失败、61 报错；切换到上述目录后仍有 17 个失败，报告将其归于 GPU 数据采集、onboard 的子进程超时及 `collector` 导入问题。测试没有全通过，本次未复现或确认各失败的根因。

## GPU 两级内存建模还需要安装什么

**若目标是在 AISim 的离散事件模型中增加两级内存，当前 Python + Rust 环境预计足够，没有发现必须额外安装的软件。** 首先需要补充的是模型、配置和测试，而不是 CUDA 或另一套模拟器。

本次静态检查了本机 `/Users/linnan/Documents/INTEL/Mirage/src/aisim` 的源码副本。该副本缺少可核验提交的 Git 元数据，不能据此确认远端锁定版本拥有完全相同的功能：

- `crates/core/src/engine/host_offload.rs` 已有 G2 容量、LRU、池归属与虚拟 D2H/H2D 传输；文件明确说明这些机制由虚拟时间驱动，不依赖真实分布式存储或运行时。
- `crates/core/src/engine/host_offload/tier.rs`、`engine/offload_transfer.rs` 提供分层容量及传输机制；`engine/g3_offload/tier.rs` 还包含离线次级存储模型。
- `python/aisim/pyproject.toml` 的构建后端为 maturin；`dev` 包含 pytest 等开发工具，`learned` 提供 `scikit-learn`，用于可选的离线训练。

因此，“只有一级内存”需要限定含义：源码副本已有 **KV-cache 的设备／主机分层卸载**，但这不等于完成了研究所需的 **GPU 两级内存架构**。若两级内存需要服务活跃请求、按层访问 KV 或专家权重，并体现共享带宽争用、迁移及计算重叠，需要进一步扩展和验证，不能只改容量数值。

| 后续工作 | 额外依赖判断 |
| --- | --- |
| 两级容量、带宽、延迟、驻留／迁移策略的离线模拟 | 暂无必装项；复用 Rust 事件模型和现有 Python 环境 |
| 真实 GPU 性能采样与模型校准 | 按所选 collector 流程另配驱动、CUDA 和真实推理后端；不是纯模拟的前提 |
| Dynamo 集成路径 | 仅选择 `--stack dynamo` 时另配对应环境，不因增加二级内存而必需 |
| learned forward-pass model 的离线训练 | 仅采用该方法时需要 `learned` 可选依赖，先检查是否已安装 |

下一步应先在远端核对上述模块是否存在，再确定两级介质、容量、带宽、访问粒度、迁移策略，以及 KV／权重是否共用链路。最小验证应包含容量守恒、迁移完成前不可使用数据、并发传输争用，以及退化为一级内存时与基线一致。
