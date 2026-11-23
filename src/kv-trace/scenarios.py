"""Scenario catalog: generate AISim configs + mooncake traces, capture, and render.

Every scenario shares one tiny vLLM worker (block_size 4, 1 MB/block, fixed
timing) and differs only in the fields it overrides. Run with any Python 3:

    python3 src/kv-trace/scenarios.py [--out DIR] [--only SLUG ...]
"""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
AISIM = HERE.parent / "aisim"
VENV_PY = AISIM / "python/aisim/.venv/bin/python"
TINY_MODEL = AISIM / "tests/e2e/configs/unified_cli/fixtures/tiny-model"

BASE_KV = {
    "block_size": 4,
    "prefix_caching": True,
    "bytes_per_token": 250000,  # 4 tokens x 250 KB = 1 MB per block
    "capacity": {"type": "fixed", "blocks": 3},
    "host_offload": {
        "scope": "dp_rank_local",
        "num_host_blocks": 8,
        "d2h_bandwidth_gbps": 1,
        "h2d_bandwidth_gbps": 1,
        "latency_to_first_byte_ms": 0,
    },
}
BASE_SCHED = {"max_batched_tokens": 16, "max_sequences": 1}

# Request = (arrival ms, input tokens, block hash ids). Output is one token.
# R3 is R1's next turn: R1's 9 prompt tokens + its 1 output token + 2 new user
# tokens = 12. It shares R1's two full blocks [1, 2]; its third block holds R1's
# last prompt token plus new tokens, so it gets a new id (30). R2 is an unrelated
# request that pushes R1's prefix out of G1 in between.
PARENT_CHILD = [(0, 9, [1, 2, 3]), (100, 9, [11, 12, 13]), (200, 12, [1, 2, 30]), (300, 9, [21, 22, 23])]

