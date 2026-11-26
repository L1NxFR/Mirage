"""Two-tier DRAM under expert parallelism: EXI-3DDRAM cards in an 8-way attention-DP + EP group.

    python3 src/two-tier-dram-engine/ep.py [--aisim PATH] [--out DIR] [--only NAME ...]

Each run is `aisim predict --stack engine` with `parallelism: {attention_data: 8, moe_expert: 8}`:
AISim prices every group pass, expert-parallel communication included, and each rank's two-tier
model fetches the experts it owns for the whole group's tokens. Rank 0 writes the trace. AISim's
native EP8 run of the same workload is the reference. Checks print OK or
MISMATCH; any MISMATCH exits 1.

No counterfactual runs: every two-tier run enforces the tier-2 capacity check. A rank holds the
non-expert weights and 1/8 of the routed experts, 128.7 GB of DeepSeek-V4-Pro, so tier 2 is 192 GB
(the architecture table allows 64-512 GB); a 128 GB run checks that the engine rejects it.
"""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from scenarios import BASE_TWO_TIER, config_for  # noqa: E402

EP = 8
GROUP = {"replicas": 1, "tensor": 1, "attention_data": EP, "moe_expert": EP}
EXI96 = {"tier1_gb": 96.0, "base_weights": "resident"}
# Feasible tier 2 for one rank's 128.7 GB, with the capacity check on.
FEASIBLE = {"tier2_gb": 192.0, "tier2_capacity_check": "enforce"}
# Corrected baseline from the hardware survey: 1.1 TB/s LPDDR6, 0.8 copy efficiency, 2 us per transfer.
SURVEY = {"tier2_bandwidth_gbps": 1100.0, "copy_efficiency": 0.8, "link_overhead_ms": 0.002}


def workload(n: int, gap_ms: float, prompt: int, output: int, budget: int) -> dict:
    return {"requests": [(gap_ms * i, prompt, output) for i in range(n)], "max_batched_tokens": budget, "max_sequences": 4}


# Requests for the whole 8-card group; AISim places them on attention-DP ranks.
WORKLOADS = {
    "together": workload(EP, 0, 16384, 8, 16384),             # one 16K request per card, all at once
    "staggered": workload(4 * EP, 50 / EP, 16384, 8, 16384),   # ~4 per card, one every 6.25 ms
    "decode": workload(4 * EP, 50 / EP, 16384, 64, 16384),     # the same with 64 output tokens
}

RUNS = [
    # name, workload, two_tier overrides (None: native AISim), note
    ("native", "staggered", None, "AISim 原生 EP8"),
    ("unlimited", "staggered", {"tier2_bandwidth_gbps": 1e9}, "复制带宽无限"),
    ("exi36", "staggered", {}, "EXI 36 GB，逐层轮换"),
    ("exi36-partition", "staggered", {"expert_policy": "layer_partition"}, "EXI 36 GB，分层分区"),
    ("exi96", "staggered", EXI96, "EXI 96 GB，常驻"),
    ("survey", "staggered", SURVEY, "调研修正：1.1 TB/s × 0.8，2 µs"),
    ("together", "together", {}, "同时到达"),
    ("decode", "decode", {}, "输出 64"),
    ("decode-partition", "decode", {"expert_policy": "layer_partition"}, "输出 64，分层分区"),
    ("decode96", "decode", EXI96, "输出 64，96 GB 常驻"),
    ("enforce128", "together", {"tier2_gb": 128.0}, "二级 128 GB：应被拒绝"),
    ("native-together", "together", None, "AISim 原生 EP8，同时到达"),
    ("native-decode", "decode", None, "AISim 原生 EP8，输出 64"),
]


