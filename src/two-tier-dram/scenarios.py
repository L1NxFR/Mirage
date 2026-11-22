"""Scenario catalog for the two-tier DRAM decode model: run, check, and render the replay.

    python3 src/two-tier-dram/scenarios.py [--out DIR] [--only SLUG ...]

Each scenario overrides a few `Config` fields. After the run, the observable
results are compared with `expect`; any mismatch prints MISMATCH and exits 1.
Outputs: DIR/<slug>/trace.json (config, metrics, events, snapshots, segments)
and DIR/two-tier-dram-replay.html (self-contained animated page).
"""

from __future__ import annotations

import argparse
import json
from dataclasses import fields
from pathlib import Path

from model import Config, simulate

HERE = Path(__file__).resolve().parent
BASE = Config()

SCENARIOS = [
    {
        "slug": "prefetch-hot-kv", "title": "基线：逐层预取 + 热 KV 缓存",
        "summary": "方案 A。每层计算时预取下一层的权重与 indexer KV；取入的 attention KV 留在一级，供后续 step 复用。",
        "finding": "第 1 个 step 冷启动：第 0 层权重按需取入，top-k 全部缺失，29.25 ms。之后预取都在当前层结束前到达，top-k 约 75% 命中，每 token 约 25 ms，接近纯计算的 24 ms。",
        "overrides": {},
        "expect": {"token_ms": [29.25, 25.225, 24.975], "kv_hit_rate": 0.5, "prefetch_late": 0, "wait_weights_ms": 2.45, "wait_kv_ms": 5.0},
    },
    {
        "slug": "on-demand", "title": "对照：全部按需搬运",
        "summary": "关闭预取和热 KV 缓存。每层开始时才取权重，每步都重新取 top-k KV。相当于把“卸载”直接搬到逐层粒度。",
        "finding": "每层都要等权重 2.45 ms、等 KV 0.7 ms，每 token 36.6 ms，比纯计算多 52%。链路搬运 108 MB 权重，全部在关键路径上。",
        "overrides": {"prefetch": False, "hot_kv_entries": 0},
        "expect": {"token_ms": [36.6, 36.6, 36.6], "kv_hit_rate": 0.0, "wait_weights_ms": 29.4, "wait_kv_ms": 8.4},
    },
    {
        "slug": "prefetch-only", "title": "对照：只开预取",
        "summary": "逐层预取，但取入的 KV 用完即丢。",
        "finding": "权重等待只剩冷启动的一次；KV 每层仍等 0.7 ms，每 token 26.8 ms。预取隐藏了权重搬运，KV 缺失成为剩余的等待。",
        "overrides": {"hot_kv_entries": 0},
        "expect": {"token_ms": [29.25, 26.8, 26.8], "kv_hit_rate": 0.0, "wait_weights_ms": 2.45, "wait_kv_ms": 8.4},
    },
    {
        "slug": "hot-kv-only", "title": "对照：只开热 KV 缓存",
        "summary": "保留热 KV 缓存，不预取权重。",
        "finding": "命中率 50%（冷启动 step 为 0，之后约 75%），KV 等待从 8.4 降到 5.0 ms；但每层仍等权重，每 token 约 35 ms。在这组参数下，权重搬运是主要代价。",
        "overrides": {"prefetch": False},
        "expect": {"token_ms": [36.6, 35.025, 34.775], "kv_hit_rate": 0.5, "wait_weights_ms": 29.4, "wait_kv_ms": 5.0},
    },
    {
        "slug": "zero-overlap", "title": "极端：top-k 零重合",
        "summary": "每个 step 每层选出的 top-k 与之前完全不同（overlap = 0）。",
        "finding": "热 KV 缓存占着一级空间却没有一次命中，时延与“只开预取”相同（26.8 ms）。缓存收益完全取决于跨步重合度。",
        "overrides": {"overlap": 0.0},
        "expect": {"token_ms": [29.25, 26.8, 26.8], "kv_hit_rate": 0.0, "wait_kv_ms": 8.4},
    },
    {
        "slug": "lru-thrash", "title": "极端：热 KV 容量恰好一步工作集",
        "summary": "热 KV 软上限 16 条 = 4 层 × top-k 4，重合度仍是 0.75。",
        "finding": "命中率为 0：新 token 的脏 KV 也占名额，全局 LRU 淘汰的正好是最久未用、也就是下一步马上要用的那一层。容量等于一步工作集时，跨层 LRU 会抖动。",
        "overrides": {"hot_kv_entries": 16},
        "expect": {"token_ms": [29.25, 26.8, 26.8], "kv_hit_rate": 0.0, "wait_kv_ms": 8.4},
    },
    {
        "slug": "prefetch-crowds-kv", "title": "极端：预取缓冲挤占热 KV",
        "summary": "一级从 32 MB 缩到 28 MB，热 KV 软上限不变（24 条）。",
        "finding": "每层开始时预取缓冲先预留 9 MB，热 KV 只能在剩余空间里周转，旧条目在被复用前就因容量不足被淘汰，命中率 0。一级空间在预取缓冲与热 KV 之间是此消彼长的。",
        "overrides": {"tier1_mb": 28.0},
        "expect": {"token_ms": [29.25, 26.8, 26.8], "kv_hit_rate": 0.0, "prefetch_skipped": 0},
    },
    {
        "slug": "slow-link", "title": "极端：链路慢，预取来不及",
        "summary": "链路带宽 4 → 1 MB/ms：预取一层要 9.2 ms，超过一层的计算时间 6 ms。按需读取优先（demand_first）。",
        "finding": "11 次预取全部没有按时到达，计算每层都在等权重（共 44.4 ms）。按需取 KV 会抢占预取，KV 等待 16.7 ms。每 token 约 40 ms，仍明显好于同样链路下全部按需的 69.6 ms：预取虽然迟到，但已经提前搬了一部分。",
        "overrides": {"link_mb_per_ms": 1.0},
        "expect": {"token_ms": [51.6, 39.9, 41.6], "prefetch_late": 11, "wait_weights_ms": 44.4, "wait_kv_ms": 16.7},
    },
    {
        "slug": "slow-link-fifo", "title": "极端：同样慢的链路，改用 FIFO",
        "summary": "链路 1 MB/ms，传输按到达顺序排队，不抢占。",
        "finding": "按需取的 KV 排在预取后面：attention 等缺失 KV 的时间从 16.7 涨到 93.4 ms，每 token 50 ms 以上。预取与按需读取共用一条链路时，调度策略直接决定时延。",
        "overrides": {"link_mb_per_ms": 1.0, "link_policy": "fifo"},
        "expect": {"token_ms": [76.9, 53.8, 51.7], "prefetch_late": 2, "wait_weights_ms": 17.0, "wait_kv_ms": 93.4},
    },
    {
        "slug": "tier1-too-small", "title": "极端：一级放不下一层的工作集",
        "summary": "一级只有 22 MB：scratch 2 + 当前层 9 + 预取缓冲 9 之后只剩 2 MB。",
        "finding": "第 0 层勉强放下。到第 1 层取入 4 条 KV 时差 0.5 MB：第 0 层新 token 的脏 KV 还没写回（写回优先级最低，被预取抢占），不能淘汰，模型在 10.15 ms 报容量不足并停止。一级容量要按同一时刻各项之和的峰值检查，写回的优先级也会影响峰值。",
        "overrides": {"tier1_mb": 22.0},
        "expect": {"error": True},
    },
]

