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
BASIS_LABEL = {"exi_sol": "EXI-SOL（AISim 解析 roofline，未校准）", "b200": "B200 计算基线 + 假设两级内存（混合实验）"}

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
        run_spec("exi36", "EXI 图示 36 GB · 2.2 TB/s 理想", CAP36, steps=16, featured=True,
                 summary="EXI-3DDRAM 图示容量：一级 36 GB，二级 LPDDR6 取 2.2 TB/s 上端且无折损、无固定开销。"
                         "非专家权重 32 GB 放不下，必须逐层轮换；路由专家走跨步 LRU 缓存。"),
        run_spec("exi96", "设计文档 96 GB · 2.2 TB/s 理想", CAP96, steps=16, featured=True,
                 summary="原设计文档的 96 GB 一级方案（不是 EXI 图示配置），其余硬件同 EXI 图示。非专家权重常驻，专家走跨步 LRU 缓存。"),
        run_spec("hybrid36", "混合：B200 计算 + EXI 36 GB", CAP36, compute="b200", steps=8, featured=True,
                 summary="计算时间来自 AISim 的 b200_sxm，两级内存按 EXI 图示假设。用于说明计算基线的影响，不是 EXI 的预测。"),
        run_spec("legacy", "旧假设对照：64 GB/s（已撤回）", LEGACY, compute="b200", model=FP8, steps=8, featured=True,
                 summary="提交 e86bfad 的旧配置：FP8 模型、B200 计算、一级 96 GB、二级 2048 GB（虚构）、64 GB/s、10 µs。仅作历史对照。"),
    ]
    for cap, base in (("36", CAP36), ("96", CAP96)):
        runs += [
            run_spec(f"bw{cap}-2.2", f"{cap} GB · 2.2 TB/s 理想", base),
            run_spec(f"bw{cap}-1.1", f"{cap} GB · 1.1 TB/s 理想", {**base, "tier2_bandwidth": "1.1 TB/s"}),
            run_spec(f"bw{cap}-2.2x0.7", f"{cap} GB · 2.2 TB/s × 0.7（假设折损）", {**base, "copy_efficiency": 0.7}),
            run_spec(f"bw{cap}-1.1x0.7", f"{cap} GB · 1.1 TB/s × 0.7（假设折损）", {**base, "tier2_bandwidth": "1.1 TB/s", "copy_efficiency": 0.7}),
            run_spec(f"bw{cap}-64g", f"{cap} GB · 64 GB/s（旧假设带宽）", {**base, "tier2_bandwidth": "64 GB/s"}),
            run_spec(f"bw{cap}-fast", f"{cap} GB · 链路 1 PB/s（对账）", {**base, "tier2_bandwidth": "1 PB/s"}),
        ]
        runs += [run_spec(f"oh{cap}-{t.replace(' ', '')}", f"{cap} GB · 每次传输开销 {t}（假设）", {**base, "transfer_overhead": t})
                 for t in ("1 us", "10 us", "100 us")]
        runs += [
            run_spec(f"pf{cap}", f"{cap} GB · 按上一步路由预取专家", {**base, "expert_prefetch": "last_step"}),
            run_spec(f"pl{cap}", f"{cap} GB · 专家逐层释放（无跨步缓存）", {**base, "expert_cache": "per_layer"}),
            run_spec(f"plpf{cap}", f"{cap} GB · 专家逐层释放 + 按上一步路由预取", {**base, "expert_cache": "per_layer", "expert_prefetch": "last_step"}),
            run_spec(f"kv{cap}", f"{cap} GB · 关闭热 top-k KV", {**base, "hot_kv_entries": 0}),
            *[run_spec(f"ov{cap}-{o}", f"{cap} GB · 专家重合度 {o}", {**base, "expert_overlap": o}) for o in (0.25, 0.75, 0.9)],
            run_spec(f"b200{cap}", f"{cap} GB · B200 计算（混合）", base, compute="b200"),
        ]
    runs += [
        run_spec("enforce36", "36 GB · 二级容量强制检查", {**CAP36, "tier2_capacity_check": "enforce"}, steps=2),
        run_spec("resident36", "36 GB · 非专家权重常驻", {**CAP36, "base_weights": "resident"}, steps=2),
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
    ("旧配置的前 3 个 step 与 e86bfad 的结果一致", lambda R: R["legacy"]["token_ms"][:3] == LEGACY_OLD_TOKEN_MS),
    ("二级强制检查时报单卡不可行", lambda R: R["enforce36"]["error"] and "单卡不可行" in R["enforce36"]["error"]),
    ("36 GB 放不下常驻的非专家权重", lambda R: R["resident36"]["error"] and "一级 DRAM" in R["resident36"]["error"]),
    ("EXI-SOL 运行的计算基线与两级内存一致，B200 运行被标为混合",
     lambda R: all(r["basis_consistent"] == (r["basis"] == "exi_sol") for r in R.values() if r["error"] is None
                   and r["name"] not in ("legacy",))),
    *[(f"{c} GB：带宽越高不会越慢", lambda R, c=c: R[f"bw{c}-2.2"]["tail_token_ms"] <= R[f"bw{c}-1.1"]["tail_token_ms"]
       <= R[f"bw{c}-1.1x0.7"]["tail_token_ms"] <= R[f"bw{c}-64g"]["tail_token_ms"]
       and R[f"bw{c}-2.2"]["tail_token_ms"] <= R[f"bw{c}-2.2x0.7"]["tail_token_ms"]) for c in ("36", "96")],
    *[(f"{c} GB：固定开销越大不会越快", lambda R, c=c: R[f"bw{c}-2.2"]["tail_token_ms"] <= R[f"oh{c}-1us"]["tail_token_ms"]
       <= R[f"oh{c}-10us"]["tail_token_ms"] <= R[f"oh{c}-100us"]["tail_token_ms"]) for c in ("36", "96")],
    *[(f"{c} GB：链路 1 PB/s 时回到 AISim 原生时延（1% 内）",
       lambda R, c=c: all(abs(t / R[f"bw{c}-fast"]["native_ms"] - 1) <= 0.01 for t in R[f"bw{c}-fast"]["token_ms"]))
      for c in ("36", "96")],
    *[(f"{c} GB：专家逐层释放时没有专家命中", lambda R, c=c: R[f"pl{c}"]["tail_expert_hit_rate"] == 0) for c in ("36", "96")],
    *[(f"{c} GB：关闭热 KV 时没有 KV 命中", lambda R, c=c: R[f"kv{c}"]["tail_kv_hit_rate"] == 0) for c in ("36", "96")],
]


def fmt(v, nd=2):
    return "—" if v is None else f"{v:.{nd}f}"


def sweep_markdown(rows: list[dict]) -> str:
    lines = ["| 运行 | 计算基线 | 可行 | 冷启动 ms | 稳态 | 统计窗口 ms/token | 其中计算 | 等权重 | 等专家 | 等 KV | 搬运 GB/token | 字节/带宽 ms | 链路利用率 | 专家命中 | 累计淘汰 |",
             "| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for r in rows:
        if r["error"]:
            lines.append(f"| {r['title']} | {r['basis']} | 否：{r['error']} |" + " — |" * 12)
            continue
        st = r["steady"]
        steady = (f"自 step {st['from_step']}" if st.get("reached")
                  else f"未达到（step {r['tail_from']}–{r['steps']}，波动 {r['tail_spread']:.0%}）")
        feasible = "旧假设（二级容量虚构）" if r["hardware_preset"] == "legacy_64gbps" else "是" if r["feasible"] else "否（反事实）"
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
