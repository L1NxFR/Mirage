---
aliases: [ "/other/agent-writing-syntax/" ]
author:
  - Codex
  - Claude
title: "文档写作语法"
description: 可复制的 YAML、Markdown、公式、图片、提示卡片和时间线示例。
content_lang: zh-CN
date: 2026-11-21
lastmod: 2026-11-23T01:35:11.298+08:00
draft: true
show_toc: true
weight: 2
---

## 一篇文档的基本结构

Markdown 文件开头是 YAML 元数据，两行 `---` 之间填写属性，后面写正文。以下内容可作为新文章的起点；日期应换成实际创建和修改日期。

```md
---
title: 我的实验记录
description: 一句话说明本文内容
subtitle: 可选副标题
content_lang: zh-CN
date: 2026-11-21
lastmod: 2026-11-21T23:25:10+01:00
author: ""
draft: true
show_toc: true
weight: 1
tags: [实验, 性能]
tldr: |
  **主要结论：** 这里填写摘要。

  - 摘要也可以使用列表。
---

## 问题

这里写正文。

## 方法

这里写方法与配置。

## 结果与局限

这里写证据、结论及适用范围。
```

| 属性 | 用法 |
| --- | --- |
| `title` | 页面标题，正文不用重复写一级标题 |
| `description` / `subtitle` | 简介 / 封面副标题 |
| `tldr` | 封面摘要，支持 Markdown；多行内容用 `\|` 后换行并缩进 |
| `date` / `lastmod` | 创建 / 修改时间；保留原始 `date`，修改时更新 `lastmod` |
| `author` | 留空继承站点默认作者 |
| `draft` | `true` 为草稿，显式 `false` 才发布 |
| `content_lang` | 中文用 `zh-CN`，英文可用 `en` |
| `show_toc` | 是否显示目录 |
| `weight` | 同级排序整数，越小越靠前 |
| `tags` | 标签列表 |

YAML 使用空格缩进，不用 Tab。标题含冒号、`#` 或以方括号开头时，建议加引号，例如 `title: "使用说明"`。带时区的修改时间可写成 `lastmod: 2026-11-21T16:30:00+01:00`。

## 作者与头像

用户和代理都以“头像 + 名字”署名。用户文档可填写 `author: 林楠`，留空则继承站点默认作者。代理文档必须明确填写实际作者，例如：

```yaml
author: Codex
```

Claude 或 Grok 撰写时分别使用 `author: Claude`、`author: Grok`。标题只写主题，无需 `[Agent]`。已有文件名不必更改。作者资料在 `dashboard/site/hugo.yaml` 的 `params.author_profiles` 中配置，Codex、Claude、Grok 使用官方图标，林楠使用 GitHub 用户 Languisher 的头像，图片保存在本地；单篇可用 `author_avatar: /images/authors/my-avatar.png` 覆盖。没有图片时显示通用人物图标，不使用字母头像。不要因修改文章而替换原作者，也不要猜测历史作者。

## 标题、段落和强调

```md
## 主节

### 子节

这是第一段。段落之间留一个空行。

这是第二段，包含 **粗体重点**、*斜体*、~~删除线~~ 和 `行内代码`。
```

正文主节用 `##`，再用 `###` 和 `####` 细分。项目中粗体显示为橙色强调，代码使用等宽字体。需要显示语法符号本身时，可放进代码，或用反斜杠转义，例如 `\*`。

## 列表、任务和引用

```md
- 第一项
- 第二项
  - 子项

1. 第一步
2. 第二步

- [x] 已完成
- [ ] 待处理

> 这是引用。
>
> 引用的第二段。
```

列表前后留空行，子项按层级缩进。普通任务列表使用 `[x]` 与 `[ ]`；进行中和失败状态使用后文的专用 `timeline` 块。

## 链接、图片和图注

```md
[项目使用方法]({{</* relref "agent-project-guide.md" */>}})
[相关工作栏目]({{</* relref "/related-work" */>}})
[下载 PDF](../../Attachments/paper.pdf)

![图 1：系统结构](../../Attachments/architecture.png)
![](../../Attachments/screenshot.png)
```

站内文档链接使用 Hugo 的 `relref` 自动生成页面地址；它在保存构建后生效，Obsidian 不会解析此 shortcode。当前站点不会自动将普通 `.md` 链接转换成页面 URL。

以上附件名是示例，使用前先放入真实文件。相对路径从当前 Markdown 文件所在目录计算：本文件夹 `other/project-guide/` 中的文章用 `../../Attachments/`；直接放在 `other/` 下的文章用 `../Attachments/`。

图片的替代文本会作为居中的图注，`![](...)` 不显示图注。可选的 `"title"` 只作悬停提示。为兼容网站与 Obsidian，优先使用标准 Markdown 链接和图片语法。

## 表格与代码块

```md
| 方法 | 延迟（ms） | 说明 |
| --- | ---: | --- |
| 基线 | 12.3 | 示例数据 |
| 候选方法 | 10.8 | 示例数据 |
```

分隔行的 `---:` 表示右对齐，`:---:` 表示居中。表格内的竖线用 `\|` 转义。示例数字仅演示排版，不代表项目结果。

三个反引号包围代码，开头可指定语言，例如 `python`、`sh`、`json` 或 `yaml`：

````md
```python
def mean(values):
    return sum(values) / len(values)
```
````

