# Mirage Dashboard

基于 Hugo 的中文科研记录工具，提供分层目录、论文卡片、进度时间线、阅读工具和本地 Markdown 编辑。

## 页面与目录

| 页面 | URL | 内容位置 |
| --- | --- | --- |
| 项目概览 | `/` | `site/content/_index.md` |
| 相关工作 | `/related-work/` | `site/content/related-work/` |
| 研究 | `/research-journey/` | `site/content/research-journey/` |
| 文档 | `/system-implementation/` | `site/content/system-implementation/` |
| 会议记录 | `/meetings/` | `site/content/meetings/` |

四个记录栏目使用可展开的文件夹层级、点状引导线和右侧最后更新日期。文档保留栏目导航、目录、Markdown 编辑与下载功能。搜索覆盖已发布记录和项目概览；关于、标签、分类和简历页面不生成。

项目概览和栏目文档共用封面、正文排版、标题编号、目录与编辑下载工具。写作模板位于 `site/content/Templates/`。修改 `site/hugo.yaml` 可配置项目名称和仓库链接。

## 本地运行

需要 Node.js 22+ 和 Hugo 0.146.0+（用于显式时区转换）。在当前 `dashboard/` 目录执行：

```sh
npm ci --ignore-scripts
npm run dev
npm run build
```

在任意新机器上执行 `pnpm dev`（或 `npm run dev`）时，启动器默认从 `23130` 开始，按顺序跳过已占用端口，直到成功监听。请打开启动日志打印的实际地址。用 `pnpm dev --port 24130`（或 `npm run dev -- --port 24130`）可指定其他起始端口，同样保留递增规则。Hugo 本地 `baseURL`、Host 校验、Origin 校验及文档保存和重建均统一使用实际端口。这是随项目迁移的运行规则，`site/hugo.yaml` 保留可移植的发布地址配置，无需记录某台机器的空闲端口。服务器仅监听本机回环地址，编辑直接保存到本副本。

`npm run test:workspace` 包含启动回归检查，需要 Hugo 和本机回环端口监听权限；测试在独立临时站点中检查连续端口占用和切换端口后的保存。

构建产物位于 `site/public/`，不纳入 Git。构建会清理过期产物，避免已删除页面继续存在。

## 浏览器编辑

- 左侧搜索按标题和正文筛选当前栏目的文档。按 **⌘J / Ctrl+J** 聚焦搜索框。
- 点击 **+**，选择**文档**或**分组**，填写标题和上级分组。新文档以草稿形式打开编辑器；空分组也会显示。本地导航显示草稿及其标记，正式构建排除草稿。准备发布时，在**文档属性**中设置 `draft: false`。
- **编辑 Markdown** 打开 CodeMirror 编辑器，支持语法高亮、行号、撤销、重做、格式快捷键以及**编辑 / 分栏 / 预览**三种视图。
- **内容摘要**支持 Markdown，与元数据 `tldr` 同步，在实时预览和文档封面中显示。已有文档无需额外设置；留空则不显示。YAML 无效时暂时禁用摘要输入，须先在**文档属性**中修正。
- **文档属性**保存 YAML 元数据。公式预览支持 `$...$`、`\(...\)`、`$$...$$`、`\[...\]` 和 `math` 代码块，使用本地 KaTeX 资源；普通代码保持原样。未完成的公式会显示错误提示，便于保存前修正。
- 点击**保存**或按 **⌘S / Ctrl+S**，将 Markdown 写入本地仓库，更新 `lastmod` 并重新构建。关闭编辑器后可看到更新后的页面。未保存时关闭或离开会提示确认。
- 如果文件已在 Obsidian 或其他编辑器中修改，保存会停止并提示冲突，当前编辑内容仍可复制。放弃未保存修改后重新打开编辑器，即可读取最新文件。
- 元数据无效或 Hugo 构建失败时，保留先前保存的文档。预览支持标准 Markdown；Hugo 专用 shortcode 在保存后的站点构建中渲染。
- 文档的 **⋯** 菜单支持重命名、编辑、复制链接、在新标签页打开、移出目录、复制、移动、导出、置顶和删除。删除将原文移至本地 `.workspace-trash` 备份目录。

外部修改内容、布局、样式或配置后，本地站点会重新构建；刷新浏览器即可查看。静态 GitHub Pages 站点只读；本地写入 API 及其会话令牌不进入构建产物。

## 添加记录

在对应栏目目录中创建 Markdown 文件。子目录会显示为分组。可在 `site/data/journal_navigation.yaml` 中配置文件夹显示名称。

