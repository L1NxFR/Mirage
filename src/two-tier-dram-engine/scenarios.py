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
SYSTEMS = HERE.parent / "two-tier-dram" / "systems"  # exi_3ddram.yaml, shared with the stack implementation
MODEL = "deepseek-ai/DeepSeek-V4-Pro"
sys.path.insert(0, str(HERE))

from render import write_page  # noqa: E402

# EXI-3DDRAM figure configuration (two_tier.py defaults): 36 GB tier 1, 128 GB LPDDR6 at 2.2 TB/s,
# ideal copies, no per-transfer overhead. Its 36 GB cannot hold the 32 GB of non-expert weights next to
# scratch, so they rotate layer by layer; 128 GB cannot hold the 805.7 GB model, so every run is an
# explicit counterfactual. Sources per field: src/two-tier-dram/two_tier_dram/config.py (exi_figure).
BASE_TWO_TIER = {"tier1_gb": 36.0, "tier2_gb": 128.0, "tier2_bandwidth_gbps": 2200.0, "copy_efficiency": 1.0,
                 "link_overhead_ms": 0.0, "base_weights": "layer_prefetch", "tier2_capacity_check": "counterfactual",
                 "expert_overlap": 0.5, "topk_overlap": 0.75, "hot_kv_entries": 65536, "expert_prefetch": "none",
                 "link_policy": "demand_first", "seed": 0, "trace_passes": 4}
EXI96 = {"tier1_gb": 96.0, "base_weights": "resident"}

# Four 16K-token requests 50 ms apart, 8 output tokens each; up to 4 decode together.
STAGGERED = {"requests": [(0, 16384, 8), (50, 16384, 8), (100, 16384, 8), (150, 16384, 8)],
             "max_batched_tokens": 16384, "max_sequences": 4}
# The same four requests arriving together, with a budget that prefills them in one pass.
TOGETHER = {"requests": [(0, 16384, 8)] * 4, "max_batched_tokens": 65536, "max_sequences": 4}

SCENARIOS = [
    {"slug": "exi36", "title": "EXI 36 GB：4 个请求错峰到达",
     "summary": "EXI 图示配置：一级 36 GB（18 TB/s），二级 128 GB LPDDR6（2.2 TB/s），非专家权重逐层轮换。",
     "finding": "全部完成 4.61 s，原生 2.97 s（+55%）。R1 的 TTFT 1078 ms = 原生 726 ms + 352 ms：16K token 的 prefill 每层几乎用到全部专家，整套路由专家 773.7 GB ÷ 2.2 TB/s ≈ 352 ms，4 个 prefill 各搬一遍。纯 decode 的 8 个 pass 合计 212 ms（原生 25.7 ms），其中 77 ms 在等轮换进来的非专家权重。复制总量 3785 GB；若复制写入与计算读取争用一级的 18 TB/s，最多再多 210 ms，未计入。",
     "workload": STAGGERED, "overrides": {}},
    {"slug": "reconcile", "title": "对账：复制带宽无限",
     "summary": "同一配置，二级带宽 1e9 GB/s、每次传输开销 0。",
     "finding": "4 个请求的 TTFT 与 AISim 原生一致，全部完成 2971.635 ms 对 2971.631 ms。",
     "workload": STAGGERED, "overrides": {"tier2_bandwidth_gbps": 1e9}},
    {"slug": "exi96", "title": "EXI 96 GB 探索：非专家权重常驻",
     "summary": "一级换成研究记录中的 96 GB 方案，非专家权重常驻，其余与 EXI 图示配置相同。",
     "finding": "全部完成 4.48 s，只比 36 GB 快 3%。纯 decode pass 从 212 ms 降到 89 ms，不再等非专家权重；但含 prefill 的 pass 都要搬整套专家，这部分两种一级容量一样，占了大部分时间。专家命中从 310 次升到 3380 次。",
     "workload": STAGGERED, "overrides": EXI96},
    {"slug": "exi36-eff07", "title": "复制效率 0.7",
     "summary": "有效复制带宽 = 2.2 TB/s × 0.7（假设折损）。",
     "finding": "有效复制 1.54 TB/s：全部完成 5.32 s，每个 prefill 的专家搬运约 0.5 s。",
     "workload": STAGGERED, "overrides": {"copy_efficiency": 0.7}},
    {"slug": "exi36-1.1x07", "title": "LPDDR6 低端 1.1 TB/s × 0.7",
     "summary": "二级标称带宽取架构表下端 1.1 TB/s，复制效率 0.7。",
     "finding": "有效复制 0.77 TB/s：全部完成 7.70 s，每个 prefill 的专家搬运约 1.0 s。时延对复制带宽基本线性。",
     "workload": STAGGERED, "overrides": {"tier2_bandwidth_gbps": 1100.0, "copy_efficiency": 0.7}},
    {"slug": "exi36-overhead", "title": "每次传输 10 µs 开销",
     "summary": "每次传输加 0.01 ms 固定开销（假设，表中未给出）。",
     "finding": "全部完成只多 19 ms（4625 ms）。等 KV 从 0.26 ms 变成 5.7 ms：传输次数多但字节少的 top-k KV 对开销敏感，专家搬运以字节为主，不受影响。",
     "workload": STAGGERED, "overrides": {"link_overhead_ms": 0.01}},
    {"slug": "exi96-together", "title": "96 GB：4 个请求同时到达、一个 pass 完成 prefill",
     "summary": "4 个请求同时到达，max_batched_tokens 65536，4 个 prefill 共用一次专家搬运。",
     "finding": "4 个 prefill 合进一个 pass，整套专家只搬一遍：全部完成 3.37 s，原生 2.93 s（+15%），复制总量从 3316 GB 降到 960 GB。之后 batch 4 的 decode 每步约 16 ms。",
     "workload": TOGETHER, "overrides": EXI96},
    {"slug": "enforce", "title": "二级容量强制检查",
     "summary": "tier2_capacity_check: enforce。805.7 GB 的模型放不进 128 GB 二级，运行应被拒绝。",
     "finding": "运行被拒绝：805.7 GB 的权重放不进 128 GB 二级。其余场景都显式设为反事实，结果不可行。",
     "workload": STAGGERED, "overrides": {"tier2_capacity_check": "enforce"},
     "expect_failure": "tier 2 cannot hold the weights"},
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
            "mode": "aggregated", "model": MODEL, "hardware": "exi_3ddram", "backend": "vllm",
            "backend_version": "0.30.0", "context_length": 131072,
            # EXI-SOL: AISim's analytical roofline on the EXI system file (tier-1 18 TB/s, FP8/FP4 peaks).
            "ais_perf_model": {"estimation_mode": "op_level", "database_mode": "SOL", "systems_paths": [str(SYSTEMS), "default"]},
            "workers": {"aggregated": {
                "parallelism": {"replicas": 1, "tensor": 1, "attention_data": 1},
                "scheduler": {"max_batched_tokens": workload["max_batched_tokens"], "max_sequences": workload["max_sequences"]},
                # The model's 1579 GB of weights exceed one device, the premise of the design;
                # fixed G1 capacity (here: tier-2 KV) keeps AISim's single-tier memory check out of the way.
                "kv_cache": kv_cache,
            }},
        },
    }


