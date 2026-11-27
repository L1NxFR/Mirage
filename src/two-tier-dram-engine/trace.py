"""Run `kv_cache.two_tier_dram` on a window of a real Mooncake request trace.

    python3 src/two-tier-dram-engine/trace.py [--hardware NAME] [--trace NAME] [--start-s S] [--duration-s S] [--speedup X] [--setup NAME ...] [--only RUN ...]

The requests (arrival time, input length, output length, prefix hash blocks) come unchanged from the
public Mooncake FAST'25 traces in `traces/mooncake-fast25/` (source and checksums in the README);
only the window's first timestamp is moved to 0. `--speedup X` replays arrivals X times as fast (AISim's
`trace_timestamps` speedup); below 1 it thins the load to what the deployment can serve, and the result
is then labelled as rate-scaled. Each run is a real `aisim predict --stack engine`.

`--hardware` picks the device (see HARDWARE):
- gb200 (default): one NVIDIA GB200 compute tray, 4 B200 and 2 Grace. AISim's own `gb200` system file
  and its measured (SILICON) perf database price compute. Tier 1 is a B200's HBM3e, tier 2 its half of a
  Grace's LPDDR5X, the link its share of NVLink-C2C. DeepSeek-V4-Pro with 4-way expert parallelism needs
  225.4 GB per card: more than the HBM, less than the LPDDR5X share.
- exi: the EXI-3DDRAM design inputs on AISim's analytical roofline, with DeepSeek-V4-Flash on one card and
  DeepSeek-V4-Pro on 8 cards, 192 GB of tier 2 per card.
Every run enforces the tier-2 capacity check. AISim's KV capacity is what tier 2 has left after the
weights, so the scheduler admits requests against tier 2's KV room. The scheduler keeps AISim's vLLM defaults.

Still synthetic: expert routing and top-k selection (seeded draws in the engine).
Checks print OK or MISMATCH; any MISMATCH exits 1.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from scenarios import AISIM, BASE_TWO_TIER, CLI, SYSTEMS  # noqa: E402

TRACES = HERE / "traces" / "mooncake-fast25"
SHA256 = {"conversation": "b8cbb061a85206d729d91cdc2981f43c9e0d99209dce588d3af5f7934408b9df",
          "toolagent": "48a2db1a13d3bc05e6330140c64f604ba366df20d3c9e128b5c35a01c1fa5f71"}
BLOCK_TOKENS = 512  # tokens per hash block in the Mooncake traces
KV_BLOCK_TOKENS = 64  # vLLM's KV block; a capacity in bytes needs it stated
PRO, FLASH = "deepseek-ai/DeepSeek-V4-Pro", "deepseek-ai/DeepSeek-V4-Flash"
COMMON = {**copy.deepcopy(BASE_TWO_TIER), "tier2_capacity_check": "enforce", "trace_passes": 0}
# `weights` is the engine's card_weights_bytes for the setup; a check compares it with each run's trace header.
# `kv_bytes_per_token` is the compressed KV one context token adds over all layers in the engine's profile:
# 512 B per entry, plus 64 B of indexer cache on sparse layers, divided by each layer's compress ratio.
HARDWARE = {
    # One GB200 tray. Sources per value: related-work/two-tier-dram-hardware-parameters.md.
    "gb200": {
        "engine": {"hardware": "gb200", "backend_version": "0.24.0", "ais_perf_model": {"database_mode": "SILICON"}},
        "two_tier": {
            "tier1_gb": 198.674743296,      # gb200.yaml mem_capacity: 189,471 MiB reported by nvidia-smi
            "scratch_gb": 4.169138176,      # gb200.yaml other_mem + nccl_mem at 4 GPUs
            "tier2_gb": 240.0,              # 480 GB of LPDDR5X per Grace, two B200 per Grace
            "tier2_bandwidth_gbps": 225.0,  # 900 GB/s NVLink-C2C both ways, two B200 per Grace: 225 GB/s one way each
            "copy_efficiency": 0.75,        # NVIDIA's Grace tuning guide: about 170 GB/s device to host
            "link_overhead_ms": 0.002,      # 1-3 us per transfer measured on PCIe; no C2C figure found
            "base_weights": "resident",
        },
        "setups": {
            "pro-ep4": {"model": PRO, "weights": 225_411_468_664, "kv_bytes_per_token": 4444,
                        "parallelism": {"replicas": 1, "tensor": 1, "attention_data": 4, "moe_expert": 4}},
        },
        "variants": {"native": None, "lru": {}, "partition": {"expert_policy": "layer_partition"}},
    },
    # EXI-3DDRAM design inputs with the survey's corrected link: 1.1 TB/s tier 2, 0.8 copy efficiency, 2 us.
    "exi": {
        "engine": {"hardware": "exi_3ddram", "backend_version": "0.30.0",
                   "ais_perf_model": {"estimation_mode": "op_level", "database_mode": "SOL",
                                      "systems_paths": [str(SYSTEMS), "default"]}},
        "two_tier": {"tier2_gb": 192.0, "tier2_bandwidth_gbps": 1100.0, "copy_efficiency": 0.8, "link_overhead_ms": 0.002},
        "setups": {
            "flash-1card": {"model": FLASH, "weights": 148_486_152_008, "kv_bytes_per_token": 3104,
                            "parallelism": {"replicas": 1, "tensor": 1, "attention_data": 1}},
            "pro-ep8": {"model": PRO, "weights": 128_699_207_032, "kv_bytes_per_token": 4444,
                        "parallelism": {"replicas": 1, "tensor": 1, "attention_data": 8, "moe_expert": 8}},
        },
        "variants": {
            "native": None,
            "t36-lru": {},
            "t36-partition": {"expert_policy": "layer_partition"},
            "t96-lru": {"tier1_gb": 96.0, "base_weights": "resident"},
            "t96-partition": {"tier1_gb": 96.0, "base_weights": "resident", "expert_policy": "layer_partition"},
        },
    },
}
QUANTILES = (("p50", 0.5), ("p90", 0.9), ("p99", 0.99))


def window(name: str, start_s: float, duration_s: float, out: Path) -> dict:
    source = TRACES / f"{name}_trace.jsonl"
    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SHA256[name]:
        raise SystemExit(f"{source}: sha256 {digest} is not the recorded {SHA256[name]}")
    lo, hi = start_s * 1000, (start_s + duration_s) * 1000
    rows = [(i, json.loads(line)) for i, line in enumerate(data.splitlines())]
    rows = [(i, r) for i, r in rows if lo <= r["timestamp"] < hi]
    if not rows:
        raise SystemExit(f"no requests of {name} in [{start_s}, {start_s + duration_s}) s")
    t0 = rows[0][1]["timestamp"]
    out.mkdir(parents=True, exist_ok=True)
    path = out / "window.mooncake.jsonl"
    path.write_text("".join(json.dumps({**r, "timestamp": r["timestamp"] - t0}) + "\n" for _, r in rows))
    return {"trace": name, "sha256": digest, "start_s": start_s, "duration_s": duration_s, "path": str(path),
            "rows": [rows[0][0], rows[-1][0]], "requests": len(rows),
            "input_tokens": sum(r["input_length"] for _, r in rows),
            "output_tokens": sum(r["output_length"] for _, r in rows)}


def config(hw: dict, setup: dict, trace_file: str, speedup: float, two_tier: dict | None) -> dict:
    kv_cache = {"prefix_caching": True, "block_size": KV_BLOCK_TOKENS, "bytes_per_token": setup["kv_bytes_per_token"],
                "capacity": {"type": "fixed", "bytes": int(hw["two_tier"]["tier2_gb"] * 1e9) - setup["weights"]}}
    if two_tier is not None:
        kv_cache["two_tier_dram"] = two_tier
    return {
        "execution": {"resources": {"initialization_timeout_seconds": 300}},
        "traffic": {"source": {"type": "trace", "format": "mooncake", "block_size": BLOCK_TOKENS, "paths": [trace_file]},
                    "load": {"type": "trace_timestamps", "speedup": speedup}},
        "engine": {
            "mode": "aggregated", "model": setup["model"], "backend": "vllm", "context_length": 131072, **hw["engine"],
            "workers": {"aggregated": {"parallelism": setup["parallelism"], "kv_cache": kv_cache}},
        },
    }


def quantile(values: list[float], q: float) -> float:
    values = sorted(values)
    return values[round(q * (len(values) - 1))]


def run(out: Path, hw: dict, setup_name: str, variant: str, trace_file: str, speedup: float) -> dict:
    folder = out / setup_name / variant
    folder.mkdir(parents=True, exist_ok=True)
    overrides = hw["variants"][variant]
    two_tier = None if overrides is None else {**COMMON, **hw["two_tier"], **overrides, "trace_path": str(folder / "two-tier.jsonl")}
    (folder / "config.json").write_text(json.dumps(config(hw, hw["setups"][setup_name], trace_file, speedup, two_tier), indent=1))
    proc = subprocess.run([str(CLI), "predict", "--stack", "engine", "--config", str(folder / "config.json"),
                           "--capture-per-request", "--output-dir", str(folder / "aisim"), "--overwrite"],
                          cwd=AISIM, capture_output=True, text=True)
    log = proc.stdout + proc.stderr
    (folder / "run.log").write_text(log)
    result = {"setup": setup_name, "variant": variant}
    if proc.returncode != 0:
        lines = [line.strip() for line in log.splitlines() if "failed" in line or "Error" in line]
        return result | {"error": (lines[0] if lines else log.strip()[-400:])[-400:]}
    requests = [json.loads(line) for line in (folder / "aisim/requests.jsonl").read_text().splitlines() if line.strip()]
    done = [r for r in requests if r.get("terminal_status") == "completed"]
    itl = [r["itl_ms"] for r in done if r["itl_ms"] is not None]
    result |= {"requests": len(requests), "completed": len(done),
               "makespan_ms": max(r["last_token_ms"] for r in done),
               "ttft_ms": {name: quantile([r["ttft_ms"] for r in done], q) for name, q in QUANTILES},
               "e2e_ms": {name: quantile([r["e2e_latency_ms"] for r in done], q) for name, q in QUANTILES},
               "mean_itl_ms": sum(itl) / len(itl),
               "reused_input_tokens": sum(r.get("reused_input_tokens") or 0 for r in done),
               "input_tokens": sum(r["input_length"] for r in done)}
    trace = folder / "two-tier.jsonl"
    if trace.exists():
        with trace.open() as f:
            header = json.loads(f.readline())
            last = None
            for line in f:
                last = line
        m = json.loads(last)["metrics"]
        result |= {"tier2_feasible": header["tier2_feasible"], "card_weights_bytes": header["card_weights_bytes"],
                   "passes": m["passes"], "native_ms": m["native_ms"], "two_tier_ms": m["two_tier_ms"],
                   "wait_ms": {k: m[k] for k in ("wait_base_ms", "wait_kv_ms", "wait_experts_ms")},
                   "expert_hits": m["expert_hits"], "expert_lookups": m["expert_lookups"],
                   "kv_hits": m["kv_hits"], "kv_lookups": m["kv_lookups"],
                   "link_gb": {k: v / 1e9 for k, v in m["link_bytes"].items()},
                   "peak_tier1_gb": m["peak_tier1_bytes"] / 1e9}
    return result


def checks(results: list[dict], info: dict, setups: dict) -> list[tuple[str, bool, str]]:
    ok = [r for r in results if "error" not in r]
    failures = "; ".join(f"{r['setup']}/{r['variant']}: {r['error']}" for r in results if "error" in r)
    out = [("每次运行都成功", len(ok) == len(results), failures or f"{len(ok)} 次")]
    out.append(("窗口内的请求全部完成", all(r["completed"] == info["requests"] for r in ok),
                ", ".join(f"{r['completed']}/{info['requests']}" for r in ok)))
    traced = [r for r in ok if "tier2_feasible" in r]
    out.append(("所有两级运行二级可行", all(r["tier2_feasible"] for r in traced),
                f"{sum(r['tier2_feasible'] for r in traced)}/{len(traced)}"))
    out.append(("KV 容量按引擎报告的每卡权重扣除", all(r["card_weights_bytes"] == setups[r["setup"]]["weights"] for r in traced),
                ", ".join(sorted({f"{r['setup']} {r['card_weights_bytes'] / 1e9:.3f} GB" for r in traced}))))
    native = {r["setup"]: r for r in ok if r["variant"] == "native"}
    paired = [r for r in traced if r["setup"] in native]
    out.append(("两级的 p50 TTFT 不早于原生",
                all(r["ttft_ms"]["p50"] >= native[r["setup"]]["ttft_ms"]["p50"] * 0.999 for r in paired),
                ", ".join(f"{r['setup']}/{r['variant']} {r['ttft_ms']['p50']:.0f}/{native[r['setup']]['ttft_ms']['p50']:.0f}" for r in paired)))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hardware", choices=list(HARDWARE), default="gb200")
    parser.add_argument("--trace", choices=list(SHA256), default="conversation")
    parser.add_argument("--start-s", type=float, default=0.0)
    parser.add_argument("--duration-s", type=float, default=300.0)
    parser.add_argument("--speedup", type=float, default=1.0, help="replay arrivals this many times as fast; 1 keeps the trace's rate")
    parser.add_argument("--setup", nargs="*", help="setups of the chosen hardware; default: all")
    parser.add_argument("--only", nargs="*", help="variants of the chosen hardware; default: all")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    hw = HARDWARE[args.hardware]
    for given, known in ((args.setup, hw["setups"]), (args.only, hw["variants"])):
        if unknown := [name for name in given or [] if name not in known]:
            parser.error(f"{args.hardware} has no {', '.join(unknown)}; choose from {', '.join(known)}")
    out = (args.out or HERE / "output" / "trace" / (f"{args.hardware}-{args.trace}-{args.start_s:g}-{args.duration_s:g}"
                                                      + (f"-x{args.speedup:g}" if args.speedup != 1 else ""))).resolve()
    info = window(args.trace, args.start_s, args.duration_s, out)
    print(f"{args.hardware}, speedup {args.speedup:g}, {args.trace} [{args.start_s:g}, {args.start_s + args.duration_s:g}) s: {info['requests']} requests, "
          f"{info['input_tokens']} input and {info['output_tokens']} output tokens")
    jobs = [(s, v) for s in args.setup or hw["setups"] for v in hw["variants"] if not args.only or v in args.only]
    with ThreadPoolExecutor(len(jobs)) as pool:
        results = list(pool.map(lambda job: run(out, hw, *job, info["path"], args.speedup), jobs))
    for r in results:
        if "error" in r:
            print(f"{r['setup']:12s} {r['variant']:14s} failed: {r['error']}")
            continue
        extra = ""
        if "wait_ms" in r:
            w = r["wait_ms"]
            extra = (f" | waits base/kv/experts {w['wait_base_ms']:.0f}/{w['wait_kv_ms']:.0f}/{w['wait_experts_ms']:.0f} ms"
                     f" | expert hits {r['expert_hits']}/{r['expert_lookups']} | kv hits {r['kv_hits']}/{r['kv_lookups']}"
                     f" | copied {sum(r['link_gb'].values()):.0f} GB")
        t = r["ttft_ms"]
        print(f"{r['setup']:12s} {r['variant']:14s} done {r['completed']}/{r['requests']}, makespan {r['makespan_ms'] / 1e3:.1f} s,"
              f" TTFT p50/p90/p99 {t['p50']:.0f}/{t['p90']:.0f}/{t['p99']:.0f} ms, ITL {r['mean_itl_ms']:.2f} ms,"
              f" prefix reuse {r['reused_input_tokens'] / r['input_tokens']:.1%}{extra}")
    failed = False
    for name, holds, detail in checks(results, info, hw["setups"]):
        failed |= not holds
        print(f"check: {name}: {'OK' if holds else 'MISMATCH'} ({detail[:400]})")
    aisim = subprocess.run(["git", "-C", str(AISIM), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    (out / "summary.json").write_text(json.dumps({"hardware": args.hardware, "speedup": args.speedup, "window": info, "aisim": aisim, "results": results}, ensure_ascii=False, indent=1))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