```yaml
---
title: 首次实验
content_lang: zh-CN
date: 2026-11-15
draft: true
show_toc: true
---
```

本地预览读取 Markdown 文件的实际修改时间，兼容 Obsidian 等外部编辑器，即使没有 `lastmod` 或该字段未变也会更新时间。封面、文档信息和目录索引的更新时间均显示到秒。正式构建优先保留显式 `lastmod`，例如 `lastmod: 2026-11-15T16:45:00+08:00`，缺少时回退到文件修改时间，以保留已记录的发布时间。创建日期仅取显式 `date`，缺少时显示横线。所有项目时间均使用北京时间（`Asia/Shanghai`、UTC+08:00），不随电脑时区变化；网页新建和保存使用含 `+08:00` 的时间戳。有时区的日期按同一时刻转换显示，仅含日期的字段保留原日期。文档在组内按整数 `weight`、标题排序，文件夹保持原来的独立分组位置；`weight: -1` 可排在同级记录前面。

所有文档默认 `draft: true`，包括省略此属性的项目概览、分组和文章。网页、Hugo 与 Obsidian 新建文档均遵循此默认值。保存缺少 `draft` 的文档时会补上 `draft: true`。只有显式设置 `draft: false` 才会发布。工作区预览包含草稿；正式构建的页面、导航与搜索排除草稿。`Templates/` 下的写作模板不参与发布。

## 左侧边栏文档顺序

相关工作、研究、文档和会议记录中的每篇文档都有整数 `weight`。数字越小越靠上，`0` 也按普通数字处理。
每个文件夹独立计算；新文档取同级现有最大权重加一，首篇文档使用 `1`，因此新文档排在已有文档后面。
复制或移入分组的文档也排到目标分组末尾。文件夹的 `_index.md` 不参与赋值，文件夹仍维持原来的独立分组位置。

可在 Obsidian 属性中或网页编辑器的 **文档属性** YAML 中修改 `weight`。相同权重按标题排序。
置顶会将权重改为小于当前最小值；取消置顶则排到末尾，位置始终由权重决定。

启动、构建及文件变更后的自动重建都会补齐缺失权重，兼容外部编辑器新增的文档；已有合法权重会保留。
运行 `node scripts/document-weights.mjs --check` 仅检查，省略 `--check` 则补齐缺失项。
`python3 scripts/verify-document-weights.py` 验证实际边栏和索引顺序；
`npm run test:workspace` 检查新建、手动修改、复制移动、置顶、外部导入和 Obsidian 辅助脚本。

Templater 的 **User scripts folder** 设置为 `Templates/Scripts`，使用 `Templates/Scripts/document_weight.js` 为新笔记赋值。
更新到已打开的仓库后，重新加载 Templater 或重新打开 Obsidian 仓库；已运行的 `pnpm dev` 也需重启一次。

## Obsidian 新建文档的默认模板

