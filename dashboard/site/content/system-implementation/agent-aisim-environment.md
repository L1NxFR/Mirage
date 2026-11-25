---
weight: 1
author: Codex
title: AISim 开发环境与运行
description: AISim 的开发依赖、预测命令与测试入口。
date: 2026-11-23T00:06:18+08:00
lastmod: 2026-11-25T10:42:39+08:00
content_lang: zh-CN
draft: true
---

## 开发环境

准备 Python 3.11–3.13、uv、Rust 和 C/C++ 工具链。使用与源码版本匹配的模型配置和性能表。从 Mirage 仓库根目录进入 AISim 并构建开发环境：

```sh
cd src/aisim
uv sync --project python/aisim --extra dev --python 3.12
source python/aisim/.venv/bin/activate
```

## 运行预测

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

## 运行单元测试

在 AISim 根目录激活开发环境后运行：

```sh
cd python/aisim
python -m pytest -c pytest.ini tests -m unit
```

## 两级内存模型

内置 engine 支持设备与主机之间的 KV 前缀卸载。Mirage 的 `two_tier_dram` 扩展在每个 decode step 内逐层模拟专家权重、KV 缓存和共享传输链路。两条路径都可离线运行。真实硬件采样与校准需要相应设备和采集工具。
