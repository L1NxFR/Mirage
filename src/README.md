# 源码仓库

上游参考仓库通过 Git 子模块固定到具体提交。

| 目录 | 仓库 |
| --- | --- |
| `aisim/` | [NVIDIA AI Simulator](https://github.com/ai-dynamo/aisim) |
| `dynamo/` | [NVIDIA Dynamo](https://github.com/ai-dynamo/dynamo) |

克隆 Mirage 并获取参考仓库：

```sh
git clone --recurse-submodules https://github.com/L1NxFR/Mirage.git
```

对于已有的本地副本：

```sh
git submodule update --init --recursive
```

## 项目内 pstack skills

skills 安装在项目根目录：实体位于 `../.claude/skills/`，`../.agents/skills` 是指向它的相对符号链接（`../.claude/skills`），两者是同一份文件。从项目根目录启动 Claude Code 或 Codex 即可发现。

在 Claude Code 中用 `/poteto-mode` 调用；在 Codex 中输入：

```text
$poteto-mode 先阅读项目记录与 src，明确这个任务的验收标准，再实施和验证。
```

若菜单没有发现 skill，可直接要求读取 `.claude/skills/poteto-mode/SKILL.md`（Codex 另读其 Codex 映射）。处理 src 时遵循本目录 AGENTS.md。

- [完整中文指南](../dashboard/site/content/other/project-guide/agent-pstack-guide.md)：初始化、关键步骤、常用技能、更新与验证。
- [上游版本及校验清单](../.agents/pstack/upstream.json)：固定提交，不自动更新。
- [许可与来源](../.agents/pstack/NOTICE-skills.md)：保留上游许可。

## 依赖与验证

读取技能不需要安装应用依赖。执行某项技能时按其脚本声明准备 Node.js、Bun、Git、GitHub CLI 或应用自己的依赖；并非所有任务都需要这些工具。PR 工具需要已有登录及相应授权。技能安装没有安装这些运行依赖。

参考组件的运行和测试命令见各自 README。Dashboard 的构建和工作区测试仅验证文档站点。

从项目根目录核对安装文件完整性：

```sh
python3 - <<'PYTHON'
import hashlib, json
from pathlib import Path
manifest = json.loads(Path('.agents/pstack/upstream.json').read_text())
for name, expected in manifest['sha256'].items():
    path = Path('.claude/skills') / name
    assert path.is_file(), f'缺少文件：{name}'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, f'文件已改变：{name}'
print(f"通过：{manifest['skill_count']} 个上游 skills 的文件校验")
PYTHON
```
