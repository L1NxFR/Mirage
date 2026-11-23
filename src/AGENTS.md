# src 代理工作规范

继承项目根目录的 AGENTS.md。本目录默认采用 pstack 的项目内 skills 工作流。

## 默认入口

- 开始 src 实现任务时，先阅读 `.claude/skills/poteto-mode/SKILL.md`，Codex 另读 `.agents/skills/poteto-mode/references/codex-tools.md`，再按任务选择 playbook；这些路径相对于项目根目录。
- 单文件机械修改可直接执行；跨文件修改、接口或架构选择、原因未知的缺陷、性能问题默认进入 poteto-mode。用户显式指定的工作流优先。
- 会话从项目根目录启动，skills 由根目录安装提供。未出现在技能菜单时，直接读取上述文件及被选中 skill 的 SKILL.md；不要改用同名全局版本。
- skills 实体位于根目录 `.claude/skills/`（Claude Code 原生发现位置），根目录 `.agents/skills` 是指向它的相对符号链接，供 Codex 发现；两条路径指向同一份文件，不要复制或替换成独立目录。
- skills 保持同级安装，保留 references、playbooks、scripts。上游来源和文件校验值位于根目录 `.agents/pstack/upstream.json`，不要直接改写上游文件。

## Codex 适配与边界

- 使用当前会话实际提供的工具和模型，遵守宿主的并发限制；Claude 的工具名称和模型名称按 codex-tools.md 映射，不能当作 Codex API 原样调用。
- 本安装没有 SessionStart hook。默认路由由本文件提供，`setup-pstack` 的 hook 开关不会禁用本文件的规则。
- `setup-pstack` 在 Codex 默认写入用户级配置。仅需要本项目默认工作流时无需运行它；需要模型配置时先明确作用域，不自动改写用户级配置。
- 依照选定 skill 使用必要的子代理；必须独立审查而工具不可用时，报告审查受阻，不将自审冒充独立审查。
- 上游流程中的提交、推送、PR、合并、部署及外部消息操作仍须在用户授权范围内。安装不代表授权自动发布或发送消息。
- 项目尚无可运行实现时，不虚构运行命令、验证技能或性能结论。有真实组件后再生成根目录 `.claude/skills/verify/` 并实际执行验证流程。
- 实验记录遵循根目录规则；Dashboard 记录按实际作者署名，遵循根目录文档归属规则。

使用指南见 `../dashboard/site/content/other/project-guide/agent-pstack-guide.md`。