将 `site/content/` 作为仓库打开。审阅并信任随附插件后，在当前仓库的设置中启用社区插件和 **Templater**。[受限模式会禁用社区插件](https://obsidian.md/help/plugin-security)，因此只复制 `.obsidian/` 配置不会自动启用模板；每台机器上的新仓库都需要用户做出这项信任选择。

已配置新建空白 Markdown 笔记时按文件夹自动插入模板：`related-work/` 使用 `Templates/Related Work.md`，研究历程、系统实现和会议记录使用各自模板；子文件夹继承最近的上级规则，`/` 使用 `Templates/New Note.md` 兜底。保持 Templater 的 **Trigger Templater on new file creation** 和 **Enable folder templates** 开启。相关工作模板提供 YAML 默认值，从初始文件名读取标题，并使用北京时间的创建当天日期。五个模板均显式按 UTC+8 计算日期，不受电脑时区影响。

自动插入针对新建空笔记，不改写已有文档或创建时已带正文的文件。在 Obsidian 外修改插件配置后，需要重新加载仓库。运行 `node --test scripts/test-obsidian-templates.mjs` 可检查文件夹绑定和元数据默认值；该命令不检查 Obsidian 运行时的受限模式状态。

## 项目名称、作者与日期

在 `site/hugo.yaml` 中设置 `title` 和 `params.author.default`。例如，页眉可显示“科研项目 作者：Nan Lin”。同一作者配置也用于没有 `author` 的文档；文档自身的 `author` 可覆盖它。导入论文的作者列表保留既有显示方式。

文档元数据行分别显示作者、创建日期和最后修改时间的图标。`date` 记录创建时间，`lastmod` 记录最后编辑时间；网页保存只更新 `lastmod`。本地修改时间规则位于 `site/config/workspace/hugo.yaml`，构建不会改写文档元数据；外部编辑后刷新页面即可查看新时间。页眉搜索图标与 **⌘K / Ctrl+K** 打开同一搜索窗口。

## 发布

相对于项目根目录，可选部署工作流位于 `dashboard/.github/workflows/deploy.yml`，嵌套位置不会被 GitHub Actions 执行。启用 GitHub Pages 前，移至根目录 `.github/workflows/` 并适配 `dashboard/` 路径。Mirage 仓库为 [L1NxFR/Mirage](https://github.com/L1NxFR/Mirage)；本地编辑不会自动推送或发布。

本项目使用 [Hugo Paged](https://github.com/yihui/hugo-paged) 主题。上游组件名称、技术标识、第三方许可和版权声明保留原文。

## Obsidian 进度时间线

将 `site/content` 作为 Obsidian 仓库打开，使用本地时间线插件。在命令面板或编辑器右键菜单中选择**插入时间线**，填写步骤、状态和可选的 Markdown 详情。预览随输入更新，保存后插入文档。悬停时间线并点击铅笔可再次编辑。

底层格式为任务列表，可在 Obsidian 实时预览、阅读视图和 Hugo 网站中使用：

````text
```timeline
# 项目进度
- [x] 完成文献阅读
- [x] 确定研究方向
- [/] 分析研究空白
  在此补充 Markdown 详情。
- [ ] 完成报告
```
````

`[x]` 表示已完成，`[/]` 表示进行中，`[ ]` 表示未开始，`[!]` 表示失败。详情缩进两个空格。步骤标题后附加 `{open}`，可默认展开详情。在步骤前添加 `collapse: 2`，可折叠前两个步骤。时间线标题可省略；既有 YAML shortcode 继续兼容。

开发验证命令为 `node --test scripts/test-timeline.cjs` 和 `python3 scripts/verify-timeline.py`。修改 `plugin.js`、`source.js`、`editor.css` 或共享时间线 CSS 后，运行 `node scripts/sync-timeline-plugin.mjs`，同步生成插件、样式、字体与许可文件。随仓库提供的插件可直接使用，无需另行安装 npm 依赖。

## 文档封面与摘要

栏目文章默认使用灰色纸张风格封面，标题、副标题、作者、日期和标签取自 front matter。添加 `tldr` 可显示 Markdown 摘要；省略或留空则隐藏。不自动插入通信作者、项目链接或机构标志。

```yaml
---
title: 集合通信
subtitle: 概念与实现
content_lang: zh-CN
date: 2026-11-15
tldr: |
  **主要结论：** 通信语义、算法与调度分别回答不同层面的问题。

  - 语义定义预期结果。
  - 算法与调度决定通信如何执行。
---
```

页面标题自动生成。正文主节使用 `##`，子节使用 `###`。Markdown 的 `#`、`##`、`###` 保留相应 HTML 标题层级，字号分别为 28px、22px、18px。目录收录全部六级标题，保留原有锚点。

## Obsidian 图片与附件

将 `site/content` 作为 Obsidian 仓库打开。“文件与链接 → 新附件的默认位置”配置为“指定的附件文件夹”，文件夹为 `Attachments`。粘贴或拖入的文件存入 `site/content/Attachments/`。保持新链接格式为相对当前文件的路径，使用 Markdown 链接，并启用自动更新内部链接。

例如，位于 `related-work/communication/` 的笔记会插入：

```md
![](../../Attachments/screenshot.png)
[PDF](../../Attachments/paper.pdf)
```

Hugo 将这些文件发布到 `/attachments/`，并在构建时转换相对链接，支持空格和中文文件名。嵌入 PDF 会变为下载链接。在应用外修改 Obsidian 配置后，请重新加载仓库。移动现有附件时应在 Obsidian 内操作，以同步更新引用。

`Attachments` 中的所有非 Markdown 文件都会复制到网站，包括只被草稿引用的附件。可运行 `python3 scripts/verify-attachments.py` 检查发布路径与附件链接。

## Excalidraw 图示

在 Obsidian 中打开 `site/content` 仓库。Excalidraw 将图示源文件存入 `Excalidraw`，保存时在旁边自动导出 SVG。使用 Excalidraw 的“新建绘图并嵌入当前文档”命令，插入指向 SVG 的相对 Markdown 链接。打开相应 `.excalidraw.md` 编辑源图，保存后更新 SVG。插件也会在重命名或删除图示时同步处理导出文件。

Hugo 将 SVG 发布到 `/excalidraw/`，不将绘图源文件作为页面生成。目录内的全部 SVG 都会进入构建，即使只被草稿使用，因此不要在此存放私密图像。新检出副本应保留 Excalidraw 配置与相对链接设置；在应用外修改这些设置后需重新加载 Obsidian 仓库。

## Obsidian 高亮

正文、摘要和网页编辑器预览支持 Obsidian 的高亮语法：

```md
==默认高亮==
==🔴红色== ==🟠橙色== ==🟡黄色==
==🟢绿色== ==🔵蓝色== ==🟣紫色==
```

开头的颜色圆点用于选择颜色，不显示在渲染后的文本中，与
[Obsidian 官方高亮格式](https://obsidian.md/help/syntax)一致。
高亮中可以嵌套粗体和斜体；代码及转义后的分隔符保持原样。
也可以使用 Obsidian 和网站共用的 HTML 格式指定自定义颜色：

```html
<mark style="background: #ADCCFFA6;">自定义蓝色高亮</mark>
<mark style="background-color: #ffb8c6; color: #5b1528;">自定义背景与文字颜色</mark>
```

网页编辑器仅保留 `mark` 的背景色与文字颜色，其他内联样式继续从预览中过滤。
打印样式保留高亮颜色。运行 `python3 scripts/verify-highlights.py` 检查正文与摘要的构建结果；
`npm run test:workspace` 包含编辑器高亮检查。

## 导出完整 PDF

打开文档，按 **Cmd+P**（Windows/Linux 为 **Ctrl+P**），选择 **另存为 PDF**。
将页边距设为 **默认**，使用文档的打印页边距。
打印布局会让代码和表格单元格换行、展开内部滚动容器，并打开文档中的折叠内容，
包括时间线历史、步骤详情和论文摘要。关闭打印预览后，恢复原来的展开与折叠状态；
日常网页继续保留滚动和交互。

自定义的裁切组件可在容器上添加 `class="print-expand"`。
只能打印已经加载到页面的内容；虚拟列表、分页数据、嵌入页面和交互图表需要各自提供完整静态视图。
需要交互时，可在 PDF 之外附上部署后的网页链接。

打印样式位于 `site/static/css/print.css`，`site/static/js/print.js` 通过
[浏览器打印事件](https://developer.mozilla.org/en-US/docs/Web/CSS/Guides/Media_queries/Printing)
临时展开内容。运行 `node --test scripts/test-print.cjs` 检查展开与恢复行为。

## 语言与排版

Mirage 的界面默认使用简体中文（`locale: zh-CN`、`defaultContentLanguage: zh-cn`）。网页新建文档和分组、Hugo archetype、Obsidian 模板及保存时补全的语言均为 `content_lang: zh-CN`，显式语言设置会保留。

需要英文长文排版时，在单篇文档中设置 `content_lang: en`。语言属性只控制页面语言与排版，不会自动翻译正文或切换整个界面的语言。Markdown 使用 UTF-8，Hugo 已设置 `hasCJKLanguage: true`。

`site/static/css/fonts.css` 保留主题衬线字体与中文回退；`site/layouts/_partials/html_open.html` 设置页面语言。目录名、模板文件名和 YAML 字段名保留原有技术标识，以兼容既有路径与插件配置。第三方 Obsidian 插件和许可文件随源项目保留，其界面语言由插件及 Obsidian 自身控制。

## 检查命令

以下命令在 `dashboard/` 中执行：

```sh
npm run build
npm run test:workspace
node --test scripts/test-search.cjs scripts/test-toc.cjs scripts/test-sidenotes.cjs scripts/test-timeline.cjs
python3 scripts/verify-navigation-search.py
python3 scripts/verify-reading-layout.py
python3 scripts/verify-attachments.py
python3 scripts/verify-timeline.py
```

这些命令检查 Dashboard，不验证 `src/` 中的模拟器实现或参考仓库。

英文文档的普通正文保留衬线字体，正文与摘要中的 `strong`、`b`（包括粗斜体）使用无衬线字体，`en-US` 同样生效。行内代码保留等宽字体。

运行 `python3 scripts/verify-document-updates.py` 检查外部编辑后的更新时间、秒级显示、创建日期分离及显式发布时间的稳定性。
