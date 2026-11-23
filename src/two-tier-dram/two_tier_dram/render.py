"""Turn two-tier traces into one self-contained animated HTML page."""

from __future__ import annotations

import json
from pathlib import Path

TEMPLATE = Path(__file__).with_name("template.html")
SWEEP_KEYS = ("name", "title", "basis", "feasible", "error", "cold_ms", "steady", "tail_from", "steps", "tail_token_ms",
              "tail_compute_ms", "tail_wait_base_ms", "tail_wait_experts_ms", "tail_wait_kv_ms", "tail_bytes",
              "tail_bytes_over_bw_ms", "tail_link_util", "tail_expert_hit_rate", "evicted_experts", "native_ms",
              "hardware_preset", "tail_spread", "expert_prefetched")


def page_entry(item: dict) -> dict:
    """One page tab from a trace: its first re-timed request plus provenance."""
    trace = item["trace"]
    request = next((r for r in trace["requests"] if "snapshots" in r), None)
    if request is None:
        raise ValueError(f"{item.get('title', 'trace')}: no request with a full trace (need trace_detail=full and 2+ tokens)")
    return {"title": item["title"], "summary": item.get("summary", ""), "basis": item.get("basis", ""),
            "aisim": trace["aisim"], "config": trace["config"],
            "request": {k: request[k] for k in ("request_id", "input_tokens", "native_itl_ms", "retimed_steps", "decode_start_ms")},
            **{k: request[k] for k in ("profile", "compute_basis", "error", "feasible", "infeasible", "metrics", "per_step",
                                       "events", "snapshots", "compute_segments", "link_segments", "jobs")}}


def write_replay(items: list[dict], out: Path, sweep: list[dict] | None = None) -> None:
    data = {"scenarios": [page_entry(item) for item in items],
            "sweep": [{k: row.get(k) for k in SWEEP_KEYS} for row in (sweep or [])]}
    out.write_text(TEMPLATE.read_text().replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False, separators=(",", ":"))))
