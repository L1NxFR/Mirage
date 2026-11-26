---
weight: 1
content_lang: zh-CN
title: 两级内存硬件参数调研：NVIDIA、AMD 与 3D DRAM 对照
subtitle: ""
date: 2026-11-25T17:42:33+08:00
lastmod: 2026-11-26T01:24:13+08:00
author: Claude
draft: true
description: 把现有 NVIDIA、AMD 和 3D DRAM 设计的公开参数对应到两级 DRAM 模拟器的输入，并对照当前 EXI 取值。
tldr: |
  当前 EXI 取值中，问题最大的是建模口径，而不是单个硬件数字：模拟器让一张卡装下整个 DeepSeek-V4-Pro，而架构表是 8 卡系统，按专家并行切分后每卡只需约 101–129 GB，每次 prefill 只搬约 97 GB。硬件数字中，一级每 GB 18/36 = 0.5 TB/s，是 HBM 产品的 6–18 倍、已流片 3D DRAM 的 2.5 倍；二级 2.2 TB/s 约需 1375 根 LPDDR6 数据线，超过 Vera CPU 的整个内存接口；复制效率 1.0、开销 0、访存效率 1.0 都比真实系统乐观。
categories: []
tags: [two-tier-dram, hardware, aisim]
show_toc: true
---

## 结论

当前 EXI 取值的主要问题按影响排序：

1. **单卡装整模型**（影响最大）：模拟器原先只建模一张卡，让它装下整个 DeepSeek-V4-Pro（805.7 GB）。二级放不下，这些运行都是反事实运行，结果已移除。EXI 架构表描述的是 8 卡系统。按 8 路专家并行（EP8）切分后：
   - **每卡容量**：注意力等非专家权重每卡复制一份时约 128.7 GB，刚好超过 128 GB；也切分时约 100.7 GB。
   - **每卡搬运**：每次 prefill 只搬约 96.7 GB，约 44 ms。

   EP8 结果见[两级 DRAM 在 8 卡专家并行下的闭环结果](../../research-journey/two-tier-dram-expert-parallel/)：prefill 搬专家不再主导，36 GB 一级的主要开销变为 decode 逐层轮换非专家权重。
2. **一级带宽与容量之比**：18 TB/s ÷ 36 GB = 0.5 TB/s/GB。HBM 产品为 0.03–0.08，已流片的混合键合 3D DRAM 测试芯片约 0.2。这不是不可能，但没有任何已发布产品或流片结果支撑。
3. **二级带宽**：128 GB LPDDR6 提供 2.2 TB/s，约需 57 个 x24 通道、1375 根数据线（14.4 Gbps）。这超过 NVIDIA Vera CPU 整个 1.2 TB/s 的 LPDDR5X 接口。1.1 TB/s 与 Vera 同级，更接近现实上限。
4. **效率与开销**：EXI 配置用复制效率 1.0、每次传输开销 0、访存效率 1.0、访存固定延迟 0。真实系统的对应值：
   - **复制效率**：GH200 实测 0.74（相对 LPDDR 标称）或 0.84（相对 C2C 单向）；PCIe Gen5 约 0.8。
   - **每次传输开销**：PCIe 每次传输 1–3 µs。
   - **访存效率与固定延迟**：AISim 自带的全部 NVIDIA 预设都用访存效率 0.8 和 3 µs 固定延迟。

   因此在同一个 AISim 模型下，EXI 比 B200 等真实 GPU 乐观约 25%。

## 模拟器参数对应什么

| 模拟器参数 | 位置 | 真实硬件中的对应量 |
| --- | --- | --- |
| `tier1_gb` | `two_tier_dram` | 加速器近端内存容量（HBM、3D DRAM 或 SRAM） |
| 一级读带宽 `gpu.mem_bw` | 系统文件 | 近端内存带宽；AISim 用它给计算定价 |
| `mem_bw_empirical_scaling_factor`、`mem_empirical_constant_latency` | 系统文件 | 实际可达带宽比例、每次访存的固定延迟。AISim 的 NVIDIA 预设为 0.8 和 3 µs |
| `fp8_tc_flops`、`fp4_tc_flops` 等 | 系统文件 | 稠密算力峰值（注意区分稀疏与稠密） |
| `tier2_gb` | `two_tier_dram` | 远端大容量内存（LPDDR5X、DDR5 主机内存） |
| `tier2_bandwidth_gbps` × `copy_efficiency` | `two_tier_dram` | 二级到一级的有效复制带宽。真实系统中为 min(远端内存带宽, 互连单向带宽) × 实测效率 |
| `link_overhead_ms` | `two_tier_dram` | 每次 DMA 传输的固定开销 |
| `scratch_gb` | `two_tier_dram` | 激活等工作区；无对应产品参数 |

