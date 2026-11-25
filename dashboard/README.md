# 科研项目 Dashboard

基于 Hugo 的中文科研记录工具，提供分层目录、论文卡片、进度时间线、阅读工具和本地 Markdown 编辑。

## 页面与目录

| 页面 | URL | 内容位置 |
| --- | --- | --- |
| 项目概览 | `/` | `site/content/_index.md` |
| 相关工作 | `/related-work/` | `site/content/related-work/` |
| 研究 | `/research-journey/` | `site/content/research-journey/` |
| 实验 | `/system-implementation/` | `site/content/system-implementation/` |
| 会议记录 | `/meetings/` | `site/content/meetings/` |
| 其他 | `/other/` | `site/content/other/` |

五个记录栏目使用可展开的文件夹层级、点状引导线和右侧最后更新日期。文档保留栏目导航、目录、Markdown 编辑与下载功能。搜索覆盖已发布记录和项目概览；关于、标签、分类和简历页面不生成。

项目概览和栏目文档共用封面、正文排版、标题编号、目录与编辑下载工具。项目内容保留为待填写项；已有的代理记录只说明模板初始化和中文化，不代表实际研究进展。写作模板位于 `site/content/Templates/`。修改 `site/hugo.yaml` 可配置项目名称和仓库链接。

“其他 → 项目使用”文件夹集中收录 [项目使用方法](site/content/other/project-guide/agent-project-guide.md) 与 [文档写作语法](site/content/other/project-guide/agent-writing-syntax.md)，以及 [pstack 初始化与使用指南](site/content/other/project-guide/agent-pstack-guide.md)，均保留为本地草稿。

## 本地运行

需要 Node.js 22+ 和 Hugo。在当前 `dashboard/` 目录执行：

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

外部保存内容、布局、样式或配置后，本地站点会重新构建，浏览器在构建成功后约一秒内自动重新加载，无需手动刷新。网页编辑器、新建窗口或其他对话框打开时暂缓刷新，关闭后更新，避免丢失未保存输入。构建失败时保留上一次成功页面；修复并保存后自动恢复更新。此功能仅在本地开发服务器启用，正式构建不会注入自动刷新脚本。静态 GitHub Pages 站点只读；本地写入 API 及其会话令牌不进入构建产物。

## 命令行新建记录

在 `dashboard/` 下运行：

```sh
pnpm run add "post_name" --target-root /absolute/path/to/project
```

终端会依次列出 `related-work`（相关工作）、`meetings`（会议记录）、`research-journey`（研究）、`system-implementation`（实验）、`other`（其他）。输入 `1`–`5` 或完整目录名选择类别，输入 `q` 或结束输入取消。终端提示使用英文。

标题含空格时加引号；可带 `.md` 后缀。标题保留原文，文件名沿用网页新建规则（英文转小写、空格转连字符）。同名文件不会覆盖。生成的草稿带标题、简介、摘要、作者、日期、标签、目录开关和排序权重；作者留空时继承站点配置。无需启动开发服务器。

`pnpm add` 是安装依赖的内置命令，创建文章必须使用 `pnpm run add`。脚本复用现有工作区模块和 `yaml` 依赖，不新增依赖；测试命令为 `node --test scripts/test-add-post.mjs`，也包含在 `npm run test:workspace` 中。

## 交付目录检查

交付目标是用户指定的项目根目录。它可以是普通仓库或 linked worktree。检查不会推断目标，也不会同步不同副本。需要 Node.js 22+ 和 Git，无新增 npm 依赖。

在准备修改的副本的 `dashboard/` 下执行，将占位路径替换为已确认的目标：

```sh
node scripts/check-delivery.mjs --target-root /absolute/path/to/project
```

检查将实际操作目录的 Git 根目录与目标目录比较，解析符号链接后再判断。目标缺失、目录不一致、内容目录链接到目标之外或 Git 无法识别仓库时返回非零退出码。目录名不参与识别，复制、改名或移动项目后只需使用新的目标路径。