def run(aisim: Path, out: Path, name: str, wl: str, overrides: dict | None) -> dict:
    folder = out / name
    folder.mkdir(parents=True, exist_ok=True)
    w = WORKLOADS[wl]
    trace_file = folder / "requests.mooncake.jsonl"
    trace_file.write_text("".join(
        json.dumps({"request_id": f"R{i}", "timestamp": t, "input_length": n, "output_length": o, "hash_ids": [100 * i + 1]}) + "\n"
        for i, (t, n, o) in enumerate(w["requests"], start=1)))
    two_tier = None if overrides is None else {**copy.deepcopy(BASE_TWO_TIER), **FEASIBLE, **overrides,
                                               "trace_path": str(folder / "two-tier.jsonl"), "trace_passes": 1_000_000}
    config = config_for(w, trace_file, two_tier)
    config["engine"]["workers"]["aggregated"]["parallelism"] = GROUP
    (folder / "config.json").write_text(json.dumps(config, indent=1))
    cli = aisim / "python/aisim/.venv/bin/aisim"
    proc = subprocess.run([str(cli), "predict", "--stack", "engine", "--config", str(folder / "config.json"),
                           "--capture-per-request", "--output-dir", str(folder / "aisim"), "--overwrite"],
                          cwd=aisim, capture_output=True, text=True)
    log = proc.stdout + proc.stderr
    (folder / "run.log").write_text(log)
    if proc.returncode != 0:
        reason = next((line.strip() for line in reversed(log.splitlines()) if "two_tier_dram" in line), log.strip()[-300:])
        return {"name": name, "error": reason[reason.find("two_tier_dram"):] if "two_tier_dram" in reason else reason}
    requests = [json.loads(line) for line in (folder / "aisim/requests.jsonl").read_text().splitlines() if line.strip()]
    result = {"name": name, "requests": len(requests),
              "makespan_ms": max(r["last_token_ms"] for r in requests),
              "mean_ttft_ms": sum(r["ttft_ms"] for r in requests) / len(requests),
              "mean_itl_ms": sum(r["itl_ms"] for r in requests if r["itl_ms"] is not None) / len(requests)}
    trace = folder / "two-tier.jsonl"
    if trace.exists():
        lines = trace.read_text().splitlines()
        header, passes = json.loads(lines[0]), [json.loads(line) for line in lines[1:]]
        last = passes[-1]["metrics"]
        first = passes[0]["metrics"]["link_bytes"]
        result |= {"card_weights_gb": header["card_weights_bytes"] / 1e9, "tier2_feasible": header["tier2_feasible"],
                   "passes": len(passes), "expert_hits": last["expert_hits"], "expert_lookups": last["expert_lookups"],
                   "wait_ms": {k: last[k] for k in ("wait_base_ms", "wait_kv_ms", "wait_experts_ms")},
                   "copy_gb": sum(last["link_bytes"].values()) / 1e9,
                   "first_pass_expert_gb": (first["demand_expert"] + first["prefetch_expert"]) / 1e9,
                   "first_pass": {"requests": passes[0]["requests"], "ms": passes[0]["end_ms"] - passes[0]["start_ms"],
                                  "native_ms": passes[0]["native_ms"]}}
    return result


def checks(m: dict) -> list[tuple[str, bool, str]]:
    ok = lambda name: name in m and "error" not in m[name]  # noqa: E731
    out = []
    if ok("unlimited") and ok("native"):
        a, b = m["unlimited"]["makespan_ms"], m["native"]["makespan_ms"]
        out.append(("复制带宽无限时与 AISim 原生 EP8 一致（1% 以内）", abs(a - b) <= 0.01 * b, f"{a:.1f} / {b:.1f} ms"))
    if ok("together"):
        gb = m["together"]["first_pass_expert_gb"]
        out.append(("同时到达时，rank 0 第一个 pass 搬的专家约为整套路由专家的 1/8（96.7 GB，±10%）", 87 <= gb <= 106.4, f"{gb:.1f} GB"))
        w = m["together"]["card_weights_gb"]
        out.append(("每卡权重 = 非专家 + 1/8 路由专家 ≈ 128.7 GB", abs(w - 128.7) < 0.5, f"{w:.1f} GB"))
    out.append(("二级 128 GB 强制检查拒绝（每卡 128.7 GB）", "error" in m.get("enforce128", {}), m.get("enforce128", {}).get("error", "未拒绝")[:120]))
    traced = [r for r in m.values() if "tier2_feasible" in r]
    out.append(("所有两级结果二级可行（没有反事实运行）", bool(traced) and all(r["tier2_feasible"] for r in traced),
                f"{sum(r['tier2_feasible'] for r in traced)}/{len(traced)}"))
    if ok("survey") and ok("exi36"):
        out.append(("调研修正（1.1 TB/s × 0.8）比 2.2 TB/s 慢", m["survey"]["makespan_ms"] > m["exi36"]["makespan_ms"],
                    f"{m['survey']['makespan_ms']:.0f} / {m['exi36']['makespan_ms']:.0f} ms"))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--aisim", type=Path, default=HERE.parent / "aisim")
    parser.add_argument("--out", type=Path, default=HERE / "output" / "ep")
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()
    chosen = [r for r in RUNS if not args.only or r[0] in args.only]
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda r: run(args.aisim.resolve(), args.out.resolve(), *r[:3]), chosen))
    m = {r["name"]: r for r in results}
    for (name, wl, _, note), r in zip(chosen, results):
        if "error" in r:
            print(f"{name:18s} {note}: rejected: {r['error'][:160]}")
            continue
        extra = ""
        if "expert_hits" in r:
            extra = (f" | card {r['card_weights_gb']:.1f} GB feasible={r['tier2_feasible']} hits {r['expert_hits']}/{r['expert_lookups']}"
                     f" copy {r['copy_gb']:.0f} GB first-pass experts {r['first_pass_expert_gb']:.1f} GB"
                     f" waits {', '.join(f'{v:.0f}' for v in r['wait_ms'].values())} ms")
        print(f"{name:18s} {note}: {r['requests']} req, makespan {r['makespan_ms']:.0f} ms, TTFT {r['mean_ttft_ms']:.0f} ms,"
              f" ITL {r['mean_itl_ms']:.2f} ms{extra}")
    failed = False
    for name, holds, detail in checks(m):
        failed |= not holds
        print(f"check: {name}: {'OK' if holds else 'MISMATCH'} ({detail})")
    (args.out / "summary.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