模型目前不覆盖以下真实行为：
- **直接读远端内存**：GH200 的 GPU 可以不经复制直接读 LPDDR5X，实测约 419 GB/s；模型要求先复制到一级。
- **共享争用**：没有建模 CPU 与 GPU 共用 LPDDR 带宽，也没有建模复制写入与计算读取争用一级带宽。
- **多卡**：支持 attention-DP 加专家并行（EP8 下每卡持有 1/8 路由专家，见[专家并行记录](../../research-journey/two-tier-dram-expert-parallel/)）；不支持注意力侧 TP 切分非专家权重。

## 现有架构参数（每个加速器）

标注：**规格** = 厂商公布；**实测** = 论文或基准测试；**推算** = 本文按公开数字计算。

| 设计 | 一级（容量／带宽） | 每 GB 带宽 | 二级（容量／带宽） | 一、二级之间 | 算力（稠密） |
| --- | --- | --- | --- | --- | --- |
| NVIDIA GH200 | 96 GB HBM3，4.0 TB/s 规格；3.4 TB/s 实测 | 0.042 | 480 GB LPDDR5X，最高 546 GB/s 规格（出货版多为 512 GB/s）；486 GB/s 实测 | NVLink-C2C 450 GB/s 单向规格；主机到设备 375–380 GB/s 实测，设备到主机约 297 GB/s 实测 | FP8 约 1.98 PF |
| NVIDIA GB200（每颗 B200） | 186 GB HBM3e，8 TB/s | 0.043 | 一颗 Grace 带两颗 GPU：480 GB、512 GB/s 由两颗共享 | C2C 900 GB/s 双向由两颗共享，每颗约 225 GB/s 单向（推算）；NVIDIA 调优指南给出 4 GPU 系统设备到主机约 170 GB/s | FP8 5 PF、FP4 10 PF（AISim 预设） |
| NVIDIA GB300（每颗 B300） | 288 GB HBM3e，8 TB/s | 0.028 | 同 GB200 | 同 GB200 | FP4 15 PF（AISim 预设） |
| NVIDIA Vera Rubin（每颗 Rubin） | 288 GB HBM4，22 TB/s | 0.076 | 一颗 Vera 带两颗 GPU：1.5 TB LPDDR5X、1.2 TB/s 由两颗共享 | C2C 1.8 TB/s 双向由两颗共享，每颗约 450 GB/s 单向（推算） | NVFP4 训练 35 PF 稠密、推理 50 PF；FP8 稠密未在来源中给出 |
| AMD MI355X | 288 GB HBM3E，8 TB/s | 0.028 | 主机 DDR5，容量取决于服务器 | PCIe Gen5 x16，约 63 GB/s 单向理论；同代 PCIe 上 H100 实测 50–54 GB/s | FP8 5.0 PF、FP4 10.1 PF；1400 W |
| AMD MI455X | 432 GB HBM4，19.6 TB/s（2025 年公布）；第三方转述 AMD 页面为 23.3 TB/s | 0.045–0.054 | 主机 CPU（EPYC Venice，每 4 颗 GPU 一颗） | 未查到公开规格 | FP8 20 PF、FP4 40 PF（AMD 公布） |
| d-Matrix Corsair（每卡） | 2 GB SRAM，150 TB/s（片上） | 75 | 256 GB LPDDR5，400 GB/s | 同封装 | 8 bit 2.4 PF、4 bit 9.6 PF；600 W |
| 混合键合 3D DRAM 测试芯片（ATLAS） | 约 80 GB（4 层 DRAM），16 TB/s | 0.2 | 无 | 无 | FP16 253 TF；242 W |
| HBM4 单堆栈 | 36–48 GB；2.0 TB/s（JEDEC），2.8–3.3 TB/s（出货） | 0.04–0.09 | — | — | — |
| **EXI-3DDRAM（当前取值）** | 36 GB，18 TB/s | **0.5** | 128 GB LPDDR6，2.2 TB/s（对照 1.1） | 未给出；模型假设复制只受二级带宽限制 | FP8 2.95 PF、FP4 6.13 PF；675 W |

二级带宽与容量之比（GB/s 每 GB）：
- Grace 1.07，Vera 0.8，Corsair 1.56；
- EXI 在 2.2 TB/s 时为 17.2，在 1.1 TB/s 时为 8.6。

