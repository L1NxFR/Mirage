"""Sweep `kv_cache.two_tier_dram` on AISim's engine and render one page with a control per parameter.

    python3 src/two-tier-dram-engine/sweep.py [--out DIR] [--jobs N] [--limit N] [--publish PATH]

Points:
- the core grid: every combination of the CORE axes (workload, tier-1 size, tier-2 bandwidth,
  non-expert weight placement), the other parameters at their defaults;
- one-at-a-time: at each ANCHOR (every workload x the two EXI tier-1 layouts), each other
  parameter's levels with the rest at defaults.
Each workload also runs once without `two_tier_dram` for AISim's native timeline.

Every point is a real `aisim predict --stack engine` run (scenarios.run_aisim). A point's result is
cached in DIR/points/<id>.json, so a rerun only runs missing points. Cross-point checks run before
the page is written; a failure prints MISMATCH, exits 1 and writes no page.
"""

from __future__ import annotations

import argparse
import base64
import copy
import gzip
import hashlib
import itertools
import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from scenarios import AISIM, BASE_TWO_TIER, run_aisim  # noqa: E402

TEMPLATE = HERE / "sweep.html"
BEIJING = timezone(timedelta(hours=8))

# Every parameter the page shows. `levels` are the swept values, `default` is the EXI figure
# configuration (scenarios.BASE_TWO_TIER). `role`: core axes are crossed with each other;
# one-at-a-time axes vary alone around an anchor; fixed ones are shown but not swept.
AXES = [
    # Workload: four requests, up to 4 sequences in a batch.
    {"key": "arrival", "group": "workload", "role": "core", "levels": ["staggered", "together"], "default": "staggered",
     "label": "到达方式", "help": "staggered：每 50 ms 到一个，每个 pass 最多一个 prefill；together：同时到达，一个 pass 做完 4 个 prefill。"},
    {"key": "prompt", "group": "workload", "role": "core", "levels": [4096, 16384, 32768], "default": 16384,
     "label": "输入长度", "unit": "token"},
    {"key": "output", "group": "workload", "role": "core", "levels": [8, 64], "default": 8,
     "label": "输出长度", "unit": "token", "help": "64 时 decode 占比大，能看出一级容量对 decode 的影响。"},
    # Capacity and bandwidth.
    {"key": "tier1_gb", "group": "memory", "role": "core", "levels": [24, 36, 48, 64, 96, 128], "default": 36,
     "label": "一级容量", "unit": "GB", "help": "EXI 图示 36 GB；研究记录的探索方案 96 GB。"},
    {"key": "base_weights", "group": "memory", "role": "core", "levels": ["layer_prefetch", "resident"], "default": "layer_prefetch",
     "label": "非专家权重", "help": "32 GB 非专家权重常驻一级（resident），或逐层从二级轮换（layer_prefetch）。"},
    {"key": "tier2_bandwidth_gbps", "group": "memory", "role": "core", "levels": [1100, 2200, 4400], "default": 2200,
     "label": "二级标称带宽", "unit": "GB/s", "help": "LPDDR6 架构表 1.1–2.2 TB/s；4.4 TB/s 为外推。"},
    {"key": "copy_efficiency", "group": "memory", "role": "oat", "levels": [0.5, 0.7, 1.0], "default": 1.0,
     "label": "复制效率", "help": "有效复制带宽 = 标称带宽 × 复制效率；引擎只看乘积。"},
    {"key": "scratch_gb", "group": "memory", "role": "oat", "levels": [2, 4, 8], "default": 4,
     "label": "scratch", "unit": "GB", "help": "一级中留给激活等的空间。"},
    {"key": "tier2_gb", "group": "memory", "role": "oat", "levels": [128, 1024], "default": 128,
     "label": "二级容量", "unit": "GB", "help": "128 GB 放不下 805.7 GB 权重，结果标为不可行；1024 GB 可行。"},
    # Link.
    {"key": "link_overhead_ms", "group": "link", "role": "oat", "levels": [0.0, 0.001, 0.01, 0.1], "default": 0.0,
     "label": "每次传输开销", "unit": "ms"},
    {"key": "link_policy", "group": "link", "role": "oat", "levels": ["demand_first", "fifo"], "default": "demand_first",
     "label": "链路策略", "help": "demand_first：按需传输抢占预取；fifo：按入队顺序。"},
    # Experts.
    {"key": "expert_cache_gb", "group": "experts", "role": "oat", "levels": [None, 4, 16], "default": None,
     "label": "专家缓存上限", "unit": "GB", "help": "不设（自动）时用一级剩余空间。"},
    {"key": "expert_overlap", "group": "experts", "role": "oat", "levels": [0.0, 0.25, 0.5, 0.75, 1.0], "default": 0.5,
     "label": "专家跨步重合度", "help": "合成路由：一个 token 本步专家与上一步相同的比例。"},
    {"key": "expert_prefetch", "group": "experts", "role": "oat", "levels": ["none", "last_step"], "default": "none",
     "label": "专家预取", "help": "last_step：按上一步的专家预取，只用空闲位置。"},
    # Top-k KV.
    {"key": "hot_kv_entries", "group": "kv", "role": "oat", "levels": [0, 16384, 65536, 262144], "default": 65536,
     "label": "热 KV 条数", "help": "一级中 top-k KV 缓存的条目数。"},
    {"key": "topk_overlap", "group": "kv", "role": "oat", "levels": [0.0, 0.5, 0.75, 0.95], "default": 0.75,
     "label": "top-k 跨步重合度", "help": "合成选择：本步 top-k 与上一步相同的比例。"},
    # Model.
    {"key": "seed", "group": "model", "role": "oat", "levels": [0, 1, 2], "default": 0,
     "label": "随机种子", "help": "合成路由与 top-k 的种子；看结果对随机性的敏感度。"},
    {"key": "profile_context_tokens", "group": "model", "role": "oat", "levels": [16384, 65536], "default": 65536,
     "label": "profile 上下文", "unit": "token", "help": "测 attention／MoE 时间比例时用的上下文长度。"},
]
FIXED = [
    {"label": "模型", "value": "deepseek-ai/DeepSeek-V4-Pro（w4a8 专家，805.7 GB）"},
    {"label": "算力", "value": "hardware exi_3ddram，AISim op-level SOL（一级 18 TB/s）"},
    {"label": "后端", "value": "vLLM 0.30.0，TP1，max_sequences 4"},
    {"label": "tier2_capacity_check", "value": "counterfactual：二级放不下时照常运行，结果标为不可行"},
    {"label": "KV 容量", "value": "固定 40000 块（二级中的 KV）"},
]
WORKLOAD_KEYS = ("arrival", "prompt", "output")
CORE = [a for a in AXES if a["role"] == "core"]
OAT = [a for a in AXES if a["role"] == "oat"]
DEFAULTS = {a["key"]: a["default"] for a in AXES}
# One-at-a-time sweeps run around these core settings, for every workload.
ANCHORS = [{"tier1_gb": 36, "base_weights": "layer_prefetch", "tier2_bandwidth_gbps": 2200},
           {"tier1_gb": 96, "base_weights": "resident", "tier2_bandwidth_gbps": 2200}]
