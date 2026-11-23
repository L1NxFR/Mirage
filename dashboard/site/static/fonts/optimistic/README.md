# Optimistic 网页字体

原项目于 2026-11-14 从 `https://conf.reactjs.org/fonts/` 下载，文件保持原始字节。文件名与来源见 React 的[官方下载脚本](https://github.com/reactjs/react.dev/blob/main/scripts/downloadFonts.mjs)，源 blob 为 `6a480c750d6ab578b28ecd56e6933f800318e309`。CSS 字重与样式映射遵循字体 OS/2 表及 [React 样式表](https://github.com/reactjs/react.dev/blob/main/src/styles/index.css)。

包含的拉丁字体：

- Display：200、300、500、600、700、800 正体；500、600、700 斜体。
- Text：400、500、700、800 正体与斜体。

此来源不含 Display 400 Regular。文章标题使用 Display 700；中文文档中的拉丁正文使用 Text 400，并提供实际粗体、斜体。英文长文按 HTML 语言使用既有 Latin Modern Roman。这些字体是互补的光学样式，字形轮廓并不完全相同。中文使用独立随附的 Noto Sans SC Regular/Bold；代码与公式保留专用字体。

英文文档正文和摘要中的加粗与粗斜体使用 Optimistic Text Bold/Bold Italic，普通正文仍使用 Latin Modern Roman。

Optimistic 是 Meta 字体。这些文件未附带开源字体许可；仓库代码许可及 Noto 的 OFL 不授予 Optimistic 使用权。下载来源只说明来源，不等于再分发许可。本目录不得标为 MIT 或 OFL。

旧文件 `paper/optimistic-bold-subset.ttf` 是包含 77 个字形、没有 Unicode cmap 的 PDF 子集，保留供既有非文章样式使用；当前文章阅读样式不再引用它。