LPDDR6 每个 x24 通道在 14.4 Gbps 时有效带宽为 38.4 GB/s，在 10.667 Gbps 时约 28.4 GB/s。所需通道数：
- **2.2 TB/s**：57–77 个通道，1375–1859 根数据线；
- **1.1 TB/s**：29–39 个通道。

作为参照，Vera 用 8 个 SOCAMM 模组达到 1.2 TB/s。

## EXI 取值逐项判断

| 参数 | 当前 | 参照 | 判断 |
| --- | --- | --- | --- |
| 部署口径 | 单卡、TP1、整模型 | 架构表为 8 卡；MI455X、Rubin 都按机架级 EP 部署 | **已改**。闭环模型已支持 EP8：每卡 128.7 GB，prefill 每卡搬 96.7 GB 专家（原来是整套 773.7 GB） |
| 一级容量 | 36 GB | HBM4 单堆栈 36–48 GB；3D DRAM 测试芯片约 80 GB | 合理（约一个 HBM4 堆栈） |
| 一级带宽 | 18 TB/s | 同容量 HBM4 为 2–3.3 TB/s；3D DRAM 测试芯片为 16 TB/s/80 GB | **偏高**。建议同时扫描 8 TB/s（0.2 TB/s/GB，测试芯片水平）和 18 TB/s |
| 访存效率／固定延迟 | 1.0 / 0 | AISim NVIDIA 预设 0.8 / 3 µs；GH200 HBM3 实测 0.85 | **偏乐观**。建议 0.8 / 3 µs，与 B200 对照口径一致 |
| 二级容量 | 128 GB（范围 64–512） | Grace 480 GB、Vera 1.5 TB（每两颗 GPU） | 单卡口径下远不够；EP8 每卡需 128.7 GB，128 GB 被拒绝，192 GB 可行 |
| 二级带宽 | 2.2 TB/s（对照 1.1） | Grace 0.5、Vera 1.2、Corsair 0.4 TB/s | **偏高**。建议以 1.1 TB/s 为基线，2.2 TB/s 作上限 |
| 复制效率 | 1.0（对照 0.7） | GH200 0.74–0.84、PCIe Gen5 约 0.8 | **偏乐观**。建议 0.75–0.85 |
| 每次传输开销 | 0 | PCIe 每次传输 1–3 µs；Gen3 实测 1.125 µs | **偏乐观**。建议 1–3 µs |
| 算力 | FP8 2.95 PF、FP4 6.13 PF @675 W | B200 FP8 4.5 PF；MI355X FP8 5.0 PF @1400 W | 每瓦水平与同代相当，未发现问题 |
| 卡间带宽 | 1.6 TB/s 双向 | NVLink 5 1.8 TB/s，NVLink 6／MI455X 3.6 TB/s | B200 同级；EP 建模时会用到 |
| scratch | 4 GB | 无产品参数 | 决定 36 GB 能否常驻非专家权重（32 + 4 = 36），需要依据 |

## 可直接填写的预设

以下数值可直接填入 `two_tier_dram` 和系统文件。有效复制带宽由模型计算为 `tier2_bandwidth_gbps × copy_efficiency`。对 C2C 系统，`tier2_bandwidth_gbps` 取远端内存与互连单向带宽中较小的一个。

| 预设 | `tier1_gb` | 一级带宽 × 效率 | `tier2_gb` | `tier2_bandwidth_gbps` | `copy_efficiency` | `link_overhead_ms` | 依据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| GH200 | 96 | 4.0 TB/s × 0.85 | 480 | 450 | 0.84 | 0.001–0.003 | 实测 377 GB/s ÷ 450 |
| GB200（每颗 B200） | 186 | 8.0 TB/s × 0.8 | 240 | 225 | 0.75（参照 170 GB/s 设备到主机指南值） | 0.001–0.003 | 推算：共享 Grace 与 C2C |
| Vera Rubin（每颗 Rubin） | 288 | 22 TB/s × 0.8 | 750 | 450 | 0.84（未实测，沿用 GH200） | 0.001–0.003 | 推算：共享 Vera 与 C2C |
| MI355X + 主机 DDR5 | 288 | 8 TB/s × 0.8 | 按服务器 | 63 | 0.8 | 0.001–0.003 | PCIe Gen5 x16 |
| EXI 修正基线 | 36 | 18 TB/s × 0.8（另扫 8 TB/s） | 192（EP8 每卡需 128.7） | 1100（上限 2200） | 0.8 | 0.002 | 本文判断 |