PHASES = ("attention", "moe", "tail", "wait_base", "wait_kv", "wait_experts")
LINK_KINDS = ("demand_base", "prefetch_base", "demand_expert", "prefetch_expert", "demand_kv", "prefill_kv", "writeback")


def workload_of(point: dict) -> dict:
    n, gap = point["prompt"], 50 if point["arrival"] == "staggered" else 0
    budget = n if point["arrival"] == "staggered" else 4 * n
    return {"requests": [(gap * i, n, point["output"]) for i in range(4)], "max_batched_tokens": budget, "max_sequences": 4}


def two_tier_of(point: dict, trace: Path) -> dict:
    cfg = {**copy.deepcopy(BASE_TWO_TIER), **{a["key"]: point[a["key"]] for a in AXES if a["key"] not in WORKLOAD_KEYS}}
    if cfg["expert_cache_gb"] is None:
        del cfg["expert_cache_gb"]
    return {**cfg, "trace_path": str(trace), "trace_passes": 1_000_000}


def point_id(point: dict) -> str:
    return hashlib.sha1(json.dumps([point[a["key"]] for a in AXES]).encode()).hexdigest()[:12]


def plan() -> list[dict]:
    points = {}
    for values in itertools.product(*[a["levels"] for a in CORE]):
        p = {**DEFAULTS, **dict(zip([a["key"] for a in CORE], values))}
        points[point_id(p)] = p
    for workload in itertools.product(*[next(a for a in CORE if a["key"] == k)["levels"] for k in WORKLOAD_KEYS]):
        for anchor in ANCHORS:
            base = {**DEFAULTS, **dict(zip(WORKLOAD_KEYS, workload)), **anchor}
            for axis in OAT:
                for level in axis["levels"]:
                    p = {**base, axis["key"]: level}
                    points[point_id(p)] = p
    return list(points.values())


