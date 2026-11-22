"""Scenario catalog: run `aisim predict --stack two_tier_dram` per scenario, check, and render one replay page.

    python3 src/two-tier-dram/scenarios.py [--out DIR] [--only SLUG ...] [--publish PATH]

Every scenario is a real AISim prediction: AISim loads the trace, schedules the
request, and prices each pass with its op-level perf model; the two_tier_dram
stack re-times the decode steps per layer. Scenarios differ only in fields of
the top-level `two_tier_dram` section. Observable results are compared with
each scenario's `expect`; a mismatch prints MISMATCH and exits 1.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
AISIM = HERE.parent / "aisim"
CLI = AISIM / "python/aisim/.venv/bin/aisim"
sys.path.insert(0, str(HERE))

from two_tier_dram.config import TwoTierConfig  # noqa: E402
from two_tier_dram.render import write_replay  # noqa: E402

BASE = TwoTierConfig()
CONTEXT_TOKENS, OUTPUT_TOKENS = 200_000, 4  # 1 prefill token + 3 decode steps

ENGINE = {
    "mode": "aggregated", "model": "sgl-project/DeepSeek-V4-Pro-FP8", "hardware": "b200_sxm", "backend": "vllm",
    "context_length": 262144,
    "ais_perf_model": {"estimation_mode": "op_level", "database_mode": "SOL"},
    "workers": {"aggregated": {
        "parallelism": {"replicas": 1, "tensor": 1, "attention_data": 1},
        # The model's 1579 GB of weights exceed one device, which is the premise of the
        # two-tier design; a fixed KV capacity keeps AISim's single-tier memory check out of the way.
        "kv_cache": {"capacity": {"type": "fixed", "blocks": 40000}},
    }},
}

SCENARIOS = [
    {"slug": "baseline", "title": "基线",
     "summary": "非专家权重常驻一级，路由专家走 LRU 缓存，top-k KV 走热缓存；链路 64 GB/s。",
     "finding": "冷启动的 step 用 385 ms：61 层 × 6 个专家 × 66 MB ≈ 24 GB，在 64 GB/s 下要 378 ms。之后专家约一半命中，每 token 203 / 184 ms。等专家共 751 ms，等 top-k KV 只有 1.3 ms。AISim 原生每 token 6.54 ms：在这组参数下，专家搬运决定了时延。",
     "expect": {"token_ms": [385.477123, 202.595547, 184.014651], "expert_hits": 372, "kv_hits": 46078},
     "overrides": {}},
    {"slug": "reconcile", "title": "对账：链路无限快",
     "summary": "链路带宽设为 1e6 GB/s、每次传输开销 0。",
     "finding": "每 token 6.56 / 6.55 / 6.55 ms，与 AISim 原生的 6.54 ms 相差 0.4% 以内。两级模型在搬运代价趋于零时退化为 AISim 的原生定价。",
     "expect": {"token_ms": [6.563285, 6.551581, 6.550391]},
     "overrides": {"link_gbps": 1e6, "link_overhead_ms": 0.0}},
    {"slug": "sticky-experts", "title": "专家路由更稳定",
     "summary": "相邻 decode step 路由到同一专家的概率从 0.5 提到 0.9。",
     "finding": "专家命中从 372 升到 657（共 1098 次路由），冷启动之后每 token 约 45 ms。时延对路由的跨步稳定性很敏感，而这个参数目前是合成的，没有真实路由统计。",
     "expect": {"token_ms": [385.477123, 45.381019, 46.403923], "expert_hits": 657},
     "overrides": {"expert_overlap": 0.9}},
    {"slug": "small-tier1", "title": "一级缩到 48 GB",
     "summary": "一级从 96 GB 缩到 48 GB，非专家权重仍常驻，留给专家缓存的空间变小。",
     "finding": "专家缓存只剩 179 个位置，而一个 step 要用 61 × 6 = 366 个专家。LRU 在专家被再次用到之前就把它淘汰了，命中 0 次，每个 token 都是 385 ms。专家缓存至少要放得下一个 step 的工作集（约 24 GB）才有用。",
     "expect": {"token_ms": [385.477123, 385.293531, 385.292091], "expert_hits": 0, "expert_cache_slots": 179},
     "overrides": {"tier1_gb": 48.0}},
    {"slug": "small-tier1-prefetch", "title": "48 GB + 按上一步路由预取专家",
     "summary": "一级 48 GB；计算第 L 层时，预取第 L+1 层上一步用过、但已不在缓存里的专家。",
     "finding": "反而更慢：574 / 551 ms。预取了 732 个专家，但重合度只有 0.5，每层 6 个里只有约 3 个用得上；这一层却要等整个预取传输完成，再按需取 3 个新的，相当于每层搬 9 个专家而不是 6 个（385 × 1.5 ≈ 578）。预取不准时，它占用的是关键路径上的链路。",
     "expect": {"token_ms": [385.477123, 574.397691, 550.791752], "expert_prefetched": 732},
     "overrides": {"tier1_gb": 48.0, "expert_prefetch": "last_step"}},
    {"slug": "no-hot-kv", "title": "关闭热 top-k KV 缓存",
     "summary": "取入的 top-k KV 用完即丢，每个 CSA 层每步都重新取 1024 条。",
     "finding": "等 KV 的时间从 1.27 ms 变成 1.64 ms，每 token 只多 0.18 ms。一层的 top-k 只有 1024 × 512 B = 0.5 MB，KV 搬运不是瓶颈。",
     "expect": {"token_ms": [385.477123, 202.779139, 184.199683], "kv_hits": 0},
     "overrides": {"hot_kv_entries": 0}},
    {"slug": "link-overhead", "title": "每次传输开销变大",
     "summary": "每次传输的固定开销从 0.01 ms 提到 0.5 ms（约 5 层的计算时间）。",
     "finding": "等 KV 从 1.3 ms 涨到 45.4 ms（30 个 CSA 层 × 3 个 step × 0.5 ms），每 token 多约 45 ms。KV 传输量很小，代价几乎全是每次传输的固定开销，所以小而频繁的读取要看开销，不是带宽。",
     "expect": {"token_ms": [430.067123, 247.185547, 228.604651]},
     "overrides": {"link_overhead_ms": 0.5}},
    {"slug": "layer-prefetch", "title": "方案 A：非专家权重逐层换入",
     "summary": "一级只保留当前层的非专家权重，并预取下一层的（每层约 0.46 GB）。",
     "finding": "182 次预取全部迟到，等非专家权重共 1313 ms，每 token 多约 437 ms。一层的非专家权重 0.46 GB，在 64 GB/s 下要 7.2 ms，而一层的计算只有 0.1 ms，预取不可能在一层的计算窗口内完成。按 AISim 的数字，非专家权重（共约 32 GB）应当常驻一级。",
     "expect": {"token_ms": [823.270599, 640.045038, 621.464142], "base_late": 182},
     "overrides": {"base_weights": "layer_prefetch"}},
    {"slug": "tier1-too-small", "title": "一级放不下",
     "summary": "一级只有 36 GB，而 scratch、全局权重和常驻的非专家权重已经约 36 GB。",
     "finding": "scratch 与全局权重 7.7 GB、常驻的非专家权重 28.3 GB 之后，专家缓存没有空间，连一层的 6 个专家（0.40 GB）都放不下。模型在开始前报容量不足。",
     "overrides": {"tier1_gb": 36.0}, "expect": {"error": True}},
]

RELATIONS = [
    ("链路无限快时，两级时延回到 AISim 原生时延（1% 以内）",
     lambda m: all(abs(t - m["reconcile"]["native_token_ms"]) <= 0.01 * m["reconcile"]["native_token_ms"] for t in m["reconcile"]["token_ms"])),
    ("专家路由更稳定时命中更多、更快", lambda m: m["sticky-experts"]["expert_hits"] > m["baseline"]["expert_hits"]
     and m["sticky-experts"]["total_ms"] < m["baseline"]["total_ms"]),
    ("关闭热 KV 后 top-k 没有命中", lambda m: m["no-hot-kv"]["kv_hits"] == 0),
    ("传输开销变大后等 KV 的时间变长", lambda m: m["link-overhead"]["wait_kv_ms"] > m["baseline"]["wait_kv_ms"]),
    ("一级变小后专家缓存位更少", lambda m: m["small-tier1"]["expert_cache_slots"] < m["baseline"]["expert_cache_slots"]),
]


def run(scenario: dict, out: Path) -> dict:
    folder = out / scenario["slug"]
    folder.mkdir(parents=True, exist_ok=True)
    trace_file = folder / "requests.mooncake.jsonl"
    trace_file.write_text(json.dumps({"request_id": "R1", "timestamp": 0, "input_length": CONTEXT_TOKENS,
                                      "output_length": OUTPUT_TOKENS, "hash_ids": [1]}) + "\n")
    config = {
        "traffic": {"source": {"type": "trace", "format": "mooncake", "block_size": 262144, "paths": [str(trace_file)]},
                    "load": {"type": "trace_timestamps"}},
        "engine": ENGINE,
        "two_tier_dram": {**scenario["overrides"], "trace_dir": str(folder)},
    }
    (folder / "config.json").write_text(json.dumps(config, indent=1))  # JSON is valid YAML
    (folder / "trace.json").unlink(missing_ok=True)
    proc = subprocess.run([str(CLI), "predict", "--stack", "two_tier_dram", "--config", str(folder / "config.json"),
                           "--output-dir", str(folder / "aisim"), "--overwrite"], cwd=AISIM, capture_output=True, text=True)
    (folder / "run.log").write_text(proc.stdout + proc.stderr)
    if not (folder / "trace.json").exists():
        raise SystemExit(f"{scenario['slug']}: aisim produced no trace (exit {proc.returncode}); see {folder / 'run.log'}")
    return json.loads((folder / "trace.json").read_text())


def check(scenario: dict, request: dict) -> list[str]:
    errors = []
    if not request.get("native_itl_matches_profile", False):
        errors.append("AISim replay ITL does not match the per-operator profile")
    for key, want in scenario.get("expect", {}).items():
        got = bool(request["error"]) if key == "error" else request["metrics"][key]
        if got != want:
            errors.append(f"{key}: expected {want}, got {got}")
    if "error" not in scenario.get("expect", {}) and request["error"]:
        errors.append(f"unexpected error: {request['error']}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=HERE / "output")
    parser.add_argument("--only", nargs="*", help="scenario slugs to run")
    parser.add_argument("--publish", type=Path, help="also copy the page to this path")
    parser.add_argument("--show", action="store_true", help="print each scenario's key metrics as JSON")
    args = parser.parse_args()
    out = args.out.resolve()
    chosen = [s for s in SCENARIOS if not args.only or s["slug"] in args.only]
    items, metrics, failed = [], {}, False
    for scenario in chosen:
        trace = run(scenario, out)
        request = trace["requests"][0]
        errors = check(scenario, request)
        failed |= bool(errors)
        metrics[scenario["slug"]] = request["metrics"]
        print(f"{scenario['slug']}: " + ("OK" if not errors else "MISMATCH " + "; ".join(errors)))
        if args.show:
            m = request["metrics"]
            print("  " + json.dumps({"error": bool(request["error"]), **{k: m[k] for k in (
                "token_ms", "expert_hits", "kv_hits", "wait_experts_ms", "wait_kv_ms", "wait_base_ms", "base_late",
                "expert_cache_slots", "expert_prefetched", "expert_prefetch_used", "total_ms")}}))
        items.append({"title": scenario["title"], "summary": scenario["summary"], "finding": scenario.get("finding", ""),
                      "changes": [{"param": k, "base": getattr(BASE, k), "value": v} for k, v in scenario["overrides"].items()],
                      "trace": trace})
    if not args.only:
        for name, holds in RELATIONS:
            ok = holds(metrics)
            failed |= not ok
            print(f"relation: {name}: " + ("OK" if ok else "MISMATCH"))
    if failed:
        return 1
    page = out / "two-tier-dram-replay.html"
    write_replay(items, page)
    print(f"wrote {page}")
    if args.publish:
        args.publish.write_bytes(page.read_bytes())
        print(f"published {args.publish}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