SCENARIOS = [
    {
        "slug": "baseline", "title": "基线",
        "summary": "R2 挤掉 R1 在 G1 的前缀；R3 是 R1 的下一轮（R1 的 9 token + 1 输出 + 2 新 token = 12），从 G2 恢复共享的 2 个 block。",
        "finding": "R3 在 200 ms 到达，H2D 2 MB 用 2 ms，202 ms 才准入；TTFT 4 ms，其中 8 token 来自 G2，只有第 3 块（R1 的最后 1 个 token + 本轮新内容）需要计算。R3·b2 写满后也存入 G2，于是 G2 里接上了这段会话的前缀链 R1·b0 → R1·b1 → R3·b2。R1 自己的第 3 块只有 1 token，不落定也不存。",
        "requests": PARENT_CHILD, "kv": {}, "sched": {},
        "expect": {"ttft": [2, 2, 4, 2], "host_reused": [0, 0, 8, 0]},
    },
    {
        "slug": "g2-pressure", "title": "G2 压力 + 慢 H2D",
        "summary": "G2 只有 4 block、H2D 0.05 GB/s。",
        "finding": "恢复 2 MB 要 40 ms，R3 的 TTFT 变为 42 ms，等待全部发生在准入之前。240 ms 存 R3·b2 时 G2 已满，驱逐 R2·b1；300 ms 存 R4 时驱逐 R2·b0 和 R1·b1。R1·b1 被逐出后，R3·b2 留在 G2 却失去了父块：按前缀查找遇缺即停的规则，它已无法被命中（推断，本场景没有请求去查它）。",
        "requests": PARENT_CHILD,
        "kv": {"host_offload": {"num_host_blocks": 4, "h2d_bandwidth_gbps": 0.05}}, "sched": {},
        "expect": {"ttft": [2, 2, 42, 2], "host_reused": [0, 0, 8, 0]},
    },
    {
        "slug": "slow-d2h", "title": "极端：D2H 未完成时复用源 block（栅栏）",
        "summary": "D2H 0.016 GB/s：存 2 MB 要 125 ms，比请求间隔 100 ms 稍长。下一个请求要复用的 G1 block 往往还在被 D2H 读取。",
        "finding": "同一个栅栏机制出现了三次：R2 在 100 ms 准入，但复用的是 R1 的 D2H 源 block，prefill 等到 127 ms，TTFT 29 ms；R3 的 H2D 目标是 R2 的 D2H 源，H2D 从 254 ms 才开始传，TTFT 58 ms；R4 驱逐了正在存的 R3·b2，等到 320.5 ms，TTFT 22.5 ms。栅栏只推迟计算或 H2D 的开始，不挡准入。",
        "requests": PARENT_CHILD,
        "kv": {"host_offload": {"d2h_bandwidth_gbps": 0.016}}, "sched": {},
        "expect": {"ttft": [2, 29, 58, 22.5], "host_reused": [0, 0, 8, 0]},
    },
    {
        "slug": "g2-one-block", "title": "极端：G2 小于一次 store",
        "summary": "G2 只有 1 block，而每次 store 要 2 block。",
        "finding": "每次 store 都报 capacity_retry（structurally_unfittable），G2 从未写入，也不会退而求其次只存一部分。R3 无法恢复 R1 的前缀，12 个 token 全部重算，store 时连同 R1 的两块一起尝试 3 个 block，同样失败。fixed timing 下重算不比恢复慢，TTFT 仍是 2 ms。",
        "requests": PARENT_CHILD,
        "kv": {"host_offload": {"num_host_blocks": 1}}, "sched": {},
        "expect": {"ttft": [2, 2, 2, 2], "host_reused": [0, 0, 0, 0]},
    },
    {
        "slug": "aligned-full-hit", "title": "极端：整块对齐的 prompt 完全命中",
        "summary": "8 token 恰好 2 个整块，G1 只有 2 block；R3 原样重发 R1 的 prompt（不是下一轮）。",
        "finding": "vLLM 完全命中时必须重算最后一个 token，按整块回退：只记复用 4 token。但 H2D 搬回了 2 个 block（2 MB），第 2 块随后被整块重算，1 MB 的 H2D 白搬。真实 vLLM connector 是否也这样，待核实。",
        "requests": [(0, 8, [1, 2]), (100, 8, [11, 12]), (200, 8, [1, 2])],
        "kv": {"capacity": {"type": "fixed", "blocks": 2}}, "sched": {},
        "expect": {"ttft": [2, 2, 4], "host_reused": [0, 0, 4]},
    },
    {
        "slug": "h2d-blocks-peer", "title": "极端：H2D 预留占住 G1，与并发请求争抢",
        "summary": "max_sequences 2、H2D 0.05 GB/s。R3（R1 的下一轮）等 H2D 期间，无关请求 R4（4 token，1 block）在 210 ms 到达。",
        "finding": "R3 的 2 个预留 block 占住 G1 的 2/3 长达 40 ms，但不阻塞别人：R4 在 210 ms 直接准入，比先到的 R3 先完成。R3 在 240 ms 准入时反过来驱逐 R4 刚落定的 block。",
        "requests": PARENT_CHILD[:3] + [(210, 4, [31])],
        "kv": {"host_offload": {"h2d_bandwidth_gbps": 0.05}}, "sched": {"max_sequences": 2},
        "expect": {"ttft": [2, 2, 42, 2], "host_reused": [0, 0, 8, 0]},
    },
    {
        "slug": "prompt-exceeds-g1", "title": "极端：prompt 大于整个 G1",
        "summary": "G1 只有 2 block，9 token 的 prompt 需要 3 block。",
        "finding": "请求在到达时刻直接被拒绝（rejected），没有任何 KV 事件，也不会尝试借 G2 分批。AISim 以退出码 1 结束并提示 No requests completed；这是预期结果，不是工具故障。",
        "requests": [(0, 9, [1, 2, 3])],
        "kv": {"capacity": {"type": "fixed", "blocks": 2}}, "sched": {},
        "expect": {"ttft": [None], "host_reused": [0], "rejected": True},
    },
]


def merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def changes(s: dict) -> list[dict]:
    """AISim parameters this scenario overrides, as dotted kv_cache/scheduler paths with base and new values."""
    out = []
    def walk(prefix: str, base: dict, override: dict):
        for k, v in override.items():
            if isinstance(v, dict):
                walk(f"{prefix}{k}.", base.get(k, {}), v)
            else:
                out.append({"param": prefix + k, "base": base.get(k), "value": v})
    walk("kv_cache.", BASE_KV, s["kv"])
    walk("scheduler.", BASE_SCHED, s["sched"])
    return out


