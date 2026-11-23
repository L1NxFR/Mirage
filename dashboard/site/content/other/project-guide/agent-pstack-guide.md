---
aliases: ["/other/agent-pstack-guide/"]
author: [Codex, Claude]
weight: 3
title: "pstack 初始化与使用指南"
content_lang: zh-CN
description: src 默认 skills 的安装范围、初始化、开发验证流程与维护方法。
date: 2026-11-21
lastmod: 2026-11-22T18:00:00+08:00
draft: true
show_toc: true
---

## 本项目已经配置了什么

`src/` 默认使用 [pstack-claude](https://github.com/michael-denyer/pstack-claude) 的 skills-only 工作流。它是 Lauren Tan 的 pstack 面向 Claude Code、Codex 等运行环境的移植版。本指南根据安装时的 [README](https://github.com/michael-denyer/pstack-claude/blob/97d2ba2790822939ee43db0d7856219ea96c450d/README.md)、[技能参考](https://github.com/michael-denyer/pstack-claude/blob/97d2ba2790822939ee43db0d7856219ea96c450d/docs/reference.md)及 [Codex 映射](https://github.com/michael-denyer/pstack-claude/blob/97d2ba2790822939ee43db0d7856219ea96c450d/plugins/pstack/skills/poteto-mode/references/codex-tools.md)编写。

| 项目 | 当前配置 |
| --- | --- |
| 安装内容 | 67 个上游 skills，连同各自的脚本、参考资料和 playbooks |
| 位置 | 实体 `.claude/skills/`（Claude Code）；`.agents/skills` 为指向它的符号链接（Codex）；均在项目根目录 |
| 固定提交 | `97d2ba2790822939ee43db0d7856219ea96c450d` |
| 默认入口 | `poteto-mode`，注意拼写是 poteto |
| 路由规则 | 根目录 `AGENTS.md` 指向 `src/AGENTS.md`，后者要求加载项目内入口 |
| 来源与校验 | `.agents/pstack/upstream.json` |
| 许可 | `.agents/pstack/` 下的 LICENSE 与 NOTICE 文件 |
| 作用范围 | src 开发任务；不改变其他项目的全局配置 |

安装采用 skill-installer 的 `--dest` 项目路径选项。上游 README 的共享安装示例使用用户级目录；这里将同一套 skills 放在项目根目录（不写入用户级目录），配合 AGENTS 规则用于 src 任务。没有安装原生插件、SessionStart hook，也没有安装 Bun、GitHub CLI 等可选运行依赖。

目前 src 仍没有可运行的研究实现，因此安装完成不代表项目已有验证技能或已完成初始化实验。

## 第一次使用

### 1. 从正确目录启动

从项目根目录启动 Claude Code 或 Codex，不需要进入 `src/`。Claude Code 读取根目录 `.claude/skills/`，用 `/poteto-mode` 调用；Codex 读取根目录 `.agents/skills`（指向同一目录的符号链接），用 `$` 搜索 `poteto-mode`，CLI 也可用 `/skills` 检查。新增或移动 skills 后，需新开会话才会刷新菜单。

菜单未发现 skill 时，可以直接这样说：

```text
请按 src/AGENTS.md 工作，读取 .claude/skills/poteto-mode/SKILL.md
（Codex 另读其中的 Codex 映射），再处理 src 任务。
```

本地 skills 调用使用 `$poteto-mode`。上游原生插件安装后，菜单可能插入 `$pstack:poteto-mode`；两者的命名方式不同，不要同时安装后凭名称猜来源。

### 2. 先明确项目和第一项任务

在聊天中提供目标、输入输出、约束和验收方式，例如：

```text
$poteto-mode 在 src 中初始化一个 Python 实验组件。
目标是比较两种缓存替换策略，先支持小型合成访问序列。
输出每种策略的命中率和执行时间；先不接入 GPU 或真实模型。
请先明确验收条件和目录结构，再实现最小可运行版本，
补齐依赖、README 和可复现验证命令。
```

这是任务模板，不是本项目已接受的研究目标。把它替换成实际需求。涉及用户所有的项目概览时，明确要求代理更新才会写入原文。

### 3. 按需配置模型

通常先用当前 Codex 会话提供的模型和工具。需要调整角色模型时再调用 `$setup-pstack`，并先说明配置范围。

上游 Codex 设置流程默认写入 `${CODEX_HOME:-~/.codex}/pstack-models.md`，并把模型行加入用户级 `AGENTS.md`，会影响其他项目。因此，本项目没有自动执行此步骤。若只希望本项目使用某些角色配置，应明确要求将适用的配置写入 `src/AGENTS.md`，由代理按当前可用模型核对，不把 Claude 的 `opus`、`sonnet` 原样传给 Codex。

```text
$setup-pstack 先列出当前会话可用的模型和角色配置建议。
我只想配置这个项目；不要改写用户级配置。
请说明如何将确认后的角色选择放入 src/AGENTS.md。
```

并行技能依赖宿主的子代理支持。上游 CLI 映射提到的 `multi_agent` 配置仅适用于相应运行环境；桌面会话以实际工具为准。独立审查缺失时，应报告审查受阻，不能用一次自审充数。

### 4. 有真实程序后，生成验证入口

当组件能启动、依赖和输入已明确后，运行：

```text
$create-verification-skill 为 src 中的实际组件建立项目验证技能。
使用项目位置 .claude/skills/verify/（Codex 经 .agents/skills 链接读取）。
从现有 README 和代码确认启动、输入、检查及清理方式。
生成 feature map，并至少真实跑通一个功能，保留证据。
```

生成的 `verify` 应回答：如何启动、如何检查环境、如何驱动真实功能、成功表现是什么、证据保存在哪、如何清理。feature map 记录功能入口、操作步骤、预期结果和容易遗漏的前提。

对于 CLI 或研究代码，证据可以是命令、退出码、输出文件和结果对比；没有 UI 就不必编造浏览器步骤。对于性能实验，还要固定数据、环境、种子、基线与测量范围。先运行生成的流程，再把它作为后续任务的验证入口。

## 日常开发的关键步骤

1. **交代任务与验收。** 说明期望行为、失败样例、范围和必须保留的约束；让代理读取相关项目记录。
2. **选择流程。** `poteto-mode` 依据任务进入缺陷修复、功能、重构、性能调查等 playbook。单文件机械修改可直接处理。
3. **先收集证据。** 缺陷先复现；性能先测基线；接口变更先确认调用方和边界。
4. **实施最小完整修改。** 把工作拆成可验证的步骤，需要时调用架构分析、并行方案或独立审查。
5. **真实验证。** 运行项目的 `verify`、回归检查及相关测试；性能主张必须有同条件测量。报告通过、失败、受阻和未运行项。
6. **维护知识。** 行为或入口变化后更新 feature map；实验和失败写入代理标记的 Dashboard 记录。
7. **按授权交付。** 本地修改、提交、推送、创建 PR 和合并是不同动作；需要后者时在任务中说明。安装 skills 本身没有授权自动合并。

常用请求可以直接复制后替换内容：

```text
$poteto-mode 修复 src 中的这个问题：<现象>。
复现输入是 <输入>，预期是 <结果>。先复现，再修复并跑回归检查。
```

```text
$poteto-mode 调查 <组件> 的性能瓶颈。
使用 <数据与配置>，先记录基线，再做一项改动并比较。
分别报告正确性、延迟、吞吐量和资源消耗，不把推测写成测量结果。
```

```text
$maintain-verification-skill 根据本次 src 改动更新 verify 和 feature map，
实际重跑受影响路径，保留证据并列出未验证部分。
```

## 常用技能怎么选

下表概括安装版本的技能用途，具体步骤以对应 `SKILL.md` 为准。

| 场景 | 技能 | 使用时关注什么 |
| --- | --- | --- |
| 不确定该用哪套流程 | `poteto-mode` / `poteto-help` | 给出目标和约束，由入口选择流程 |
| 理解机制与原因 | `how` / `why` | 结论要能追溯到代码和证据 |
| 设计与方案比较 | `architect` / `arena` | 明确约束、取舍和评价标准 |
| 实现与回归 | `tdd` | 覆盖外部可观察行为 |
| 验证真实程序 | `create-verification-skill` / `maintain-verification-skill` | 建立并维护可执行验证与功能地图 |
| 性能测量 | `benchmark-checklist` | 保证基线和比较条件可比 |
| 独立质疑与审查 | `interrogate` / `thermos` | 审查证据与修改范围，工具不可用时报告限制 |
| 简化与清理 | `unslop` / `deslop` | 保留行为，控制无关改动 |
| 处理 PR 与 CI | `get-pr-comments` / `fix-ci` / `babysit` | 需要仓库、登录状态及明确授权 |
| 留下过程与教训 | `show-me-your-work` / `reflect` | 记录依据，避免将未经检查的会话内容发布出去 |

不需要每次把全部技能跑一遍。先用入口完成一个小任务，再按实际问题增加专门步骤。

## 如何借鉴 Lauren Tan 的方法

指定参考文章是 [Toby’s Guide：Lauren Tan — How I Merged 1000 PRs in a Month with Agents](https://tobysguide.com/episodes/2026-08-24-lauren-tan-1000-prs-with-agents/)。它强调先让代理能够运行并验证产品，借助 feature map 复现问题，并逐步扩大自动化范围；也讨论了技能评测和用架构、静态检查及 CI 落实约束。

在这个科研模板里，可按以下顺序实践：

- 先完成一个本地任务的“输入—执行—可观察结果”闭环，再考虑多个并行任务。
- 把重复失败转成回归用例或检查命令；需要技能承载操作知识时，再沉淀为项目技能。
- 评估新技能时，使用预先确定的代表性任务和评分标准，保留失败案例，避免只对单个样例调提示词。
- 将能机器检查的约束落实到代码或检查脚本，例如结果 schema、数据范围和依赖边界。

这些是本项目的采用建议，尚未执行技能效果评测。文章中的 PR 数量是访谈案例，不是本项目的效率承诺；自动合并、禁用某个框架 API 或禁注释也不应直接照搬成研究项目规则。

## 安装方式与更新

### 已克隆本模板

技能文件随模板保存在 src 下，无需再次联网安装。先按 `src/README.md` 中的 Python 命令校验文件，再从 src 会话使用。校验只证明上游文件未发生变化，不证明每个技能在当前宿主中都可执行。

### 从零复现此次安装

有 skill-installer 的 Codex 环境可以让代理执行以下安装过程。`<固定提交>` 使用上表 SHA，`<技能路径列表>` 应包含该提交 `plugins/pstack/skills/` 下所有带 `SKILL.md` 的目录，不能只安装入口而遗漏其引用的技能。

```text
请使用 skill-installer，从 michael-denyer/pstack-claude 的固定提交
97d2ba2790822939ee43db0d7856219ea96c450d 安装全部 67 个 skills，
目标为本项目根目录 .claude/skills（.agents/skills 是指向它的符号链接），保留许可证、来源和校验清单。
不要覆盖已有目录，也不要修改全局 skills。
```

底层脚本接口如下；尖括号内容是待替换参数，不能原样执行：

```text
python3 <skill-installer目录>/scripts/install-skill-from-github.py \
  --repo michael-denyer/pstack-claude --ref <固定提交> \
  --dest <项目绝对路径>/.claude/skills --path <技能路径列表>
```

### 原生插件是另一种选择

上游 README 给出的 Codex 原生安装命令为：

```sh
codex plugin marketplace add michael-denyer/pstack-claude
codex plugin add pstack@pstack-claude
```

原生插件提供 hook 集成，并要求在 `/hooks` 中信任 hook。本次没有执行这两条命令。若以后改用原生插件，应先处理同名技能来源和 src 的路由规则，避免两套版本并存；不能假定插件安装也只影响 src。

### 升级与撤销

升级时先查看新版本 README 与差异，选择新的固定提交，安装到临时目录，核对技能增删、脚本依赖和 Codex 映射，再替换已确认的上游技能并更新校验清单。保留自己生成的 `verify` 等项目技能。安装脚本遇到已存在的目录会退出；不要直接对整个 skills 目录做清空操作。

撤销默认路由时，移除根目录 AGENTS 中的 `src 默认 skills` 段及 src AGENTS 中的 pstack 路由规则。随后按清单删除确属此次安装的上游技能，保留项目自建技能。`session hook: off` 对这里的 AGENTS 路由无效。

## 验收范围与常见问题

- **菜单找不到技能：** 确认会话从项目根目录启动，且 `.agents/skills` 链接指向 `../.claude/skills`；重新开启会话，或按上面的路径显式读取入口。
- **要求 Claude 专用工具或模型：** 先读取安装目录中的 Codex 映射，以当前会话能力为准。
- **无法并行或独立审查：** 报告宿主限制；单次顺序分析不能冒充多个独立意见。
- **没有项目验证命令：** 先实现最小可运行组件。Dashboard 的 `npm run build` 和 `npm run test:workspace` 不能验证研究实现。
- **安装验证与工作流验证：** 文件数量、内容哈希、路由规则和文档构建可以在安装阶段检查；真实项目端到端验证、性能实验与多模型技能评测需等到具体任务再执行。

本文保留为本地草稿，可在 Dashboard 的“其他”栏目查看；发布前需另行授权修改 `draft`。