def r4(x: float | None) -> float | None:
    """Four significant digits: enough for the page, a third of the bytes."""
    return None if x is None else float(f"{x:.4g}")


def compact_requests(result: dict) -> list[list]:
    return [[r4(r["arrival_time_ms"]), r4(r["first_admit_ms"]), r4(r["first_token_ms"]), r4(r["last_token_ms"])]
            for r in result["requests"]]


def per_layer(p: dict, layers: int) -> list[list]:
    rows = [[0.0] * len(PHASES) for _ in range(layers)]
    for c in p.get("compute", []):
        if c.get("layer") is not None and c["phase"] in PHASES:
            rows[c["layer"]][PHASES.index(c["phase"])] += c["t1"] - c["t0"]
    return [[r4(v) for v in row] for row in rows]


def compact_trace(path: Path) -> dict:
    """Per-pass totals from the cumulative metrics, per-layer phases for two passes, run totals."""
    header, passes = None, []
    with path.open() as f:
        for line in f:
            item = json.loads(line)
            if item["type"] == "header":
                header = item
            else:
                passes.append(item)
    layers = len(header["config"]["profile"]["layers"])
    strip, prev = [], {}
    for p in passes:
        m = p["metrics"]
        d = lambda k: m.get(k, 0.0) - prev.get(k, 0.0)  # noqa: E731
        link = sum(m["link_bytes"].values()) - sum(prev.get("link_bytes", {}).values())
        prefill = [r for r in p["requests"] if r["kind"] == "prefill"]
        strip.append([r4(p["start_ms"]), r4(p["end_ms"] - p["start_ms"]), r4(p["native_ms"]),
                      r4(d("wait_base_ms")), r4(d("wait_kv_ms")), r4(d("wait_experts_ms")),
                      len(prefill), len(p["requests"]) - len(prefill), sum(r.get("tokens", 0) for r in prefill), r4(link / 1e9)])
        prev = m
    decodes = [i for i, p in enumerate(passes) if p["requests"] and all(r["kind"] == "decode" for r in p["requests"])]
    # Steady decode: the last pass among those with the largest pure-decode batch.
    decode = max(decodes, key=lambda i: (len(passes[i]["requests"]), i)) if decodes else None
    local = {"prefill": {"pass": 0, "layers": per_layer(passes[0], layers)}}
    if decode is not None:
        local["decode"] = {"pass": decode, "layers": per_layer(passes[decode], layers)}
    last = passes[-1]["metrics"]
    tier1_bw = header["config"]["profile"]["source"].get("tier1_bandwidth_bytes_per_s")
    link_total = sum(last["link_bytes"].values())
    return {
        "kinds": "".join("C" if layer["kind"] == "csa" else "H" for layer in header["config"]["profile"]["layers"]),
        "strip": strip, "local": local,
        "totals": {"link_gb": {k: r4(last["link_bytes"].get(k, 0.0) / 1e9) for k in LINK_KINDS},
                   "wait_ms": [r4(last.get(k, 0.0)) for k in ("wait_base_ms", "wait_kv_ms", "wait_experts_ms")],
                   "expert_hits": last.get("expert_hits"), "expert_lookups": last.get("expert_lookups"),
                   "kv_hits": last.get("kv_hits"), "kv_lookups": last.get("kv_lookups"),
                   "evicted_experts": last.get("evicted_experts"),
                   "peak_tier1_gb": r4(last.get("peak_tier1_bytes", 0.0) / 1e9),
                   "expert_room_gb": r4((header.get("expert_cache_bytes") or 0.0) / 1e9),
                   "tier2_feasible": header.get("tier2_feasible"),
                   "contention_ub_ms": r4(link_total / tier1_bw * 1e3) if tier1_bw else None},
    }


def failure_message(folder: Path) -> str:
    log = (folder / "run.log").read_text() if (folder / "run.log").exists() else ""
    lines = [x.strip() for x in log.splitlines() if "two_tier_dram" in x or "Error" in x]
    line = lines[-1] if lines else log.strip().splitlines()[-1] if log.strip() else "aisim failed"
    # Keep the engine's own reason, not the replay wrapper's prefix.
    return line[line.find("two_tier_dram:"):] if "two_tier_dram:" in line else line[-300:]


