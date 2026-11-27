"""Evaluate EXI capacity/bandwidth sweep points with the engine's two_tier_dram model.

    python3 src/two-tier-dram-engine/curves.py [--figure NAME ...] [--jobs N] [--out DIR]

Every point of targets/exi-slides.csv is one `aisim predict --stack engine` run on one card:
DeepSeek-V4-Pro, 8 requests of the point's context arriving together, 16 output tokens each.
TPOT is the median length of the steady passes, those where all 8 requests decode; ideal TPOT is
AISim's own price of the same passes, as if every byte were in tier 1. Tier 1 reads at 10 TB/s
(systems/exi_hbm10.yaml).

Tier 2 holds the weights plus the batch's full KV, with the capacity check enforced.
The link uses copy efficiency 1 and zero per-transfer cost. Expert routing uses
the engine's synthetic draw.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import math
import statistics
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from scenarios import AISIM, BASE_TWO_TIER, CLI, SYSTEMS  # noqa: E402

TARGETS = HERE / "targets" / "exi-slides.csv"
MODEL = "deepseek-ai/DeepSeek-V4-Pro"
WEIGHTS = 805_685_038_456  # the engine's card_weights_bytes for Pro on one card
KV_BYTES_PER_TOKEN = 4444  # compressed KV per context token over all layers (engine profile)
KV_BLOCK = 64              # vLLM KV block, tokens
TRACE_BLOCK = 512          # tokens per hash block in the request file
BATCH, OUTPUT = 8, 16
SKIP = 2                   # steady passes dropped while caches warm up


def tier2_gb(context: int) -> float:
    blocks = math.ceil((context + OUTPUT) / KV_BLOCK) * BATCH
    return math.ceil((WEIGHTS + blocks * KV_BLOCK * KV_BYTES_PER_TOKEN) / 1e8) / 10


def config(point: dict, folder: Path, expert_overlap: float) -> dict:
    context = int(point["context_tokens"])
    l1 = float(point["l1_gb"])
    requests = folder / "requests.mooncake.jsonl"
    blocks = math.ceil(context / TRACE_BLOCK)
    requests.write_text("".join(
        json.dumps({"request_id": f"R{i}", "timestamp": 0, "input_length": context, "output_length": OUTPUT,
                    "hash_ids": list(range(i * blocks, (i + 1) * blocks))}) + "\n" for i in range(BATCH)))
    tier2 = tier2_gb(context)
    two_tier = {**copy.deepcopy(BASE_TWO_TIER), "tier1_gb": l1, "tier2_gb": tier2, "tier2_capacity_check": "enforce",
                "tier2_bandwidth_gbps": float(point["l2_bw_tbps"]) * 1000, "copy_efficiency": 1.0, "link_overhead_ms": 0.0,
                # 32 GB of non-expert weights fit next to scratch from 48 GB of tier 1 up; at 36 GB they rotate.
                "base_weights": "resident" if l1 >= 48 else "layer_prefetch",
                "expert_policy": "layer_partition", "expert_overlap": expert_overlap, "trace_path": str(folder / "two-tier.jsonl"), "trace_passes": 0}
    return {
        "execution": {"resources": {"initialization_timeout_seconds": 300}},
        "traffic": {"source": {"type": "trace", "format": "mooncake", "block_size": TRACE_BLOCK, "paths": [str(requests)]},
                    "load": {"type": "trace_timestamps"}},
        "engine": {
            "mode": "aggregated", "model": MODEL, "hardware": "exi_hbm10", "backend": "vllm", "backend_version": "0.30.0",
            "context_length": context + OUTPUT + KV_BLOCK,
            "ais_perf_model": {"estimation_mode": "op_level", "database_mode": "SOL", "systems_paths": [str(SYSTEMS), "default"]},
            "workers": {"aggregated": {
                "parallelism": {"replicas": 1, "tensor": 1, "attention_data": 1},
                "scheduler": {"max_batched_tokens": context, "max_sequences": BATCH},
                "kv_cache": {"block_size": KV_BLOCK, "bytes_per_token": KV_BYTES_PER_TOKEN, "prefix_caching": False,
                             "capacity": {"type": "fixed", "bytes": int(tier2 * 1e9) - WEIGHTS},
                             "two_tier_dram": two_tier},
            }},
        },
    }


def run(out: Path, point: dict, expert_overlap: float) -> dict:
    name = f"{point['figure']}-l1_{point['l1_gb']}-bw_{point['l2_bw_tbps']}"
    folder = out / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "config.json").write_text(json.dumps(config(point, folder, expert_overlap), indent=1))
    proc = subprocess.run([str(CLI), "predict", "--stack", "engine", "--config", str(folder / "config.json"),
                           "--output-dir", str(folder / "aisim"), "--overwrite"], cwd=AISIM, capture_output=True, text=True)
    log = proc.stdout + proc.stderr
    (folder / "run.log").write_text(log)
    result = {"name": name, **point}
    if proc.returncode != 0:
        lines = [x.strip() for x in log.splitlines() if "two_tier_dram" in x or "failed" in x]
        return result | {"error": (lines[-1] if lines else log.strip()[-300:])[-300:]}
    with (folder / "two-tier.jsonl").open() as f:
        header = json.loads(f.readline())
        passes = [json.loads(line) for line in f]
    steady, prev = [], None
    for p in passes:
        link = sum(p["metrics"]["link_bytes"].values())
        reqs = p["requests"]
        if prev is not None and len(reqs) == BATCH and all(r["kind"] == "decode" for r in reqs):
            steady.append((p["end_ms"] - p["start_ms"], p["native_ms"], (link - prev) / 1e9))
        prev = link
    steady = steady[SKIP:]
    if not steady:
        return result | {"error": "no steady decode passes"}
    m = passes[-1]["metrics"]
    return result | {
        "tier2_gb": header["config"]["tier2_bytes"] / 1e9, "tier2_feasible": header["tier2_feasible"],
        "steady_passes": len(steady),
        "sim_obtained_ms": statistics.median(s[0] for s in steady),
        "sim_ideal_ms": statistics.median(s[1] for s in steady),
        "sim_fetch_gb_per_step": statistics.median(s[2] for s in steady),
        "expert_hit_rate": m["expert_hits"] / m["expert_lookups"] if m["expert_lookups"] else None,
        "peak_tier1_gb": m["peak_tier1_bytes"] / 1e9,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--figure", nargs="*")
    parser.add_argument("--only", nargs="*", help="point names, e.g. bw-1m-l1_96-bw_1")
    parser.add_argument("--expert-overlap", type=float, default=BASE_TWO_TIER["expert_overlap"],
                        help="share of a token's experts kept from its previous step (synthetic routing)")
    parser.add_argument("--jobs", type=int, default=16)
    parser.add_argument("--out", type=Path, default=HERE / "output" / "curves")
    args = parser.parse_args()
    points = [p for p in csv.DictReader(TARGETS.open()) if not args.figure or p["figure"] in args.figure]
    if args.only:
        points = [p for p in points if f"{p['figure']}-l1_{p['l1_gb']}-bw_{p['l2_bw_tbps']}" in args.only]
    out = args.out.resolve()
    with ThreadPoolExecutor(args.jobs) as pool:
        results = list(pool.map(lambda p: run(out, p, args.expert_overlap), points))
    failed = False
    print(f"{'point':28s} {'ideal sim/slide':>16s} {'obtained sim/slide':>19s} {'overlap slide':>13s} {'fetch GB/step':>13s} {'hit':>5s}")
    for r in results:
        if "error" in r:
            failed = True
            print(f"{r['name']:28s} failed: {r['error']}")
            continue
        failed |= not r["tier2_feasible"]
        print(f"{r['name']:28s} {r['sim_ideal_ms']:7.1f}/{float(r['ideal_tpot_ms']):<7.1f} {r['sim_obtained_ms']:9.1f}/{float(r['obtained_tpot_ms']):<8.1f}"
              f" {r['overlap_tpot_ms'] or '-':>13s} {r['sim_fetch_gb_per_step']:13.1f} {r['expert_hit_rate']:5.0%}")
    aisim = subprocess.run(["git", "-C", str(AISIM), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps({"aisim": aisim, "expert_overlap": args.expert_overlap, "results": results}, indent=1))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
