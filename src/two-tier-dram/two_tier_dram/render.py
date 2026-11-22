"""Turn two-tier traces into one self-contained animated HTML page."""

from __future__ import annotations

import json
from pathlib import Path

TEMPLATE = Path(__file__).with_name("template.html")


def page_entry(item: dict) -> dict:
    """One page scenario from a trace: its first re-timed request plus provenance."""
    trace = item["trace"]
    request = next((r for r in trace["requests"] if "snapshots" in r), None)
    if request is None:
        raise ValueError(f"{item.get('title', 'trace')}: no request was re-timed (need at least 2 output tokens)")
    return {"title": item["title"], "summary": item.get("summary", ""), "finding": item.get("finding", ""),
            "changes": item.get("changes", []), "aisim": trace["aisim"], "config": trace["config"],
            "request": {k: request[k] for k in ("request_id", "input_tokens", "native_itl_ms", "retimed_steps", "decode_start_ms")},
            "requests_total": len(trace["requests"]),
            **{k: request[k] for k in ("profile", "error", "metrics", "events", "snapshots", "compute_segments",
                                       "link_segments", "jobs")}}


def write_replay(items: list[dict], out: Path) -> None:
    data = [page_entry(item) for item in items]
    out.write_text(TEMPLATE.read_text().replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False)))