交付前，追加本次文件的项目相对路径。`--file` 可以重复使用：

```sh
node scripts/check-delivery.mjs --target-root /absolute/path/to/project \
  --file dashboard/site/content/research-journey/example.md
```

需要验证网页时，先启动目标副本的 Dashboard，再使用启动日志中的实际地址和文章路径：

```sh
node scripts/check-delivery.mjs --target-root /absolute/path/to/project \
  --file dashboard/site/content/research-journey/example.md \
  --url http://localhost:23130 \
  --page /research-journey/example/
```

`--url` 检查本地服务报告的 `projectRoot`、`contentRoot`；`--page` 可重复使用，并要求指定 `--url`。旧服务需要重启以提供身份字段。服务不可达、身份不匹配或页面检查失败均返回非零退出码。页面检查验证 HTML 响应，不代替内容正确性或视觉验收；只检查文件不能证明网页可见。草稿需要本地 `npm run dev` 预览，正式构建不包含草稿。

新建记录的 CLI 在提示类别前执行同一目录检查，缺少目标或副本不匹配时不会创建文件。可以用环境变量 `DELIVERY_ROOT` 提供目标，命令行 `--target-root` 优先。不要把当前 `pwd` 自动设为目标，否则无法发现选错 worktree。

```sh
node --test scripts/test-delivery.mjs
npm run test:workspace
```

回归测试在临时 Git 仓库中创建 linked worktree，检查错误副本、目标缺失、文件缺失、符号链接和目录改名，以及服务身份与页面响应。检查只约束调用它的流程，不能拦截编辑器、Obsidian 或代理直接写文件；代理执行要求见根目录 `AGENTS.md`。

## 添加记录

在对应栏目目录中创建 Markdown 文件。子目录会显示为分组。点击分组标题直接打开分组文档，点击标题旁的箭头展开或收起子文档；不再另设“打开分组”入口，栏目与归档页不显示记录总数。可在 `site/data/journal_navigation.yaml` 中配置文件夹显示名称。

```yaml
---
title: 首次实验
content_lang: zh-CN
date: 2026-11-15
draft: true
show_toc: true
---
```

本地预览读取 Markdown 文件的实际修改时间，兼容 Obsidian 等外部编辑器，即使没有 `lastmod` 或该字段未变也会更新时间。封面、文档信息和目录索引的更新时间均显示到分钟，不显示秒数；底层时间记录保留秒级精度。正式构建优先保留显式 `lastmod`，例如 `lastmod: 2026-11-15T16:45:00+01:00`，缺少时回退到文件修改时间，以保留已记录的发布时间。创建日期仅取显式 `date`，缺少时显示横线。文档在组内按整数 `weight`、标题排序，文件夹保持原来的独立分组位置；`weight: -1` 可排在同级记录前面。

所有文档默认 `draft: true`，包括省略此属性的项目概览、分组和文章。网页、Hugo 与 Obsidian 新建文档均遵循此默认值。保存缺少 `draft` 的文档时会补上 `draft: true`。只有显式设置 `draft: false` 才会发布。工作区预览包含草稿；正式构建的页面、导航与搜索排除草稿。`Templates/` 下的写作模板不参与发布。

## 左侧边栏文档顺序

相关工作、研究、文档和会议记录中的每篇文档都有整数 `weight`。数字越小越靠上，`0` 也按普通数字处理。
每个文件夹独立计算；新文档取同级现有最大权重加一，首篇文档使用 `1`，因此新文档排在已有文档后面。
复制或移入分组的文档也排到目标分组末尾。文件夹的 `_index.md` 不参与赋值，文件夹仍维持原来的独立分组位置。

可在 Obsidian 属性中或网页编辑器的 **Properties** YAML 中修改 `weight`。相同权重按标题排序。
置顶会将权重改为小于当前最小值；取消置顶则排到末尾，位置始终由权重决定。

