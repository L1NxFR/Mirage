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