def write_inputs(s: dict, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    trace = folder / "trace.jsonl"
    trace.write_text("".join(
        json.dumps({"request_id": f"R{i}", "timestamp": t, "input_length": n, "output_length": 1, "hash_ids": h}) + "\n"
        for i, (t, n, h) in enumerate(s["requests"], start=1)))
    config = {
        "traffic": {"source": {"type": "trace", "format": "mooncake", "block_size": 4, "paths": [str(trace)]},
                    "load": {"type": "trace_timestamps"}},
        "engine": {
            "mode": "aggregated", "model": str(TINY_MODEL), "hardware": "h200_sxm", "backend": "vllm",
            "context_length": 2048,
            "workers": {"aggregated": {
                "parallelism": {"replicas": 1, "tensor": 1, "attention_data": 1},
                "scheduler": merge(BASE_SCHED, s["sched"]),
                "kv_cache": merge(BASE_KV, s["kv"]),
                "timing": {"type": "fixed", "prefill_ms": 2, "decode_ms": 1},
            }},
        },
    }
    path = folder / "config.json"  # JSON is valid YAML
    path.write_text(json.dumps(config, indent=1))
    return path


def capture(s: dict, out: Path) -> dict:
    folder = out / s["slug"]
    config = write_inputs(s, folder)
    proc = subprocess.run(
        [str(VENV_PY), str(HERE / "capture.py"), "--trace-out", str(folder / "trace.json"), "--",
         "predict", "--stack", "engine", "--config", str(config), "--capture-per-request",
         "--output-dir", str(folder / "aisim"), "--overwrite"],
        cwd=AISIM, capture_output=True, text=True)
    (folder / "run.log").write_text(proc.stdout + proc.stderr)
    status = {"slug": s["slug"], "exit": proc.returncode, "captured": (folder / "trace.json").exists()}
    if proc.returncode != 0:
        status["error"] = (proc.stderr.strip().splitlines() or ["(no stderr)"])[-1]
    return status


def check(s: dict, folder: Path) -> list[str]:
    """Compare the run against the scenario's expected observable behavior."""
    trace = json.loads((folder / "trace.json").read_text())["artifacts"]
    records = {r["uuid"]: r for r in map(json.loads, (folder / "aisim/requests.jsonl").read_text().splitlines())}
    ordered = [records[a["request_id"]] for a in sorted(trace["requests"], key=lambda a: a["observed_at_ms"])]
    got = {"ttft": [r.get("ttft_ms") for r in ordered],
           "host_reused": [r.get("first_admission_host_reused_input_tokens") or 0 for r in ordered]}
    rejected = any(o["rejected"] for o in trace["outputs"])
    errors = [f"{k}: expected {v}, got {got[k]}" for k, v in s["expect"].items() if k in got and got[k] != v]
    if rejected != s["expect"].get("rejected", False):
        errors.append(f"rejected: expected {s['expect'].get('rejected', False)}, got {rejected}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=HERE / "output")
    parser.add_argument("--only", nargs="*", help="scenario slugs to run")
    parser.add_argument("--no-render", action="store_true")
    parser.add_argument("--publish", type=Path, help="also copy the page here, e.g. dashboard/site/content/Attachments/kv-cache-replay.html")
    args = parser.parse_args()
    out = args.out.resolve()
    chosen = [s for s in SCENARIOS if not args.only or s["slug"] in args.only]
    statuses = [capture(s, out) for s in chosen]
    failed = False
    for s, st in zip(chosen, statuses):
        st["mismatch"] = check(s, out / s["slug"]) if st["captured"] else ["no replay captured"]
        failed |= bool(st["mismatch"])
        print(f"{s['slug']}: exit={st['exit']} " + ("OK" if not st["mismatch"] else "MISMATCH " + "; ".join(st["mismatch"])))
    if failed:
        return 1
    if args.no_render:
        return 0
    rendered = []
    for s, st in zip(chosen, statuses):
        rendered.append({**{k: s[k] for k in ("slug", "title", "summary", "finding")}, **st, "changes": changes(s),
                         "trace": str(out / s["slug"] / "trace.json"),
                         "requests_jsonl": str(out / s["slug"] / "aisim/requests.jsonl")})
    manifest = out / "scenarios.json"
    manifest.write_text(json.dumps(rendered, ensure_ascii=False, indent=1))
    page = out / "kv-cache-replay.html"
    status = subprocess.run([sys.executable, str(HERE / "render.py"), "--manifest", str(manifest), "--out", str(page)]).returncode
    if status == 0 and args.publish:
        args.publish.write_bytes(page.read_bytes())
        print(f"published {args.publish}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