RELATIONS = [
    ("预取+热 KV 不慢于只开预取", lambda m: m["prefetch-hot-kv"]["decode_ms"] <= m["prefetch-only"]["decode_ms"]),
    ("只开预取快于全部按需", lambda m: m["prefetch-only"]["decode_ms"] < m["on-demand"]["decode_ms"]),
    ("只开热 KV 快于全部按需", lambda m: m["hot-kv-only"]["decode_ms"] < m["on-demand"]["decode_ms"]),
    ("零重合时没有命中", lambda m: m["zero-overlap"]["kv_hits"] == 0),
    ("FIFO 下 KV 等待长于按需优先", lambda m: m["slow-link-fifo"]["wait_kv_ms"] > m["slow-link"]["wait_kv_ms"]),
    ("关闭预取与缓存时每 token = 纯计算 + 每层两次按需搬运",
     lambda m: abs(m["on-demand"]["token_ms"][0] - (m["on-demand"]["compute_only_token_ms"]
               + BASE.layers * (2 * BASE.link_setup_ms + (BASE.bundle_mb + BASE.topk * BASE.kv_entry_mb) / BASE.link_mb_per_ms))) < 1e-6),
]


def changes(overrides: dict) -> list[dict]:
    return [{"param": k, "base": getattr(BASE, k), "value": v} for k, v in overrides.items()]


def check(scenario: dict, result: dict) -> list[str]:
    errors = []
    for key, want in scenario["expect"].items():
        got = bool(result["error"]) if key == "error" else result["metrics"][key]
        if got != want:
            errors.append(f"{key}: expected {want}, got {got}")
    if "error" not in scenario["expect"] and result["error"]:
        errors.append(f"unexpected error: {result['error']}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=HERE / "output")
    parser.add_argument("--only", nargs="*", help="scenario slugs to run")
    parser.add_argument("--publish", type=Path, help="also copy the page to this path")
    args = parser.parse_args()
    valid = {f.name for f in fields(Config)}
    chosen = [s for s in SCENARIOS if not args.only or s["slug"] in args.only]
    page, metrics, failed = [], {}, False
    for scenario in chosen:
        unknown = set(scenario["overrides"]) - valid
        if unknown:
            raise SystemExit(f"{scenario['slug']}: unknown Config fields {sorted(unknown)}")
        result = simulate(Config(**scenario["overrides"]))
        folder = args.out / scenario["slug"]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "trace.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
        errors = check(scenario, result)
        failed |= bool(errors)
        metrics[scenario["slug"]] = result["metrics"]
        print(f"{scenario['slug']}: " + ("OK" if not errors else "MISMATCH " + "; ".join(errors)))
        page.append({**{k: scenario[k] for k in ("slug", "title", "summary", "finding")},
                     "changes": changes(scenario["overrides"]), **result})
    if not args.only:
        for name, holds in RELATIONS:
            ok = holds(metrics)
            failed |= not ok
            print(f"relation: {name}: " + ("OK" if ok else "MISMATCH"))
    if failed:
        return 1
    html = (HERE / "template.html").read_text().replace("/*__DATA__*/null", json.dumps(page, ensure_ascii=False))
    out = args.out / "two-tier-dram-replay.html"
    out.write_text(html)
    print(f"wrote {out}")
    if args.publish:
        args.publish.write_text(html)
        print(f"published {args.publish}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
