"""Closed-loop two-tier DRAM scenarios on AISim's engine (`kv_cache.two_tier_dram`), checked and rendered.

    python3 src/two-tier-dram-engine/scenarios.py [--out DIR] [--only SLUG ...] [--show] [--publish PATH]

Each scenario is a real `aisim predict --stack engine` run with the two-tier
model inside the vLLM scheduler: every pass is re-timed layer by layer and the
waits delay the next pass. Each distinct workload is also run once without
`two_tier_dram` for AISim's native timeline. Observable results are compared
with `expect`; a mismatch prints MISMATCH and exits 1, and no page is written.
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
CLI = AISIM / "python/aisim/.venv/bin/aisim"
sys.path.insert(0, str(HERE))

from render import write_page  # noqa: E402

BASE_TWO_TIER = {"tier1_gb": 96.0, "link_gbps": 64.0, "link_overhead_ms": 0.01, "expert_overlap": 0.5,
                 "topk_overlap": 0.75, "hot_kv_entries": 65536, "base_weights": "resident", "expert_prefetch": "none",
                 "link_policy": "demand_first", "seed": 0, "trace_passes": 4}

# Four 16K-token requests 50 ms apart, 8 output tokens each; up to 4 decode together.
STAGGERED = {"requests": [(0, 16384, 8), (50, 16384, 8), (100, 16384, 8), (150, 16384, 8)],
             "max_batched_tokens": 16384, "max_sequences": 4}
# The same four requests arriving together, with a budget that prefills them in one pass.
TOGETHER = {"requests": [(0, 16384, 8)] * 4, "max_batched_tokens": 65536, "max_sequences": 4}

SCENARIOS = [
    {"slug": "baseline", "title": "基线：4 个请求错峰到达",
     "summary": "4 个 16K token 的请求每 50 ms 到达一个，各输出 8 个 token；一级 96 GB，链路 64 GB/s。",
     "finding": "R1 的 TTFT 24.7 s：一个 16K token 的 prefill 在每层几乎路由到全部 384 个专家，61 层 × 384 × 66 MB ≈ 1547 GB，64 GB/s 下约 24.2 s。max_batched_tokens 只够一个 prompt，4 个 prefill 各占一个 pass，各搬一遍全部专家；这些 pass 里还夹着已在 decode 的请求，所以 R1 的 ITL 也有 11.5 s。全部完成 109 s，原生 2.4 s。专家命中只有 0.4%：每次 prefill 都把缓存冲掉。",
     "workload": STAGGERED, "overrides": {}},
    {"slug": "reconcile", "title": "对账：链路无限快",
     "summary": "同一负载，链路 1e9 GB/s、每次传输开销 0。",
     "finding": "4 个请求的 TTFT 与 AISim 原生完全一致（570 / 1681 / 2213 / 2192 ms），全部完成 2428.53 ms 对 2428.52 ms。两级模型在搬运代价趋零时不改变 AISim 的调度。",
     "workload": STAGGERED, "overrides": {"link_gbps": 1e9, "link_overhead_ms": 0.0}},
    {"slug": "fast-link", "title": "链路 512 GB/s",
     "summary": "同一负载，链路带宽提高 8 倍。",
     "finding": "全部完成从 109 s 降到 15.8 s，约为 1/7。剩下的部分里有约 2.4 s 是 AISim 本身的计算时间，不随链路变快。",
     "workload": STAGGERED, "overrides": {"link_gbps": 512.0}},
    {"slug": "batched-prefill", "title": "4 个请求同时到达、一个 pass 完成 prefill",
     "summary": "4 个请求同时到达，max_batched_tokens 65536，让 4 个 prefill 共用一次专家搬运。",
     "finding": "4 个 prompt 在一个 pass 里 prefill，专家只搬一遍：4 个请求的 TTFT 都是 26.3 s，全部完成 36.7 s，基线是 109 s。之后 4 个请求一起 decode，每步每层要用约 23 个专家，61 层合计超过专家缓存的约 900 个位置，命中 0，ITL 1.49 s。",
     "workload": TOGETHER, "overrides": {}},
    {"slug": "sticky-experts", "title": "专家路由更稳定",
     "summary": "相邻 step 路由到同一专家的概率 0.5 → 0.9。",
     "finding": "专家命中从 398 次升到 689 次，但全部完成时间几乎不变（108.8 s）：prefill 搬运全部专家占了绝大部分时间，decode 的命中改善被淹没。",
     "workload": STAGGERED, "overrides": {"expert_overlap": 0.9}},
    {"slug": "small-tier1", "title": "一级缩到 48 GB",
     "summary": "专家缓存从约 906 个位置缩到约 179 个。",
     "finding": "一层的 384 个专家放不进一级，MoE 分组执行。专家缓存只剩约 179 个位置，命中 0；专家挤占空间后热 top-k KV 也被淘汰，KV 命中从 113093 降到 56009。全部完成 109.5 s，只比基线慢 0.4%，因为瓶颈仍是 prefill 搬运全部专家。",
     "workload": STAGGERED, "overrides": {"tier1_gb": 48.0}},
]


def workload_key(workload: dict) -> str:
    return json.dumps(workload, sort_keys=True)


def config_for(workload: dict, trace_file: Path, two_tier: dict | None) -> dict:
    kv_cache = {"capacity": {"type": "fixed", "blocks": 40000}}
    if two_tier is not None:
        kv_cache["two_tier_dram"] = two_tier
    return {
        "traffic": {"source": {"type": "trace", "format": "mooncake", "block_size": 65536, "paths": [str(trace_file)]},
                    "load": {"type": "trace_timestamps"}},
        "engine": {
            "mode": "aggregated", "model": "sgl-project/DeepSeek-V4-Pro-FP8", "hardware": "b200_sxm", "backend": "vllm",
            "context_length": 131072,
            "ais_perf_model": {"estimation_mode": "op_level", "database_mode": "SOL"},
            "workers": {"aggregated": {
                "parallelism": {"replicas": 1, "tensor": 1, "attention_data": 1},
                "scheduler": {"max_batched_tokens": workload["max_batched_tokens"], "max_sequences": workload["max_sequences"]},
                # The model's 1579 GB of weights exceed one device, the premise of the design;
                # fixed G1 capacity (here: tier-2 KV) keeps AISim's single-tier memory check out of the way.
                "kv_cache": kv_cache,
            }},
        },
    }


def run_aisim(folder: Path, workload: dict, two_tier: dict | None) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    trace_file = folder / "requests.mooncake.jsonl"
    trace_file.write_text("".join(
        json.dumps({"request_id": f"R{i}", "timestamp": t, "input_length": n, "output_length": out, "hash_ids": [100 * i + 1]}) + "\n"
        for i, (t, n, out) in enumerate(workload["requests"], start=1)))
    config = config_for(workload, trace_file, two_tier)
    (folder / "config.json").write_text(json.dumps(config, indent=1))  # JSON is valid YAML
    proc = subprocess.run([str(CLI), "predict", "--stack", "engine", "--config", str(folder / "config.json"),
                           "--capture-per-request", "--output-dir", str(folder / "aisim"), "--overwrite"],
                          cwd=AISIM, capture_output=True, text=True)
    (folder / "run.log").write_text(proc.stdout + proc.stderr)
    if proc.returncode != 0:
        raise SystemExit(f"{folder.name}: aisim exited {proc.returncode}; see {folder / 'run.log'}\n"
                         + "\n".join(proc.stderr.strip().splitlines()[-3:]))
    requests = [json.loads(line) for line in (folder / "aisim/requests.jsonl").read_text().splitlines() if line.strip()]
    requests.sort(key=lambda r: r["arrival_time_ms"])
    return {"requests": [{k: r.get(k) for k in ("arrival_time_ms", "first_admit_ms", "first_token_ms", "last_token_ms",
                                                 "input_length", "output_length", "ttft_ms", "itl_ms", "terminal_status")}
                         for r in requests]}


def read_trace(path: Path) -> dict:
    header, passes = None, []
    for line in path.read_text().splitlines():
        item = json.loads(line)
        if item["type"] == "header":
            header = item
        else:
            passes.append(item)
    if header is None:
        raise SystemExit(f"{path}: no header line")
    return {"header": header, "passes": passes}


def summarize(two_tier: dict, native: dict, trace: dict) -> dict:
    last = trace["passes"][-1]["metrics"] if trace["passes"] else {}
    mean = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731
    return {
        "ttft_ms": [r["ttft_ms"] for r in two_tier["requests"]],
        "native_ttft_ms": [r["ttft_ms"] for r in native["requests"]],
        "itl_ms": [r["itl_ms"] for r in two_tier["requests"]],
        "native_itl_ms": [r["itl_ms"] for r in native["requests"]],
        "mean_ttft_ms": mean([r["ttft_ms"] for r in two_tier["requests"]]),
        "mean_itl_ms": mean([r["itl_ms"] for r in two_tier["requests"] if r["itl_ms"] is not None]),
        "makespan_ms": max(r["last_token_ms"] for r in two_tier["requests"]),
        "native_makespan_ms": max(r["last_token_ms"] for r in native["requests"]),
        "passes": len(trace["passes"]),
        "expert_hits": last.get("expert_hits"), "expert_lookups": last.get("expert_lookups"),
        "kv_hits": last.get("kv_hits"), "kv_lookups": last.get("kv_lookups"),
        "wait_experts_ms": last.get("wait_experts_ms"), "wait_kv_ms": last.get("wait_kv_ms"),
        "max_batch": max((len(p["requests"]) for p in trace["passes"]), default=0),
    }


def check(scenario: dict, s: dict) -> list[str]:
    errors = []
    for key, (low, high) in scenario.get("expect", {}).items():
        value = s[key]
        if value is None or not (low <= value <= high):
            errors.append(f"{key}: expected within [{low}, {high}], got {value}")
    return errors


RELATIONS = [
    ("链路无限快时，闭环时间线与 AISim 原生一致（1% 以内）",
     lambda m: all(abs(a - b) <= 0.01 * b + 1e-6 for a, b in zip(m["reconcile"]["ttft_ms"], m["reconcile"]["native_ttft_ms"]))
     and abs(m["reconcile"]["makespan_ms"] - m["reconcile"]["native_makespan_ms"]) <= 0.01 * m["reconcile"]["native_makespan_ms"]),
    ("链路更快时整体完成更早", lambda m: m["fast-link"]["makespan_ms"] < m["baseline"]["makespan_ms"]),
    ("4 个 prefill 合并后整体完成更早", lambda m: m["batched-prefill"]["makespan_ms"] < m["baseline"]["makespan_ms"]),
    ("专家路由更稳定时 ITL 更低", lambda m: m["sticky-experts"]["mean_itl_ms"] < m["baseline"]["mean_itl_ms"]),
    ("一级变小时 ITL 更高", lambda m: m["small-tier1"]["mean_itl_ms"] > m["baseline"]["mean_itl_ms"]),
    ("错峰到达时出现了多请求同批 decode", lambda m: m["baseline"]["max_batch"] >= 2),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=HERE / "output")
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--publish", type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    chosen = [s for s in SCENARIOS if not args.only or s["slug"] in args.only]
    natives: dict[str, dict] = {}
    items, metrics, failed = [], {}, False
    for scenario in chosen:
        key = workload_key(scenario["workload"])
        if key not in natives:
            natives[key] = run_aisim(out / f"native-{len(natives)}", scenario["workload"], None)
        folder = out / scenario["slug"]
        two_tier = {**copy.deepcopy(BASE_TWO_TIER), **scenario["overrides"], "trace_path": str(folder / "two-tier.jsonl")}
        result = run_aisim(folder, scenario["workload"], two_tier)
        trace = read_trace(folder / "two-tier.jsonl")
        s = summarize(result, natives[key], trace)
        metrics[scenario["slug"]] = s
        errors = check(scenario, s)
        failed |= bool(errors)
        print(f"{scenario['slug']}: " + ("OK" if not errors else "MISMATCH " + "; ".join(errors)))
        if args.show:
            print("  " + json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in s.items()
                                     if not isinstance(v, list)} | {k: [round(x, 1) if x else x for x in s[k]] for k in ("ttft_ms", "native_ttft_ms", "itl_ms")}))
        items.append({"slug": scenario["slug"], "title": scenario["title"], "summary": scenario["summary"],
                      "finding": scenario.get("finding", ""), "workload": scenario["workload"],
                      "changes": [{"param": k, "base": BASE_TWO_TIER.get(k), "value": v} for k, v in scenario["overrides"].items()],
                      "two_tier": result, "native": natives[key], "trace": trace, "summary_metrics": s})
    if not args.only:
        for name, holds in RELATIONS:
            ok = holds(metrics)
            failed |= not ok
            print(f"relation: {name}: " + ("OK" if ok else "MISMATCH"))
    if failed:
        return 1
    page = out / "two-tier-dram-engine-replay.html"
    write_page(items, page)
    print(f"wrote {page} ({page.stat().st_size / 1e6:.1f} MB)")
    if args.publish:
        args.publish.write_bytes(page.read_bytes())
        print(f"published {args.publish}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
