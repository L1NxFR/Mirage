"""Experiment catalog: real `aisim predict --stack two_tier_dram` runs, logic checks, a sweep table and a replay page.

    python3 src/two-tier-dram/scenarios.py [--out DIR] [--only NAME ...] [--publish PATH]

Featured runs keep the full event trace and become animated tabs. Sweep runs
keep per-step statistics only and become rows of output/sweep.md. Every run is
one AISim prediction: AISim loads the trace, schedules the request and prices
each pass; the two_tier_dram stack re-times the decode steps per layer.

The checks below assert only logic that must hold whatever the conclusions are
(higher bandwidth is never slower, the legacy configuration reproduces its
old numbers, infeasible configurations are reported as such). They do not
assert the conclusions themselves.
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

CONTEXT_TOKENS = 200_000
OFFICIAL, FP8 = "deepseek-ai/DeepSeek-V4-Pro", "sgl-project/DeepSeek-V4-Pro-FP8"
COMPUTE = {
    "exi_sol": {"hardware": "exi_3ddram", "backend_version": "0.30.0",
                "systems_paths": [str(HERE / "systems"), "default"]},
    "b200": {"hardware": "b200_sxm"},
}
BASIS_LABEL = {"exi_sol": "EXI-SOL (uncalibrated AISim analytical roofline)", "b200": "B200 compute baseline with an assumed two-tier memory system (hybrid experiment)"}

# Policies per tier-1 configuration. 36 GB cannot hold the 32 GB of non-expert weights next to scratch,
# so the figure configuration has to rotate them layer by layer; 96 GB keeps them resident.
CAP36 = {"hardware": "exi_figure", "base_weights": "layer_rotation", "tier2_capacity_check": "counterfactual"}
CAP96 = {"hardware": "exi_96gb_explore", "base_weights": "resident", "tier2_capacity_check": "counterfactual"}
LEGACY = {"hardware": "legacy_64gbps", "base_weights": "resident"}
LEGACY_OLD_TOKEN_MS = [385.477123, 202.595547, 184.014651]  # commit e86bfad, 3 steps


def run_spec(name, title, two_tier, compute="exi_sol", model=OFFICIAL, steps=32, featured=False, summary=""):
    return {"name": name, "title": title, "two_tier": two_tier, "compute": compute, "model": model,
            "steps": steps, "featured": featured, "summary": summary}


def catalog() -> list[dict]:
    runs = [
        run_spec("exi36", "EXI reference, 36 GB at an ideal 2.2 TB/s", CAP36, steps=16, featured=True,
                 summary="The EXI-3DDRAM reference specifies a 36 GB tier 1. This run uses the upper LPDDR6 bandwidth of 2.2 TB/s without transfer losses or fixed overhead. "
                         "The 32 GB of non-expert weights cannot stay resident and rotate by layer. Routed experts use a cross-step LRU cache."),
        run_spec("exi96", "Design study, 96 GB at an ideal 2.2 TB/s", CAP96, steps=16, featured=True,
                 summary="The design study increases tier 1 to 96 GB and keeps the other EXI parameters. Non-expert weights stay resident and experts use a cross-step LRU cache."),
        run_spec("hybrid36", "Hybrid B200 compute with 36 GB EXI memory", CAP36, compute="b200", steps=8, featured=True,
                 summary="This sensitivity run combines AISim compute times for b200_sxm with the EXI memory configuration to isolate the effect of the compute baseline."),
        run_spec("legacy", "Legacy comparison at 64 GB/s (withdrawn assumption)", LEGACY, compute="b200", model=FP8, steps=8, featured=True,
                 summary="Commit e86bfad used an FP8 model, B200 compute, a 96 GB tier 1, an assumed 2048 GB tier 2, 64 GB/s bandwidth, and 10 µs per transfer. This run reproduces that baseline."),
    ]
    for cap, base in (("36", CAP36), ("96", CAP96)):
        runs += [
            run_spec(f"bw{cap}-2.2", f"{cap} GB at an ideal 2.2 TB/s", base),
            run_spec(f"bw{cap}-1.1", f"{cap} GB at an ideal 1.1 TB/s", {**base, "tier2_bandwidth": "1.1 TB/s"}),
            run_spec(f"bw{cap}-2.2x0.7", f"{cap} GB at 2.2 TB/s with 70% assumed efficiency", {**base, "copy_efficiency": 0.7}),
            run_spec(f"bw{cap}-1.1x0.7", f"{cap} GB at 1.1 TB/s with 70% assumed efficiency", {**base, "tier2_bandwidth": "1.1 TB/s", "copy_efficiency": 0.7}),
            run_spec(f"bw{cap}-64g", f"{cap} GB at the legacy bandwidth of 64 GB/s", {**base, "tier2_bandwidth": "64 GB/s"}),
            run_spec(f"bw{cap}-fast", f"{cap} GB with a 1 PB/s link (native latency check)", {**base, "tier2_bandwidth": "1 PB/s"}),
        ]
        runs += [run_spec(f"oh{cap}-{t.replace(' ', '')}", f"{cap} GB with {t} assumed overhead per transfer", {**base, "transfer_overhead": t})
                 for t in ("1 us", "10 us", "100 us")]
        runs += [
            run_spec(f"pf{cap}", f"{cap} GB with expert prefetch based on the previous step", {**base, "expert_prefetch": "last_step"}),
            run_spec(f"pl{cap}", f"{cap} GB with per-layer expert release and no cross-step cache", {**base, "expert_cache": "per_layer"}),
            run_spec(f"plpf{cap}", f"{cap} GB with per-layer expert release and previous-step prefetch", {**base, "expert_cache": "per_layer", "expert_prefetch": "last_step"}),
            run_spec(f"kv{cap}", f"{cap} GB with hot top-k KV disabled", {**base, "hot_kv_entries": 0}),
            *[run_spec(f"ov{cap}-{o}", f"{cap} GB with expert overlap {o}", {**base, "expert_overlap": o}) for o in (0.25, 0.75, 0.9)],
            run_spec(f"b200{cap}", f"{cap} GB with B200 compute (hybrid)", base, compute="b200"),
        ]
    runs += [
        run_spec("enforce36", "36 GB with enforced tier 2 capacity", {**CAP36, "tier2_capacity_check": "enforce"}, steps=2),
        run_spec("resident36", "36 GB with resident non-expert weights", {**CAP36, "base_weights": "resident"}, steps=2),
    ]
    return runs


def run(spec: dict, out: Path) -> dict:
    folder = out / spec["name"]
    folder.mkdir(parents=True, exist_ok=True)
    trace_file = folder / "requests.mooncake.jsonl"
    trace_file.write_text(json.dumps({"request_id": "R1", "timestamp": 0, "input_length": CONTEXT_TOKENS,
                                      "output_length": spec["steps"] + 1, "hash_ids": [1]}) + "\n")
    compute = COMPUTE[spec["compute"]]
    perf = {"estimation_mode": "op_level", "database_mode": "SOL"}
    if "systems_paths" in compute:
        perf["systems_paths"] = compute["systems_paths"]
    engine = {"mode": "aggregated", "model": spec["model"], "hardware": compute["hardware"], "backend": "vllm",
              "context_length": 262144, "ais_perf_model": perf,
              "workers": {"aggregated": {"parallelism": {"replicas": 1, "tensor": 1, "attention_data": 1},
                                         # weights exceed one device; a fixed KV capacity keeps AISim's single-tier memory check out of the way
                                         "kv_cache": {"capacity": {"type": "fixed", "blocks": 40000}}}}}
    if "backend_version" in compute:
        engine["backend_version"] = compute["backend_version"]
    two_tier = {**spec["two_tier"], "max_decode_steps": spec["steps"], "trace_dir": str(folder),
                "trace_detail": "full" if spec["featured"] else "summary"}
    config = {"traffic": {"source": {"type": "trace", "format": "mooncake", "block_size": 262144, "paths": [str(trace_file)]},
                          "load": {"type": "trace_timestamps"}},
              "engine": engine, "two_tier_dram": two_tier}
    (folder / "config.json").write_text(json.dumps(config, indent=1))  # JSON is valid YAML
    (folder / "trace.json").unlink(missing_ok=True)
    proc = subprocess.run([str(CLI), "predict", "--stack", "two_tier_dram", "--config", str(folder / "config.json"),
                           "--output-dir", str(folder / "aisim"), "--overwrite"], cwd=AISIM, capture_output=True, text=True)
    (folder / "run.log").write_text(proc.stdout + proc.stderr)
    if not (folder / "trace.json").exists():
        raise SystemExit(f"{spec['name']}: aisim produced no trace (exit {proc.returncode}); see {folder / 'run.log'}")
    return json.loads((folder / "trace.json").read_text())


def row(spec: dict, trace: dict) -> dict:
    """One sweep row: what a reader needs to compare runs, all from the trace."""
    r = trace["requests"][0]
    m, steps = r["metrics"], r["per_step"]
    cfg = TwoTierConfig.from_mapping(spec["two_tier"])
    hw = cfg.hardware
    steady = m["steady"]
    # Statistics window: the steady window if one was found; otherwise every step after the cold step and the
    # filling phase (the reader sees it is not steady), or the last 6 steps if the cache never filled.
    settled = [s for s in steps if s["phase"] in ("evicting", "no_cache")]
    tail = ([s for s in steps if s["step"] >= steady["from_step"]] if steady.get("reached")
            else settled if len(settled) >= 6 else steps[-6:])
    times = [s["token_ms"] for s in tail]
    per_token = lambda key: sum(s[key] for s in tail) / len(tail) if tail else None  # noqa: E731
    moved = per_token("link_total_bytes")
    return {
        "name": spec["name"], "title": spec["title"], "basis": spec["compute"], "model": spec["model"],
        "hardware_preset": hw.preset, "tail_spread": (max(times) - min(times)) / (sum(times) / len(times)) if times else None,
        "tail_phase": tail[0]["phase"] if tail else None,
        "expert_prefetched": m["expert_prefetched"], "expert_prefetch_used": m["expert_prefetch_used"],
        "feasible": r["feasible"], "error": r["error"], "infeasible": r["infeasible"],
        "basis_consistent": r["compute_basis"]["consistent"], "steps": len(m["token_ms"]),
        "cold_ms": m["token_ms"][0] if m["token_ms"] else None,
        "steady": steady, "tail_from": tail[0]["step"] if tail else None,
        "tail_token_ms": per_token("token_ms"), "tail_compute_ms": per_token("compute_ms"),
        "tail_wait_base_ms": per_token("wait_base_ms"), "tail_wait_experts_ms": per_token("wait_experts_ms"),
        "tail_wait_kv_ms": per_token("wait_kv_ms"), "tail_bytes": moved,
        "tail_bytes_over_bw_ms": moved / hw.copy_bandwidth * 1e3 if moved is not None else None,
        "tail_link_util": per_token("link_utilization"),
        "tail_expert_hit_rate": (sum(s["expert_hits"] for s in tail) / max(sum(s["expert_lookups"] for s in tail), 1)) if tail else None,
        "tail_kv_hit_rate": per_token("kv_hit_rate") if tail and all(s["kv_hit_rate"] is not None for s in tail) else None,
        "evicted_experts": m["evicted_experts"], "released_experts": m["released_experts"],
        "cache_slots": m["expert_cache_slots"], "peak_tier1_gb": m["peak_tier1_bytes"] / 1e9,
        "native_ms": m["native_token_ms"], "contention_bound_ms_per_token": m["tier1_contention_bound_ms"] / max(len(m["token_ms"]), 1),
        "copy_bw_tbs": hw.copy_bandwidth / 1e12, "overhead_us": hw.transfer_overhead * 1e6,
        "token_ms": m["token_ms"], "phases": [s["phase"] for s in steps],
    }


CHECKS = [
    ("The first three legacy steps reproduce e86bfad", lambda R: R["legacy"]["token_ms"][:3] == LEGACY_OLD_TOKEN_MS),
    ("Enforcing tier 2 capacity identifies an infeasible single-device configuration", lambda R: R["enforce36"]["error"] and "infeasible on a single device" in R["enforce36"]["error"]),
    ("The 36 GB configuration cannot keep all non-expert weights resident", lambda R: R["resident36"]["error"] and "Tier 1 DRAM" in R["resident36"]["error"]),
    ("The EXI-SOL compute baseline matches the memory configuration and the B200 run is marked as hybrid",
     lambda R: all(r["basis_consistent"] == (r["basis"] == "exi_sol") for r in R.values() if r["error"] is None
                   and r["name"] not in ("legacy",))),
    *[(f"At {c} GB, increasing link bandwidth does not increase latency", lambda R, c=c: R[f"bw{c}-2.2"]["tail_token_ms"] <= R[f"bw{c}-1.1"]["tail_token_ms"]
       <= R[f"bw{c}-1.1x0.7"]["tail_token_ms"] <= R[f"bw{c}-64g"]["tail_token_ms"]
       and R[f"bw{c}-2.2"]["tail_token_ms"] <= R[f"bw{c}-2.2x0.7"]["tail_token_ms"]) for c in ("36", "96")],
    *[(f"At {c} GB, increasing fixed overhead does not reduce latency", lambda R, c=c: R[f"bw{c}-2.2"]["tail_token_ms"] <= R[f"oh{c}-1us"]["tail_token_ms"]
       <= R[f"oh{c}-10us"]["tail_token_ms"] <= R[f"oh{c}-100us"]["tail_token_ms"]) for c in ("36", "96")],
    *[(f"At {c} GB, a 1 PB/s link reproduces native AISim latency within 1%",
       lambda R, c=c: all(abs(t / R[f"bw{c}-fast"]["native_ms"] - 1) <= 0.01 for t in R[f"bw{c}-fast"]["token_ms"]))
      for c in ("36", "96")],
    *[(f"At {c} GB, releasing experts after each layer yields no expert cache hits", lambda R, c=c: R[f"pl{c}"]["tail_expert_hit_rate"] == 0) for c in ("36", "96")],
    *[(f"At {c} GB, disabling hot KV yields no KV cache hits", lambda R, c=c: R[f"kv{c}"]["tail_kv_hit_rate"] == 0) for c in ("36", "96")],
]


def fmt(v, nd=2):
    return "—" if v is None else f"{v:.{nd}f}"


def sweep_markdown(rows: list[dict]) -> str:
    lines = ["| Run | Compute baseline | Feasible | Cold start (ms) | Steady state | Window mean (ms/token) | Compute (ms) | Weight wait (ms) | Expert wait (ms) | KV wait (ms) | Transfer (GB/token) | Bytes / bandwidth (ms) | Link utilization | Expert hit rate | Total evictions |",
             "| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for r in rows:
        if r["error"]:
            lines.append(f"| {r['title']} | {r['basis']} | No ({r['error']}) |" + " — |" * 12)
            continue
        st = r["steady"]
        steady = (f"From step {st['from_step']}" if st.get("reached")
                  else f"Not reached (steps {r['tail_from']}–{r['steps']}, variation {r['tail_spread']:.0%})")
        feasible = "Legacy assumption (hypothetical tier 2 capacity)" if r["hardware_preset"] == "legacy_64gbps" else "Yes" if r["feasible"] else "No (counterfactual)"
        lines.append(" | ".join([
            f"| {r['title']}", r["basis"], feasible, fmt(r["cold_ms"]), steady, fmt(r["tail_token_ms"]), fmt(r["tail_compute_ms"]),
            fmt(r["tail_wait_base_ms"]), fmt(r["tail_wait_experts_ms"]), fmt(r["tail_wait_kv_ms"]),
            fmt(r["tail_bytes"] / 1e9 if r["tail_bytes"] is not None else None), fmt(r["tail_bytes_over_bw_ms"]),
            f"{r['tail_link_util']:.0%}" if r["tail_link_util"] is not None else "—",
            f"{r['tail_expert_hit_rate']:.0%}" if r["tail_expert_hit_rate"] is not None else "—",
            f"{r['evicted_experts']} |"]))
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=HERE / "output")
    parser.add_argument("--only", nargs="*", help="run names")
    parser.add_argument("--publish", type=Path, help="also copy the replay page to this path")
    args = parser.parse_args()
    out = args.out.resolve()
    specs = [s for s in catalog() if not args.only or s["name"] in args.only]
    rows, items = {}, []
    for spec in specs:
        trace = run(spec, out)
        rows[spec["name"]] = row(spec, trace)
        r = rows[spec["name"]]
        print(f"{spec['name']}: " + (f"error: {r['error']}" if r["error"] else
              f"cold {r['cold_ms']:.2f} ms, window {r['tail_token_ms']:.3f} ms/token, steady={r['steady'].get('reached')}"))
        if spec["featured"]:
            items.append({"title": spec["title"], "summary": spec["summary"], "basis": BASIS_LABEL[spec["compute"]],
                          "changes": [], "trace": trace})
    (out / "sweep.json").write_text(json.dumps(list(rows.values()), ensure_ascii=False, indent=1))
    (out / "sweep.md").write_text(sweep_markdown(list(rows.values())))
    failed = False
    if not args.only:
        for name, holds in CHECKS:
            try:
                ok = bool(holds(rows))
            except (KeyError, TypeError) as error:
                ok, name = False, f"{name} ({error!r})"
            failed |= not ok
            print(f"check: {name}: " + ("OK" if ok else "MISMATCH"))
    if items:
        page = out / "two-tier-dram-replay.html"
        write_replay(items, page, sweep=list(rows.values()))
        print(f"wrote {page}")
        if args.publish:
            args.publish.write_bytes(page.read_bytes())
            print(f"published {args.publish}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
