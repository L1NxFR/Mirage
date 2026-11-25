"""Render closed-loop two-tier scenarios into one self-contained HTML page."""

from __future__ import annotations

import json
from pathlib import Path

TEMPLATE = Path(__file__).with_name("template.html")


STATE = {"loading": 0, "resident": 1, "gone": 2}


def pick_detailed(passes: list[dict]) -> set[int]:
    """Keep per-layer detail for two passes: the first one, and the pure-decode pass with the largest batch."""
    detailed = [i for i, p in enumerate(passes) if p.get("detail")]
    keep = set(detailed[:1])
    decodes = [i for i in detailed if all(r["kind"] == "decode" for r in passes[i]["requests"])]
    if decodes:
        keep.add(max(decodes, key=lambda i: (len(passes[i]["requests"]), -i)))
    return keep


def compact(p: dict) -> dict:
    """Experts as [id, hit, state, job] arrays; the page decodes them."""
    for snap in p["snapshots"]:
        detail = snap.get("detail") or {}
        if detail.get("experts"):
            detail["experts"] = [[e["id"], 1 if e["was"] == "hit" else 0, STATE.get(e.get("state"), 2), e.get("job")]
                                 for e in detail["experts"]]
    return p


def strip(p: dict) -> dict:
    return {k: p[k] for k in ("index", "start_ms", "end_ms", "native_ms", "requests", "metrics")}


def write_page(items: list[dict], out: Path) -> None:
    data = []
    for item in items:
        header = item["trace"]["header"]
        keep = pick_detailed(item["trace"]["passes"])
        profile = header["config"]["profile"]
        data.append({
            **{k: item[k] for k in ("slug", "title", "summary", "finding", "workload", "changes")},
            "metrics": item["summary_metrics"],
            "requests": item["two_tier"]["requests"],
            "native_requests": item["native"]["requests"],
            "config": {k: v for k, v in header["config"].items() if k != "profile"},
            "expert_cache_slots": header["expert_cache_slots"],
            "profile": {**{k: v for k, v in profile.items() if k not in ("layers", "source")},
                        "kinds": "".join("C" if l["kind"] == "csa" else "H" for l in profile["layers"]),
                        "base_bytes_total": sum(l["base_bytes"] for l in profile["layers"]),
                        "source": {k: profile["source"].get(k) for k in ("model", "hardware", "backend", "database_mode")}},
            "passes": [compact(p) if i in keep else strip(p)
                       for i, p in enumerate(item["trace"]["passes"])],
        })
    out.write_text(TEMPLATE.read_text().replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False, separators=(",", ":"))))