ATTEMPTS = 3


def run_with_retry(folder: Path, workload: dict, two_tier: dict | None) -> dict | str:
    """AISim's result, or the engine's `two_tier_dram:` rejection. Any other failure (a startup
    timeout under load, say) is retried, then raised: it says nothing about the configuration."""
    for attempt in range(ATTEMPTS):
        try:
            return run_aisim(folder, workload, two_tier)
        except SystemExit:
            reason = failure_message(folder)
            if reason.startswith("two_tier_dram:"):
                return reason
    raise RuntimeError(f"{folder.name}: aisim failed {ATTEMPTS} times: {reason}")


def aisim_commit() -> str:
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=AISIM, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=AISIM, capture_output=True, text=True).stdout.strip()
    return head + ("+dirty" if dirty else "")


AISIM_COMMIT = aisim_commit()


def run_point(out: Path, point: dict) -> dict:
    pid = point_id(point)
    cached = out / "points" / f"{pid}.json"
    if cached.exists():
        return json.loads(cached.read_text())
    folder = out / "runs" / pid
    trace = folder / "two-tier.jsonl"
    result = run_with_retry(folder, workload_of(point), two_tier_of(point, trace))
    if isinstance(result, str):
        record = {"id": pid, "aisim": AISIM_COMMIT, "point": point, "error": result}
    else:
        record = {"id": pid, "aisim": AISIM_COMMIT, "point": point, "requests": compact_requests(result), **compact_trace(trace)}
    shutil.rmtree(folder)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(record, separators=(",", ":")))
    return record


def run_native(out: Path, workload_point: dict) -> dict:
    key = "-".join(str(workload_point[k]) for k in WORKLOAD_KEYS)
    cached = out / "points" / f"native-{key}.json"
    if cached.exists():
        return json.loads(cached.read_text())
    folder = out / "runs" / f"native-{key}"
    result = run_with_retry(folder, workload_of(workload_point), None)
    if isinstance(result, str):
        raise RuntimeError(f"native-{key}: {result}")
    record = {"workload": key, "aisim": AISIM_COMMIT, "requests": compact_requests(result)}
    shutil.rmtree(folder)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(record, separators=(",", ":")))
    return record


def makespan(rec: dict) -> float:
    return max(r[3] for r in rec["requests"])


def wkey(point: dict) -> str:
    return "-".join(str(point[k]) for k in WORKLOAD_KEYS)


def checks(records: list[dict], natives: dict[str, dict]) -> list[tuple[str, bool, str]]:
    ok = {json.dumps([r["point"][a["key"]] for a in AXES]): r for r in records if "error" not in r}
    find = lambda p: ok.get(json.dumps([p[a["key"]] for a in AXES]))  # noqa: E731
    results = []

    # Run-to-run noise of AISim's default `determinism: random` is about 1e-4; allow 0.5%.
    slower = [r for r in records if "error" not in r and makespan(r) < makespan(natives[wkey(r["point"])]) * 0.995]
    results.append(("两级完成时间不早于 AISim 原生", not slower, f"{len(slower)} 个点更早"))

    pairs, bad = 0, []
    for r in ok.values():
        p = r["point"]
        if p["copy_efficiency"] == 0.5 and p["tier2_bandwidth_gbps"] == 2200:
            twin = find({**p, "copy_efficiency": 1.0, "tier2_bandwidth_gbps": 1100})
            if twin:
                pairs += 1
                if abs(makespan(r) - makespan(twin)) > 0.005 * makespan(twin):
                    bad.append(r["id"])
    results.append(("2.2 TB/s × 0.5 与 1.1 TB/s × 1.0 结果一致（引擎只看乘积）", pairs > 0 and not bad, f"{pairs} 对，{len(bad)} 对不一致"))

    pairs, bad = 0, []
    for r in ok.values():
        p = r["point"]
        if p["tier2_bandwidth_gbps"] == 1100:
            faster = find({**p, "tier2_bandwidth_gbps": 4400})
            if faster:
                pairs += 1
                if makespan(faster) > makespan(r) * 1.005:
                    bad.append(r["id"])
    results.append(("二级带宽 4.4 TB/s 不比 1.1 TB/s 慢", pairs > 0 and not bad, f"{pairs} 对，{len(bad)} 对变慢"))

    pairs, bad = 0, []
    for r in ok.values():
        p = r["point"]
        if p["tier2_gb"] == 1024:
            base = find({**p, "tier2_gb": 128})
            if base:
                pairs += 1
                if not (r["totals"]["tier2_feasible"] is True and base["totals"]["tier2_feasible"] is False
                        and abs(makespan(r) - makespan(base)) <= 0.005 * makespan(base)):
                    bad.append(r["id"])
    results.append(("二级 1024 GB 可行、128 GB 不可行，时间相同（容量只影响可行性）", pairs > 0 and not bad, f"{pairs} 对，{len(bad)} 对不符"))

    pairs, bad = 0, []
    for r in ok.values():
        p = r["point"]
        if p["link_overhead_ms"] == 0.1:
            base = find({**p, "link_overhead_ms": 0.0})
            if base:
                pairs += 1
                if makespan(r) < makespan(base) * 0.995:
                    bad.append(r["id"])
    results.append(("每次传输 0.1 ms 开销不比 0 快", pairs > 0 and not bad, f"{pairs} 对，{len(bad)} 对更快"))

    resident_small = [r for r in records if r["point"]["base_weights"] == "resident" and r["point"]["tier1_gb"] <= 36]
    results.append(("一级 ≤ 36 GB 时非专家权重常驻被拒绝（32 GB + scratch 放不下）",
                    bool(resident_small) and all("error" in r for r in resident_small),
                    f"{sum('error' in r for r in resident_small)}/{len(resident_small)} 被拒绝"))
    return results