def run_aisim(folder: Path, workload: dict, two_tier: dict | None, expect_failure: str | None = None) -> dict:
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
    if expect_failure is not None:
        return {"failed": proc.returncode != 0, "matched": expect_failure in proc.stdout + proc.stderr,
                "message": next((l for l in (proc.stdout + proc.stderr).splitlines() if expect_failure in l), "")}
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
        "tier2_feasible": trace["header"].get("tier2_feasible"),
        "link_gb": sum(last.get("link_bytes", {}).values()) / 1e9,
        # Upper bound of the tier-1 time copies would steal from compute if writes and reads shared its bandwidth.
        "tier1_contention_upper_ms": (sum(last.get("link_bytes", {}).values()) / tier1_bw * 1e3) if (tier1_bw := trace["header"]["config"]["profile"]["source"].get("tier1_bandwidth_bytes_per_s")) else None,
    }


def check(scenario: dict, s: dict) -> list[str]:
    errors = []
    for key, (low, high) in scenario.get("expect", {}).items():
        value = s[key]
        if value is None or not (low <= value <= high):
            errors.append(f"{key}: expected within [{low}, {high}], got {value}")
    return errors


RELATIONS = [
    ("复制带宽无限时，闭环时间线与 AISim 原生一致（1% 以内）",
     lambda m: all(abs(a - b) <= 0.01 * b + 1e-6 for a, b in zip(m["reconcile"]["ttft_ms"], m["reconcile"]["native_ttft_ms"]))
     and abs(m["reconcile"]["makespan_ms"] - m["reconcile"]["native_makespan_ms"]) <= 0.01 * m["reconcile"]["native_makespan_ms"]),
    ("复制效率 0.7 比 1.0 慢", lambda m: m["exi36-eff07"]["makespan_ms"] > m["exi36"]["makespan_ms"]),
    ("1.1 TB/s × 0.7 比 2.2 TB/s × 0.7 慢", lambda m: m["exi36-1.1x07"]["makespan_ms"] > m["exi36-eff07"]["makespan_ms"]),
    ("每次传输加开销后变慢", lambda m: m["exi36-overhead"]["makespan_ms"] > m["exi36"]["makespan_ms"]),
    ("96 GB 常驻非专家权重比 36 GB 轮换快", lambda m: m["exi96"]["makespan_ms"] < m["exi36"]["makespan_ms"]),
    ("同时到达合并 prefill 比错峰到达更早完成", lambda m: m["exi96-together"]["makespan_ms"] < m["exi96"]["makespan_ms"]),
    ("所有反事实运行都标记为二级不可行", lambda m: all(v["tier2_feasible"] is False for v in m.values())),
    ("错峰到达时出现了多请求同批 decode", lambda m: m["exi36"]["max_batch"] >= 2),
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
        if "expect_failure" in scenario:
            outcome = run_aisim(folder, scenario["workload"], two_tier, expect_failure=scenario["expect_failure"])
            ok = outcome["failed"] and outcome["matched"]
            failed |= not ok
            print(f"{scenario['slug']}: " + (f"OK (rejected: {outcome['message'].strip()[-140:]})" if ok else f"MISMATCH expected failure, got {outcome}"))
            continue
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