GB200、Rubin 和 MI355X 的一级都能放下 DeepSeek-V4-Pro 的非专家权重。它们在 EP 部署中的专家路径，正好可以作为 EXI 的对照组。

## 后续工作

- ~~给闭环模型加专家并行~~：已完成，见[两级 DRAM 在 8 卡专家并行下的闭环结果](../../research-journey/two-tier-dram-expert-parallel/)。EP8 下每卡需 128.7 GB；36 GB 一级的主要开销变为 decode 逐层轮换非专家权重。
- 新增 GH200、GB200 与 MI355X 预设，在同一负载下与 EXI 对照。
- 区分直接读远端内存与先复制：GH200 类系统可以不复制，直接读取。

## 来源

- NVIDIA：[Grace Hopper 架构](https://developer.nvidia.com/blog/nvidia-grace-hopper-superchip-architecture-in-depth/)、[Vera Rubin 平台](https://developer.nvidia.com/blog/inside-the-nvidia-rubin-platform-six-new-chips-one-ai-supercomputer/)、[Vera Rubin NVL72](https://www.nvidia.com/en-in/data-center/vera-rubin-nvl72/)、[Grace 调优指南：健康检查](https://docs.nvidia.com/dccpu/grace-perf-tuning-guide/health-checks.html)
- GH200 实测：[HPCwire 对 Hopper 带宽论文的报道](https://www.hpcwire.com/2024/07/15/researchers-say-memory-bandwidth-and-nvlink-speeds-in-hopper-not-so-simple/)、[2×GH200 基准](https://dnhkng.github.io/posts/gh200-benchmarking/)、[Grace Hopper 数据移动研究（arXiv 2408.11556）](https://arxiv.org/html/2408.11556v2)
- GB200：[Spheron GB200 NVL72](https://www.spheron.network/blog/nvidia-gb200-nvl72-guide/)、[Vast.ai GB200](https://vast.ai/article/gb200-superchip-now-on-vast-ai)
- AMD：[MI350 系列与 MI400](https://www.amd.com/en/blogs/2025/amd-instinct-mi350-series-and-beyond-accelerating-the-future-of-ai-and-hpc.html)、[MI355X 产品手册](https://www.amd.com/content/dam/amd/en/documents/instinct-tech-docs/product-briefs/amd-instinct-mi355x-gpu-brochure.pdf)、[SemiAnalysis MI355X](https://inferencex.semianalysis.com/chips/mi355x)、[MI450 规格汇总](https://mirrorfrog.com/en/docs/cards/amd/mi450/)、[HotHardware MI450](https://hothardware.com/news/instinct-mi400-challenge-vera-rubin)
- 内存标准：[JEDEC HBM4](https://www.allaboutcircuits.com/news/jedec-officially-releases-hbm4-memory-standard/)、[LPDDR6（ISSCC 2026）](https://morethanmoore.substack.com/p/lpddr6-samsungsk-hynix-at-isscc-2026)、[Synopsys LPDDR6 报告](https://www.jedec.org/sites/default/files/Brett%20Murdock_FINAL_Mobile_2024.pdf)
- 3D DRAM 与近存：[ATLAS：3D DRAM LLM 加速器评估（arXiv 2604.08044）](https://arxiv.org/html/2604.08044v1)、[Samsung zHBM（DigiTimes）](https://www.digitimes.com/news/a20260805VL200/samsung-2026-nand-dram-3d.html)、[d-Matrix Corsair 产品简介](https://d-matrix.ai/pdf/d-Matrix-Corsair-Product-Brief-FINAL.pdf)、[Qualcomm AI250（The Register）](https://www.theregister.com/systems/2026/06/30/qualcomms-proposed-solution-to-catch-up-in-ai-infra-bury-the-compute-under-the-dram/5264071)
- PCIe 实测：[NVIDIA 论坛：H100 PCIe 吞吐](https://forums.developer.nvidia.com/t/question-about-pci-e-transfer-throughput/328759)、[NVIDIA 论坛：主机到设备带宽](https://forums.developer.nvidia.com/t/cudamemcpy-speed-bandwidth-for-host-to-device/10482)
- AISim 预设：`src/aisim/python/aisim/src/aisim_core/systems/*.yaml`（i163v，AISim `528193d`）；EXI 预设：`src/two-tier-dram/systems/exi_3ddram.yaml`。

第三方汇总站点的数字已标注来源；MI455X 带宽、GB200 每颗 GPU 的 C2C 份额和 Rubin FP8 稠密算力仍需厂商原始文档确认。