启动、构建及文件变更后的自动重建都会补齐缺失权重，兼容外部编辑器新增的文档；已有合法权重会保留。
使用 VS Code 等编辑器在五个记录栏目中新建空白 `.md` 文件时，运行中的 `pnpm dev` 会自动初始化 YAML；启动和构建时也会检查。标题取文件名，补上 `description`（简介）、`subtitle`（副标题）、`tldr`（页面摘要，支持 Markdown）、`date`、`lastmod`、`draft`、`content_lang`、`tags`、`show_toc` 和 `weight`。`author` 留空时继承站点默认作者。只有 `weight` 且没有正文的空白文件也会初始化；已有正文或其他 YAML 属性的文档只补缺失权重。未启动开发服务器时，VS Code 本身不会插入模板。

运行 `node scripts/document-weights.mjs --check` 仅检查，省略 `--check` 则补齐缺失项。
`python3 scripts/verify-document-weights.py` 验证实际边栏和索引顺序；
`npm run test:workspace` 检查新建、手动修改、复制移动、置顶、外部导入和 Obsidian 辅助脚本。

Templater 的 **User scripts folder** 设置为 `Templates/Scripts`，使用 `Templates/Scripts/document_weight.js` 为新笔记赋值。
更新到已打开的仓库后，重新加载 Templater 或重新打开 Obsidian 仓库；已运行的 `pnpm dev` 也需重启一次。

## Obsidian 新建文档的默认模板

