---
aliases: ["/other/agent-project-guide/"]
author: Codex
title: "项目使用方法"
description: 从启动 Dashboard 到组织记录、编辑文档与导出 PDF。
content_lang: zh-CN
date: 2026-11-21
lastmod: 2026-11-21T23:25:10+01:00
draft: true
show_toc: true
weight: 1
---

## 这个项目用来做什么

用 Dashboard 管理项目记录，用 `src/` 存放实现、实验与评估代码。当前项目概览尚未填写，使用时先补充实际目标、范围、验收标准与下一步。

| 栏目 | 适合记录的内容 | 相对于项目根目录的位置 |
| --- | --- | --- |
| 项目概览 | 目标、约束、当前进展、下一步 | `dashboard/site/content/_index.md` |
| 相关工作 | 论文阅读、方法对比、文献分析 | `dashboard/site/content/related-work/` |
| 研究 | 研究问题、实验发现、失败与局限 | `dashboard/site/content/research-journey/` |
| 实验 | 架构、接口、实现与设计决策 | `dashboard/site/content/system-implementation/` |
| 归档 | 历史记录与阶段性材料 | `dashboard/site/content/meetings/` |
| 其他 | 使用说明、语法速查与通用参考 | `dashboard/site/content/other/` |

## 启动本地 Dashboard

需要 Node.js 22+ 和 Hugo。以下命令从项目根目录执行：

```sh
cd dashboard
npm ci --ignore-scripts
npm run dev
```

依赖已安装时，直接在 `dashboard/` 运行 `npm run dev`，也可使用 `pnpm dev`。启动器从端口 `23130` 开始寻找可用端口，打开日志打印的实际地址即可。按 `Ctrl+C` 停止服务。

指定其他起始端口：

```sh
npm run dev -- --port 24130
```

源码或 Markdown 保存后，服务会重新构建，页面随后自动刷新。编辑器或对话框打开时会暂缓刷新。若修改了启动脚本等服务代码，重启开发服务器。

## 创建和编辑文档

### 在网页中操作

1. 打开目标栏目，例如顶部的“其他”。
2. 点击侧栏 **+**，选择文档或分组，填写标题和上级分组。
3. 在 **编辑 Markdown** 中写正文，在 **文档属性** 中编辑 YAML，在 **内容摘要** 中填写封面摘要。
4. 点击保存或按 `⌘S / Ctrl+S`。保存会写入本地 Markdown 并更新 `lastmod`。

编辑器提供编辑、分栏与预览视图。文档的 **⋯** 菜单可用于重命名、移动、复制、置顶、导出和删除；删除的原文移入本地 `.workspace-trash` 备份目录。若外部编辑器同时改过文件，网页保存会提示冲突，应保留自己的内容并重新读取最新版本。

### 在终端中创建

在 `dashboard/` 运行：

```sh
pnpm run add "我的第一篇记录"
```

按提示输入 `1`–`5` 或完整栏目目录名。选择 `5` 或输入 `other`，即创建到“其他”。输入 `q` 取消；同名文件不会覆盖。也可以使用：

```sh
npm run add -- "我的第一篇记录"
```

`pnpm add` 是安装依赖命令，创建文章要写成 `pnpm run add`。

### 在 Obsidian 或文本编辑器中写作

将 `dashboard/site/content/` 作为 Obsidian 仓库打开，也可直接用 VS Code 编辑 Markdown。Obsidian 的模板放在 `Templates/`；启用并信任 Templater 后，新建空笔记按文件夹规则插入模板，“其他”使用根目录的通用模板。

运行中的开发服务会为记录栏目中的外部新建空白 Markdown 补齐默认 YAML；已有正文的文件只补缺失的排序权重。未运行服务时，VS Code 本身不会插入模板。

## 导航、分组和排序

- 页眉搜索或 `⌘K / Ctrl+K` 打开全站搜索；侧栏搜索筛选当前栏目，`⌘J / Ctrl+J` 聚焦侧栏搜索。
- 在栏目下创建子目录可组织分组，分组首页使用 `_index.md`。
- 同一分组的文档按整数 `weight` 排序，数字越小越靠前；相同权重再按标题排序。新文档默认排在同级末尾。
- `title` 控制页面标题，文件名决定路径。重命名或移动后检查引用链接。

## 图片、附件与导出

附件放到 `dashboard/site/content/Attachments/`。从本篇所在的 `other/project-guide/` 引用附件时使用 `../../Attachments/文件名`。图片和图注语法见 [文档写作语法]({{< relref "agent-writing-syntax.md" >}})。Excalidraw 源文件放在 `Excalidraw/`，文档引用导出的 SVG。

打开文章，按 `⌘P / Ctrl+P`，选择“另存为 PDF”，页边距使用默认值。打印布局会展开已加载的折叠内容，并处理长代码和表格换行。Markdown 原文可通过文档下载或导出功能保存。

## 草稿、构建与发布

新文档默认 `draft: true`：本地开发预览可见，正式构建不生成文章。准备发布时，显式改成 `draft: false`，同时检查相关栏目索引的发布状态。仅执行本地保存或构建不会上传网站。

在 `dashboard/` 中运行：

```sh
npm run build
npm run test:workspace
```

构建产物位于 `site/public/`。这些检查验证 Dashboard，不验证 `src/` 中的项目实现。当前部署工作流位于 `dashboard/.github/workflows/deploy.yml`；启用 GitHub Actions 需要将其移至项目根目录 `.github/workflows/` 并适配路径。

`Attachments/` 中的非 Markdown 文件、`Excalidraw/` 中的 SVG 即使只被草稿引用，也会进入构建产物；大型数据、模型和私密附件应另行保存，在记录中注明版本及位置。

## 项目协作习惯

先明确任务和验收标准，再实现、验证和记录。实验记录应包含代码版本、命令、配置、数据范围、环境、随机种子、指标、基线、产物位置和局限；区分已验证结果、假设和计划。

代理创建的文章填写实际 `author`（如 `Codex`、`Claude`、`Grok`），标题只写主题。用户与代理均显示“头像 + 名字”。已有 `agent-` 路径保留兼容；没有代理署名或历史代理标记的文档视为用户所有，代理仅在用户要求时修改。页面标题由 YAML 自动生成，正文从 `##` 开始；完整示例见 [文档写作语法]({{< relref "agent-writing-syntax.md" >}})。
