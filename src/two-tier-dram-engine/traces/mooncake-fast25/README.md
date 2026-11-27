# Mooncake FAST'25 请求 trace

`trace.py` 使用的真实请求 trace。文件来自 Mooncake 官方仓库 [kvcache-ai/Mooncake](https://github.com/kvcache-ai/Mooncake) 的 `FAST25-release/traces/`，提交 `3cca71daccf2a7afb8fe3f0295358f70e3a69fdb`，未作修改。数据文件不入库（见 `../../.gitignore`），按下面的命令取得。

| 文件 | 大小 | 请求数 | SHA-256 |
| --- | --- | --- | --- |
| `conversation_trace.jsonl` | 3,029,533 B | 12,031 | `b8cbb061a85206d729d91cdc2981f43c9e0d99209dce588d3af5f7934408b9df` |
| `toolagent_trace.jsonl` | 4,415,857 B | 23,608 | `48a2db1a13d3bc05e6330140c64f604ba366df20d3c9e128b5c35a01c1fa5f71` |

```sh
cd src/two-tier-dram-engine/traces/mooncake-fast25
base=https://raw.githubusercontent.com/kvcache-ai/Mooncake/3cca71daccf2a7afb8fe3f0295358f70e3a69fdb/FAST25-release/traces
curl -fsSLO $base/conversation_trace.jsonl
curl -fsSLO $base/toolagent_trace.jsonl
sha256sum *.jsonl
```

`trace.py` 每次运行前校验 SHA-256，不一致就退出。

## 内容

每行一个请求：`timestamp`（毫秒）、`input_length`、`output_length`（token）、`hash_ids`（前缀内容块，每块 512 token；相同的块表示可复用的前缀）。

| | conversation | toolagent |
| --- | --- | --- |
| 时长 | 3,537 s | 3,537 s |
| 平均到达率 | 3.4 请求/s | 6.7 请求/s |
| 输入长度 p50／p90／p99／最大 | 6,909／27,367／85,399／126,195 | 6,346／16,804／61,525／126,195 |
| 输出长度 p50／p90／p99／最大 | 350／597／1,115／2,000 | 30／507／897／2,000 |
| 重复出现的前缀块占比 | 36.6% | 55.3% |

发布的时间戳按 3 秒取整，同一个 3 秒内的请求同时到达。trace 不含 token 内容，也不含专家路由或 top-k 选择。
