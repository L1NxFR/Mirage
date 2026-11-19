# Mirage

大语言模型推理服务模拟器。

实现尚未开始。

项目界面、使用说明和新建文档默认使用简体中文；既有研究文档保留原文，单篇英文文档继续使用 `content_lang: en`。项目日期与时间统一使用北京时间（`Asia/Shanghai`、UTC+08:00）。

## 项目结构

- `src/`：模拟器代码、实验与评估，参考仓库见 [源码说明](src/README.md)。
- `dashboard/site/content/`：项目记录与文档。
- `dashboard/`：本地 Dashboard 应用，见 [使用说明](dashboard/README.md)。

## 运行 Dashboard

需要 Node.js 22+ 和 Hugo 0.146.0+。

```sh
cd dashboard
npm ci --ignore-scripts
npm run dev
```

打开启动日志打印的实际地址。默认从端口 `23130` 开始，按顺序跳过已占用端口。编辑直接保存到本地 Markdown 文件。

```sh
npm run build
npm run test:workspace
```

以上命令检查 Dashboard。模拟器的运行与测试命令随实现补充。