将 `site/content/` 作为仓库打开。审阅并信任随附插件后，在当前仓库的设置中启用社区插件和 **Templater**。[受限模式会禁用社区插件](https://obsidian.md/help/plugin-security)，因此只复制 `.obsidian/` 配置不会自动启用模板；每台机器上的新仓库都需要用户做出这项信任选择。

已配置新建空白 Markdown 笔记时按文件夹自动插入模板：`related-work/` 使用 `Templates/Related Work.md`，研究历程、系统实现和会议记录使用各自模板；子文件夹继承最近的上级规则，`/` 使用 `Templates/New Note.md` 兜底。保持 Templater 的 **Trigger Templater on new file creation** 和 **Enable folder templates** 开启。相关工作模板提供 YAML 默认值，从初始文件名读取标题，并使用创建当天的日期。

自动插入针对新建空笔记，不改写已有文档或创建时已带正文的文件。在 Obsidian 外修改插件配置后，需要重新加载仓库。运行 `node --test scripts/test-obsidian-templates.mjs` 可检查文件夹绑定和元数据默认值；该命令不检查 Obsidian 运行时的受限模式状态。

## 项目名称、作者与日期

在 `site/hugo.yaml` 中设置 `title` 和 `params.author.default`。例如，页眉可显示“科研项目 林楠”。同一作者配置也用于没有 `author` 的文档；文档自身的 `author` 可覆盖它。用户与代理的文档署名统一显示圆形头像和名字；在 `params.author_profiles` 中按作者名字的小写形式配置 `name`、`avatar`，单篇可用 `author_avatar` 覆盖图片路径。Codex、Claude、Grok 使用官方图标，林楠使用 GitHub 用户 Languisher 的头像，均保存为本地资源；未配置作者使用通用人物图标，不使用字母头像。代理文章必须显式填写实际作者，不再要求 `[Agent]` 标题前缀；修改文章保留原作者，并追加修改代理到 `author`。导入论文的作者列表保留既有显示方式。

文档元数据行分别显示作者、创建日期和最后修改时间的图标。`date` 记录创建时间，`lastmod` 记录最后编辑时间；网页保存只更新 `lastmod`。本地修改时间规则位于 `site/config/workspace/hugo.yaml`，构建不会改写文档元数据；外部编辑后刷新页面即可查看新时间。页眉搜索图标与 **⌘K / Ctrl+K** 打开同一搜索窗口。

## 发布

相对于项目根目录，可选部署工作流位于 `dashboard/.github/workflows/deploy.yml`，嵌套位置不会被 GitHub Actions 执行。启用 GitHub Pages 前，移至根目录 `.github/workflows/` 并适配 `dashboard/` 路径。中文副本当前没有配置远程仓库；本地编辑不会推送或发布。

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

图片写法 `![图注文字](图片链接)` 会自动在图片下方显示居中的图注，并保留相同的 `alt` 替代文本；`![](图片链接)` 不显示图注。图注按纯文本显示，正文和网页编辑器预览均支持；可选的 `"title"` 仍仅作为悬停提示。PDF 嵌入继续显示下载链接。

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

此副本的界面默认使用简体中文（`locale: zh-CN`、`defaultContentLanguage: zh-cn`）。网页新建文档和分组、Hugo archetype、Obsidian 模板及保存时补全的语言均为 `content_lang: zh-CN`，显式语言设置会保留。

英文文档可在单篇文档中设置 `content_lang: en`，字体仍统一为无衬线。语言属性只控制页面语言与排版，不会自动翻译正文或切换整个界面的语言。Markdown 使用 UTF-8，Hugo 已设置 `hasCJKLanguage: true`。

`site/static/css/fonts.css` 统一使用无衬线字体（英文 Optimistic Text、中文 Noto Sans SC）；`site/layouts/_partials/html_open.html` 设置页面语言。目录名、模板文件名和 YAML 字段名保留原有技术标识，以兼容既有路径与插件配置。第三方 Obsidian 插件和许可文件随源项目保留，其界面语言由插件及 Obsidian 自身控制。

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

除 `verify-timeline.py` 和 `verify-paper-cards.py` 外，`scripts/verify-*.py` 依赖 Beautiful Soup（`beautifulsoup4`）。系统 Python 未安装它时，可用 uv 临时提供，例如：

```sh
uv run --no-project --with beautifulsoup4 python scripts/verify-navigation-search.py
```

这些命令检查 Dashboard，不验证 `src/` 中未来添加的项目实现。中文化验收与实际运行结果见 [中文版记录](site/content/system-implementation/agent-chinese-template.md)。

项目概览、相关工作、研究、实验与会议记录的页眉导航、栏目标题、列表、正文、摘要和元信息统一使用无衬线字体，英文文档同样适用。正文与摘要的加粗保留橙色强调；代码保留等宽字体，数学公式保留专用字体。

运行 `python3 scripts/verify-document-updates.py` 检查外部编辑后的更新时间、分钟级显示与秒级时间记录、创建日期分离及显式发布时间的稳定性。


## 中文加粗与强调卡片

普通正文用 `**中文重点**` 显示橙色粗体，与卡片内的强调文字保持相同字体和字重。需要浅米色背景、橙色左边线和橙色粗体的卡片时：

```md
> [!summary]
> 本研究提出一种新的服务框架。**核心思路是将计算资源分配与 KV 缓存管理解耦**，支持灵活切换。
>
> 第二段也可以使用 **中文加粗**、链接、列表和公式。
```

`[!summary]` 后可添加卡片标题，如 `> [!summary] 核心结论`。卡片正文的每一行都以 `>` 开头，空行使用单独的 `>`。正文与网页编辑器预览共用样式，打印时保留背景色。加粗使用已有中文 Bold 字体；卡片强调色使用较深的橙色，以提高小字号下的可读性。正文、摘要、引用和网页编辑器预览中的加粗均使用同一橙色粗体样式。

也支持 `[!note]` 等字母类型标记，当前共用这一卡片外观；`+`、`-` 标记会被识别，但卡片始终展开，不实现折叠。


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

分组标题（包括“项目使用”）与文档行均在右侧显示最后更新时间。分组取其 `_index.md` 的更新时间。日期所属年份为当前年时省略年份，往年保留年份；当前年按 Asia/Shanghai 判断。机器可读的 `datetime` 和更新时间悬停提示仍保留完整年份。