def write_page(records: list[dict], natives: dict[str, dict], check_results: list, out: Path) -> None:
    # Layer kinds are the model's, the same in every run: keep one copy.
    kinds = next((r["kinds"] for r in records if "kinds" in r), None)
    # The AISim commit each run used, recorded when it ran.
    commits = sorted({r.get("aisim", "unknown") for r in [*records, *natives.values()]})
    records = [{k: v for k, v in r.items() if k not in ("kinds", "aisim")} for r in records]
    natives = {k: {f: v for f, v in r.items() if f != "aisim"} for k, r in natives.items()}
    data = {
        "kinds": kinds, "axes": AXES, "fixed": FIXED, "anchors": ANCHORS, "phases": PHASES, "link_kinds": LINK_KINDS,
        "points": records, "natives": natives,
        "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in check_results],
        "meta": {"aisim": "、".join(commits), "generated": datetime.now(BEIJING).isoformat(timespec="seconds"),
                 "runs": len(records) + len(natives)},
    }
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    packed = base64.b64encode(gzip.compress(raw, 9, mtime=0)).decode()
    out.write_text(TEMPLATE.read_text().replace("__DATA_GZ_B64__", packed))
    print(f"data {len(raw) / 1e6:.1f} MB -> gzip+base64 {len(packed) / 1e6:.2f} MB")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=HERE / "output" / "sweep")
    parser.add_argument("--jobs", type=int, default=32)
    parser.add_argument("--limit", type=int, help="run only the first N points (smoke test)")
    parser.add_argument("--publish", type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    points = plan()[: args.limit] if args.limit else plan()
    workloads = {wkey(p): p for p in points}
    print(f"{len(points)} points, {len(workloads)} native runs, {args.jobs} jobs")
    records, natives = [], {}
    with ThreadPoolExecutor(args.jobs) as pool:
        native_futures = {pool.submit(run_native, out, p): k for k, p in workloads.items()}
        futures = [pool.submit(run_point, out, p) for p in points]
        for i, f in enumerate(as_completed(futures), 1):
            records.append(f.result())
            if i % 50 == 0 or i == len(futures):
                print(f"  {i}/{len(futures)} points ({sum('error' in r for r in records)} rejected)", flush=True)
        for f, k in native_futures.items():
            natives[k] = f.result()
    records.sort(key=lambda r: [str(r["point"][a["key"]]) for a in AXES])
    check_results = checks(records, natives)
    failed = False
    for name, ok, detail in check_results:
        failed |= not ok
        print(f"check: {name}: {'OK' if ok else 'MISMATCH'} ({detail})")
    if failed:
        return 1
    page = out / "two-tier-dram-sweep.html"
    write_page(records, natives, check_results, page)
    print(f"wrote {page} ({page.stat().st_size / 1e6:.2f} MB)")
    if args.publish:
        args.publish.write_bytes(page.read_bytes())
        print(f"published {args.publish}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
