"""Scenario catalog: generate AISim configs + mooncake traces, capture, and render.

Every scenario shares one tiny vLLM worker (block_size 4, 1 MB/block, fixed
timing) and differs only in the fields it overrides. Run with any Python 3:

    python3 src/kv-trace/scenarios.py [--out DIR] [--only SLUG ...]
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
VENV_PY = AISIM / "python/aisim/.venv/bin/python"
TINY_MODEL = AISIM / "tests/e2e/configs/unified_cli/fixtures/tiny-model"

BASE_KV = {
    "block_size": 4,
    "prefix_caching": True,
    "bytes_per_token": 250000,  # 4 tokens x 250 KB = 1 MB per block
    "capacity": {"type": "fixed", "blocks": 3},
    "host_offload": {
        "scope": "dp_rank_local",
        "num_host_blocks": 8,
        "d2h_bandwidth_gbps": 1,
        "h2d_bandwidth_gbps": 1,
        "latency_to_first_byte_ms": 0,
    },
}
BASE_SCHED = {"max_batched_tokens": 16, "max_sequences": 1}

# Request = (arrival ms, input tokens, block hash ids). Output is one token.
# R3 is R1's next turn: R1's 9 prompt tokens + its 1 output token + 2 new user
# tokens = 12. It shares R1's two full blocks [1, 2]; its third block holds R1's
# last prompt token plus new tokens, so it gets a new id (30). R2 is an unrelated
# request that pushes R1's prefix out of G1 in between.
PARENT_CHILD = [(0, 9, [1, 2, 3]), (100, 9, [11, 12, 13]), (200, 12, [1, 2, 30]), (300, 9, [21, 22, 23])]

SCENARIOS = [
    {
        "slug": "baseline", "title": "Baseline",
        "summary": "R2 evicts R1's prefix from G1. R3 continues R1 with nine original prompt tokens, one output token, and two new tokens. It restores the first two blocks from G2.",
        "finding": "R3 arrives at 200 ms. A 2 MB H2D transfer takes 2 ms, so admission occurs at 202 ms and TTFT is 4 ms. G2 supplies eight tokens. R3 computes only its third block, which contains R1's last prompt token and the new content. Once full, that block extends the cached prefix to R1·b0 → R1·b1 → R3·b2. R1's original third block held one token and was never sealed or stored.",
        "requests": PARENT_CHILD, "kv": {}, "sched": {},
        "expect": {"ttft": [2, 2, 4, 2], "host_reused": [0, 0, 8, 0]},
    },
    {
        "slug": "g2-pressure", "title": "G2 pressure and slow H2D",
        "summary": "G2 holds four blocks. H2D bandwidth is 0.05 GB/s.",
        "finding": "Restoring 2 MB takes 40 ms, all before admission. R3's TTFT rises to 42 ms. At 240 ms, storing R3·b2 evicts R2·b1. At 300 ms, storing R4 evicts R2·b0 and R1·b1. R3·b2 remains in G2 without its parent. A prefix lookup would stop at the missing parent and miss R3·b2. No request in this scenario tests that inference.",
        "requests": PARENT_CHILD,
        "kv": {"host_offload": {"num_host_blocks": 4, "h2d_bandwidth_gbps": 0.05}}, "sched": {},
        "expect": {"ttft": [2, 2, 42, 2], "host_reused": [0, 0, 8, 0]},
    },
    {
        "slug": "slow-d2h", "title": "Edge case: Reusing a D2H source block",
        "summary": "At 0.016 GB/s, storing 2 MB takes 125 ms. Requests arrive 100 ms apart, so the next request can reuse a G1 block while D2H still reads it.",
        "finding": "The same fence delays three operations. R2 gains admission at 100 ms, but prefill waits until 127 ms for D2H to finish reading R1's blocks (TTFT 29 ms). R3's H2D targets are still sources for R2's D2H, so the load starts at 254 ms (TTFT 58 ms). R4 evicts R3·b2 during its store and waits until 320.5 ms (TTFT 22.5 ms). These fences delay prefill or H2D while allowing admission.",
        "requests": PARENT_CHILD,
        "kv": {"host_offload": {"d2h_bandwidth_gbps": 0.016}}, "sched": {},
        "expect": {"ttft": [2, 29, 58, 22.5], "host_reused": [0, 0, 8, 0]},
    },
    {
        "slug": "g2-one-block", "title": "Edge case: One store exceeds G2 capacity",
        "summary": "G2 holds one block. Each baseline store needs two.",
        "finding": "Each store reports capacity_retry (structurally_unfittable). The engine skips the entire store, leaving G2 empty. R3 recomputes all 12 tokens, then attempts to store three blocks, including both shared with R1. That store also fails. With fixed prefill timing, TTFT remains 2 ms.",
        "requests": PARENT_CHILD,
        "kv": {"host_offload": {"num_host_blocks": 1}}, "sched": {},
        "expect": {"ttft": [2, 2, 2, 2], "host_reused": [0, 0, 0, 0]},
    },
    {
        "slug": "aligned-full-hit", "title": "Edge case: Exact hit on a block-aligned prompt",
        "summary": "Eight tokens fill two blocks, exactly the capacity of G1. R3 repeats R1's prompt verbatim.",
        "finding": "On a full prefix hit, the simulated vLLM path must recompute the last token. It backs up by one whole block and counts four reused tokens. H2D restores both blocks (2 MB), but prefill recomputes the second block, wasting 1 MB of transfer. This behavior has not been checked against a deployed vLLM connector.",
        "requests": [(0, 8, [1, 2]), (100, 8, [11, 12]), (200, 8, [1, 2])],
        "kv": {"capacity": {"type": "fixed", "blocks": 2}}, "sched": {},
        "expect": {"ttft": [2, 2, 4], "host_reused": [0, 0, 4]},
    },
    {
        "slug": "h2d-blocks-peer", "title": "Edge case: H2D reservations compete with another request",
        "summary": "The scheduler allows two concurrent sequences. H2D runs at 0.05 GB/s. While R3 waits for its prefix load, an unrelated four-token request (R4) arrives at 210 ms and needs one block.",
        "finding": "R3 reserves two of three G1 blocks for 40 ms. R4 uses the remaining block at 210 ms and finishes first. When R3 enters at 240 ms, it evicts the block R4 just sealed.",
        "requests": PARENT_CHILD[:3] + [(210, 4, [31])],
        "kv": {"host_offload": {"h2d_bandwidth_gbps": 0.05}}, "sched": {"max_sequences": 2},
        "expect": {"ttft": [2, 2, 42, 2], "host_reused": [0, 0, 8, 0]},
    },
    {
        "slug": "prompt-exceeds-g1", "title": "Edge case: Prompt exceeds G1 capacity",
        "summary": "G1 holds two blocks. A nine-token prompt needs three.",
        "finding": "AISim rejects the request on arrival without emitting KV events or splitting the prompt across G1 and G2. The expected outcome is exit code 1 with the message No requests completed.",
        "requests": [(0, 9, [1, 2, 3])],
        "kv": {"capacity": {"type": "fixed", "blocks": 2}}, "sched": {},
        "expect": {"ttft": [None], "host_reused": [0], "rejected": True},
    },
]


def merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def changes(s: dict) -> list[dict]:
    """AISim parameters this scenario overrides, as dotted kv_cache/scheduler paths with base and new values."""
    out = []
    def walk(prefix: str, base: dict, override: dict):
        for k, v in override.items():
            if isinstance(v, dict):
                walk(f"{prefix}{k}.", base.get(k, {}), v)
            else:
                out.append({"param": prefix + k, "base": base.get(k), "value": v})
    walk("kv_cache.", BASE_KV, s["kv"])
    walk("scheduler.", BASE_SCHED, s["sched"])
    return out


def write_inputs(s: dict, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    trace = folder / "trace.jsonl"
    trace.write_text("".join(
        json.dumps({"request_id": f"R{i}", "timestamp": t, "input_length": n, "output_length": 1, "hash_ids": h}) + "\n"
        for i, (t, n, h) in enumerate(s["requests"], start=1)))
    config = {
        "traffic": {"source": {"type": "trace", "format": "mooncake", "block_size": 4, "paths": [str(trace)]},
                    "load": {"type": "trace_timestamps"}},
        "engine": {
            "mode": "aggregated", "model": str(TINY_MODEL), "hardware": "h200_sxm", "backend": "vllm",
            "context_length": 2048,
            "workers": {"aggregated": {
                "parallelism": {"replicas": 1, "tensor": 1, "attention_data": 1},
                "scheduler": merge(BASE_SCHED, s["sched"]),
                "kv_cache": merge(BASE_KV, s["kv"]),
                "timing": {"type": "fixed", "prefill_ms": 2, "decode_ms": 1},
            }},
        },
    }
    path = folder / "config.json"  # JSON is valid YAML
    path.write_text(json.dumps(config, indent=1))
    return path


def capture(s: dict, out: Path) -> dict:
    folder = out / s["slug"]
    config = write_inputs(s, folder)
    proc = subprocess.run(
        [str(VENV_PY), str(HERE / "capture.py"), "--trace-out", str(folder / "trace.json"), "--",
         "predict", "--stack", "engine", "--config", str(config), "--capture-per-request",
         "--output-dir", str(folder / "aisim"), "--overwrite"],
        cwd=AISIM, capture_output=True, text=True)
    (folder / "run.log").write_text(proc.stdout + proc.stderr)
    status = {"slug": s["slug"], "exit": proc.returncode, "captured": (folder / "trace.json").exists()}
    if proc.returncode != 0:
        status["error"] = (proc.stderr.strip().splitlines() or ["(no stderr)"])[-1]
    return status


def check(s: dict, folder: Path) -> list[str]:
    """Compare the run against the scenario's expected observable behavior."""
    trace = json.loads((folder / "trace.json").read_text())["artifacts"]
    records = {r["uuid"]: r for r in map(json.loads, (folder / "aisim/requests.jsonl").read_text().splitlines())}
    ordered = [records[a["request_id"]] for a in sorted(trace["requests"], key=lambda a: a["observed_at_ms"])]
    got = {"ttft": [r.get("ttft_ms") for r in ordered],
           "host_reused": [r.get("first_admission_host_reused_input_tokens") or 0 for r in ordered]}
    rejected = any(o["rejected"] for o in trace["outputs"])
    errors = [f"{k}: expected {v}, got {got[k]}" for k, v in s["expect"].items() if k in got and got[k] != v]
    if rejected != s["expect"].get("rejected", False):
        errors.append(f"rejected: expected {s['expect'].get('rejected', False)}, got {rejected}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=HERE / "output")
    parser.add_argument("--only", nargs="*", help="scenario slugs to run")
    parser.add_argument("--no-render", action="store_true")
    parser.add_argument("--publish", type=Path, help="also copy the page here, e.g. dashboard/site/content/Attachments/kv-cache-replay.html")
    args = parser.parse_args()
    out = args.out.resolve()
    chosen = [s for s in SCENARIOS if not args.only or s["slug"] in args.only]
    statuses = [capture(s, out) for s in chosen]
    failed = False
    for s, st in zip(chosen, statuses):
        st["mismatch"] = check(s, out / s["slug"]) if st["captured"] else ["no replay captured"]
        failed |= bool(st["mismatch"])
        print(f"{s['slug']}: exit={st['exit']} " + ("OK" if not st["mismatch"] else "MISMATCH " + "; ".join(st["mismatch"])))
    if failed:
        return 1
    if args.no_render:
        return 0
    rendered = []
    for s, st in zip(chosen, statuses):
        rendered.append({**{k: s[k] for k in ("slug", "title", "summary", "finding")}, **st, "changes": changes(s),
                         "trace": str(out / s["slug"] / "trace.json"),
                         "requests_jsonl": str(out / s["slug"] / "aisim/requests.jsonl")})
    manifest = out / "scenarios.json"
    manifest.write_text(json.dumps(rendered, ensure_ascii=False, indent=1))
    page = out / "kv-cache-replay.html"
    status = subprocess.run([sys.executable, str(HERE / "render.py"), "--manifest", str(manifest), "--out", str(page)]).returncode
    if status == 0 and args.publish:
        args.publish.write_bytes(page.read_bytes())
        print(f"published {args.publish}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