如果要在文档中展示三个反引号的写法，外层使用四个反引号，就像本指南中的示例。

## 数学公式

行内公式用 `$...$`，独立公式用 `$$...$$`：

```md
平均延迟为 $\bar{t} = \frac{1}{N}\sum_{i=1}^{N} t_i$。

$$
\mathrm{Speedup} = \frac{T_{\mathrm{baseline}}}{T_{\mathrm{method}}}
$$
```

也支持 `\(...\)`、`\[...\]` 和 `math` 代码块。公式通过 KaTeX 渲染，使用其支持的 LaTeX 数学命令；普通代码块内的美元符号不会被当成公式。

## 高亮与提示卡片

```md
==默认高亮==
==🔴红色== ==🟠橙色== ==🟡黄色==
==🟢绿色== ==🔵蓝色== ==🟣紫色==

> [!summary] 核心结论
> **这里写最重要的结论。**
>
> 这里补充条件、证据或局限。
```

高亮开头的颜色圆点用于选择颜色，不会显示在网站渲染后的文本中。提示卡片也支持 `[!note]` 等字母类型，当前共用相同外观。每行都要保留 `>`，空行也一样。`+`、`-` 标记会被识别，但网站卡片始终展开。

## 进度时间线

专用 `timeline` 代码块会渲染成进度时间线：

```timeline
# 项目进度
- [x] 完成文献阅读
- [/] 运行实验 {open}
  这里补充 **配置**、观察结果和下一步。
- [ ] 汇总报告
- [!] 失败的尝试
  记录失败原因和后续处理。
```

````md
```timeline
# 项目进度
- [x] 完成文献阅读
- [/] 运行实验 {open}
  这里补充 **配置**、观察结果和下一步。
- [ ] 汇总报告
- [!] 失败的尝试
  记录失败原因和后续处理。
```
````

`[x]` 表示完成，`[/]` 表示进行中，`[ ]` 表示未开始，`[!]` 表示失败。详情缩进两个空格，标题后的 `{open}` 使详情默认展开。在步骤前添加 `collapse: 2` 可折叠前两个步骤。代码块里的 `# 项目进度` 是时间线标题，不属于正文标题层级。

## 嵌入交互页面

自包含的 HTML 页面（如 `src/kv-trace` 生成的动画）放进 `Attachments/`，用 `embed-html` shortcode 嵌入为可交互的 iframe：

```md
{{</* embed-html src="../../Attachments/kv-cache-replay.html" title="KV Cache 行为回放" height="1000" */>}}
```

`src` 与 Markdown 链接一样按当前文件计算相对路径，且必须指向 `Attachments/`；发布地址经过 `relURL`，部署到子路径时仍然正确。`height` 是初始高度（像素），页面向父窗口发送 `{kvReplayHeight}` 消息时会自动调整。可选 `query` 追加到地址后，例如 `query="scenario=slow-d2h"`。图注下方附"新窗口打开"链接。shortcode 在保存后的站点构建中渲染，Obsidian 只显示原文。

## 写完后的检查

1. 检查 YAML 是否完整，草稿状态、日期、语言和排序是否正确。
2. 用分栏预览检查标题、表格、公式和图片；专用块以保存后的站点渲染结果为准。
3. 点击实际链接，确认附件存在，检查图注和相对路径。
4. 区分示例、假设、计划与实际结果，引用数据时注明来源。
5. 保存后检查页面；需要导出 PDF 时，再打开打印预览确认分页。

返回 [项目使用方法]({{< relref "agent-project-guide.md" >}})。


## 多作者共同署名

`author` 既支持单个名字，也支持按显示顺序填写的列表，每位作者都有自己的头像。

用户和代理共同创作：

```yaml
author: [林楠, Claude]
```

多个代理共同创作：

```yaml
author: [Claude, Codex]
```

只填写实际参与创作的作者，保留已有作者及其顺序，任何代理修改后均追加共同署名，包括格式调整和简单编辑。含用户署名的文档按用户文档保护。名字大小写会匹配作者资料，例如 `claude` 显示为 `Claude`。多作者的头像分别从 `params.author_profiles` 读取，单篇 `author_avatar` 仅在单作者时生效。不要将多个名字写成一个逗号分隔的字符串。


### 代理修改后的共同署名

修改既有文档时保留已有作者，将修改代理追加到 `author` 列表，页面并排显示各作者的头像与名字，作者之间仅留间距，不显示逗号，例如：

```yaml
author: [林楠, Claude, Codex]
```

每次代理修改文件后（包括格式调整），从项目根目录运行：

```sh
node dashboard/scripts/attribute-files.mjs --agent Codex dashboard/site/content/other/project-guide/agent-pstack-guide.md
node dashboard/scripts/attribute-files.mjs --check --agent Codex dashboard/site/content/other/project-guide/agent-pstack-guide.md
```

工具复用 Dashboard 的 `yaml` 依赖（先在 `dashboard/` 运行 `npm ci --ignore-scripts`）。用实际代理名替换 `Codex`，可传入多个本次修改文件；不登记别人尚未提交的改动。Dashboard 文档写入 `author`，其他文件登记在根目录 `.file-coauthors.json`。作者已存在时不重复追加。检查发现遗漏会返回非零退出码。仅启动服务器不能识别任意外部编辑器背后的代理，代理必须执行登记与检查命令。
