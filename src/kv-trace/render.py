"""Render AISim KV replay artifacts as one self-contained, animated HTML page.

Input: the manifest written by scenarios.py (one entry per scenario with its
trace.json and requests.jsonl). Output: an offline HTML file with all data
embedded; it also works inside an <iframe>.

Data shape
  request  label, arrival, admit, compute_start, first_token, status, input,
           token_blocks, g1/host reused tokens, seq (block hashes)
  slot     key, label (R·bk), owner, tokens (filled/block_size), state
           G1 states: writing | recompute | active | cached | reserved
           G2 states: pending | resident | pinned
  transfer dir, queued, start (when bytes begin to move), end, blocks, bytes

Native events drive every state. Three things are inferred and marked:
  * blocks being written are not reported by AISim; their count follows the
    engine's admission rule: token_blocks - max(reused blocks, loaded blocks);
  * vLLM publishes a G1 eviction at the end of the pass whose allocation
    caused it; it is drawn at that pass's admission. A removal published after
    that pass's own `stored` event belongs to later scheduling and stays put;
  * a transfer's start is end - bytes/bandwidth; time before that is spent
    queued or fenced.
The slot simulation asserts occupancy never exceeds the configured capacity.
Scope: aggregated vLLM, one DP rank, one output token per request, no PP.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

PALETTE = ["#4f7cff", "#f08a24", "#21a179", "#c04bd6", "#d64545", "#2aa7c9"]


class Fail(SystemExit):
    pass


def load(entry: dict) -> dict:
    trace = json.loads(Path(entry["trace"]).read_text())
    spec = trace["execution_spec"].get("spec", trace["execution_spec"])
    rank = spec["engine"]["rank"]
    host = rank.get("native_host_offload") or {}
    bs = rank["block_size"]
    cfg = {"g1_blocks": rank["num_gpu_blocks"], "g2_blocks": host.get("num_host_blocks", 0), "block_size": bs,
           "bytes_per_token": rank["kv_cache_bytes_per_token"], "d2h_gbps": host.get("d2h_bandwidth_gbps"),
           "h2d_gbps": host.get("h2d_bandwidth_gbps"), "prefill_ms": rank["timing_model"]["prefill_ms"],
           "max_seqs": rank["max_num_seqs"]}
    block_bytes = bs * cfg["bytes_per_token"]
    art = trace["artifacts"]
    records = {r["uuid"]: r for r in map(json.loads, Path(entry["requests_jsonl"]).read_text().splitlines())}

    # ---- requests ----
    requests, owner, label_of, color_of_root = [], {}, {}, {}
    for i, a in enumerate(sorted(art["requests"], key=lambda r: r["observed_at_ms"]), start=1):
        rec = records.get(a["request_id"])
        if rec is None:
            raise Fail(f"{entry['slug']}: request {a['request_id']} has no record")
        lab = f"R{i}"
        seq = [str(h) for h in (a.get("replay_hashes") or {}).get("sequence_hashes", [])]
        for k, h in enumerate(seq):
            if h not in owner:
                owner[h], label_of[h] = lab, f"{lab}·b{k}"
        root = owner.get(seq[0], lab) if seq else lab
        color = color_of_root.setdefault(root, PALETTE[len(color_of_root) % len(PALETTE)])
        rejected = any(o["request_id"] == a["request_id"] and o["rejected"] for o in art["outputs"])
        ft = rec.get("first_token_ms")
        requests.append({
            "label": lab, "uuid": a["request_id"], "color": color, "input": a["input_length"],
            "token_blocks": math.ceil(a["input_length"] / bs), "seq": seq,
            "arrival": a["observed_at_ms"], "admit": rec.get("first_admit_ms"),
            "compute_start": None if ft is None else ft - cfg["prefill_ms"], "first_token": ft,
            "status": "rejected" if rejected else rec.get("terminal_status", "?"),
            "ttft": rec.get("ttft_ms"),
            "g1_reused": rec.get("first_admission_g1_reused_input_tokens") or 0,
            "host_reused": rec.get("first_admission_host_reused_input_tokens") or 0,
        })
    # relation to an earlier request, derived from shared block hashes only
    for r in requests:
        best = None
        for e in requests:
            if e is r or e["arrival"] >= r["arrival"]:
                continue
            n = next((k for k, (a, b) in enumerate(zip(e["seq"], r["seq"])) if a != b), min(len(e["seq"]), len(r["seq"])))
            if n and (best is None or n > best[1]):
                best = (e, n)
        r["relation"] = None
        if best:
            e, n = best
            if r["seq"] == e["seq"] and r["input"] == e["input"]:
                r["relation"] = {"of": e["label"], "kind": "repeat", "text": f"Repeat of {e['label']}", "shared_blocks": n}
            else:
                r["relation"] = {"of": e["label"], "kind": "next_turn", "text": f"Next turn after {e['label']}", "shared_blocks": n}
    by_uuid = {r["uuid"]: r for r in requests}
    by_label = {r["label"]: r for r in requests}
    pass_end = {r["first_token"]: r for r in requests if r["first_token"] is not None and r["admit"] < r["first_token"]}
    tokens_in = lambda h: (lambda r, k: min(bs, r["input"] - k * bs))(by_label[owner[h]], int(label_of[h].split("b")[-1]))

    # ---- actions: (t, order, op, payload, note) ----
    # order inside one instant: pass-end bookkeeping, then new scheduling, then admission
    A: list[tuple] = []
    raw = []
    stored_seen: set[float] = set()
    for e in sorted(art["kv_events"], key=lambda e: e["event"]["event_id"]):
        ev, t = e["event"], e["observed_at_ms"]
        tier = ev.get("tier", "device")
        kind, data = next(iter(ev["data"].items()))
        hs = [str(b["block_hash"]) for b in data["blocks"]] if kind == "stored" else [str(h) for h in data["block_hashes"]]
        raw.append({"t": t, "src": f"kv_events/{tier}", "what": kind, "blocks": hs})
        if tier != "device":
            continue
        if kind == "stored":
            stored_seen.add(t)
            A.append((t, 10, "g1_seal", {"hashes": hs}, "Full G1 blocks are sealed and available for prefix hits."))
            continue
        r = pass_end.get(t)
        if r is not None and t not in stored_seen:
            A.append((r["admit"], 20, "g1_evict", {"hashes": hs},
                      f"G1 evicts LRU blocks to admit {r['label']}. vLLM reports the eviction at pass end ({t:g} ms). The replay shows it at admission."))
        else:
            A.append((t, 20, "g1_evict", {"hashes": hs}, "G1 evicts LRU blocks to reserve H2D destinations."))
    for e in art["host_offload_events"]:
        ev, t = e["event"], e["observed_at_ms"]
        rl = by_uuid.get(e["request_id"], {}).get("label", "?")
        kind = ev["event"]
        hs = [str(h) for h in ev.get("block_hashes", [])] or ([str(ev["block_hash"])] if "block_hash" in ev else [])
        raw.append({"t": t, "src": "host_offload", "what": kind, "blocks": hs, "req": rl, "completes_at_ms": ev.get("completes_at_ms")})
        if kind == "store_block_mappings":
            continue
        if kind == "evicted":
            A.append((t, 21, "g2_evict", {"hashes": hs}, "G2 evicts LRU blocks to make room for a store."))
        elif kind == "store_prepared":
            A.append((t, 22, "g2_reserve", {"hashes": hs}, f"The scheduler selects full prompt blocks for {rl} and reserves G2 slots in the PendingStore state."))
        elif kind == "capacity_retry":
            why = "the store exceeds total G2 capacity and is skipped" if ev.get("structurally_unfittable") else "G2 is temporarily full and the store can retry later"
            A.append((t, 22, "note", {"hashes": hs}, f"Store failed for {rl} (capacity_retry): {why}."))
        elif kind == "store_submitted":
            A.append((t, 12, "d2h_start", {"hashes": hs, "end": ev["completes_at_ms"], "id": ev["transfer_id"]},
                      f"The pass ends and submits a D2H store of {len(hs)} × 1 MB. It completes at {ev['completes_at_ms']:g} ms."))
        elif kind == "store_completed":
            A.append((t, 13, "g2_resident", {"hashes": hs, "id": ev["transfer_id"]}, "D2H completes and the G2 blocks become resident."))
        elif kind == "load_queued":
            A.append((t, 23, "h2d_start", {"hashes": hs, "end": ev["completes_at_ms"], "id": ev["transfer_id"], "req": rl},
                      f"{rl} hits in G2, reserves destination blocks in G1, and queues an H2D load that completes at {ev['completes_at_ms']:g} ms."))
        elif kind == "load_completed":
            A.append((t, 15, "h2d_done", {"hashes": hs, "id": ev["transfer_id"]}, "H2D completes. The reserved blocks are now available for reuse in G1."))
        else:
            A.append((t, 22, "note", {"hashes": hs}, f"host_offload: {kind}"))
    for r in requests:
        rel = f", {r['relation']['text']}, first {r['relation']['shared_blocks']} blocks shared" if r["relation"] else ""
        A.append((r["arrival"], 16, "arrive", {"req": r["label"]}, f"{r['label']} arrives with {r['input']} tokens{rel}. It needs {r['token_blocks']} G1 blocks."))
        if r["status"] == "rejected":
            A.append((r["arrival"], 26, "reject", {"req": r["label"]},
                      f"G1 rejects {r['label']}. Its prompt needs {r['token_blocks']} blocks, exceeding total capacity ({cfg['g1_blocks']})."))
            continue
        A.append((r["admit"], 25, "admit", {"req": r["label"]}, ""))
        if r["compute_start"] > r["admit"]:
            A.append((r["compute_start"], 17, "compute", {"req": r["label"]},
                      f"The fence clears for {r['label']} and prefill starts. D2H was reading the reused G1 blocks for {r['compute_start'] - r['admit']:g} ms after admission."))
        A.append((r["first_token"], 11, "finish", {"req": r["label"]},
                  f"{r['label']} finishes prefill and emits its token (TTFT {r['ttft']:g} ms). The request releases any partially filled blocks."))
    A.sort(key=lambda a: (a[0], a[1]))

    # ---- slot simulation ----
    g1: list = [None] * cfg["g1_blocks"]
    g2: list = [None] * cfg["g2_blocks"]
    transfers: dict[int, dict] = {}
    loaded: dict[str, list[str]] = {}  # request -> hashes restored by H2D
    phase = {r["label"]: "Not arrived" for r in requests}

    def find(slots, key):
        return next((i for i, s in enumerate(slots) if s and s["key"] == key), None)

    def need(slots, key, tier, t):
        i = find(slots, key)
        if i is None:
            raise Fail(f"{entry['slug']}: {tier} block {label_of.get(key, key)} absent at t={t}")
        return i

    def put(slots, tier, item, t):
        for i, s in enumerate(slots):
            if s is None:
                slots[i] = item
                return
        raise Fail(f"{entry['slug']}: {tier} over capacity at t={t}: {[s and s['label'] for s in slots]} + {item['label']}")

    def block(h, state):
        return {"key": h, "label": label_of.get(h, h[:6]), "owner": owner.get(h), "tokens": tokens_in(h) if h in owner else bs, "state": state}

    def transfer(direction, p, t, gbps):
        n = len(p["hashes"]) * block_bytes
        start = max(t, p["end"] - (n / (gbps * 1e6) if gbps else 0))
        return {"dir": direction, "queued": t, "start": start, "end": p["end"], "bytes": n,
                "blocks": [label_of.get(h, h[:6]) for h in p["hashes"]]}

    snapshots, i = [], 0
    while i < len(A):
        t, notes = A[i][0], []
        while i < len(A) and A[i][0] == t:
            _, _, op, p, note = A[i]
            i += 1
            if op == "g1_evict":
                for h in p["hashes"]:
                    g1[need(g1, h, "G1", t)] = None
            elif op == "g1_seal":
                for h in p["hashes"]:
                    k = find(g1, h)
                    if k is not None:
                        g1[k]["state"] = "active"
                        continue
                    # the writer is whichever request has this hash at the slot's index (R3 may rewrite R1's block)
                    k = next((j for j, s in enumerate(g1) if s and s["state"] == "writing"
                              and by_label[s["owner"]]["seq"][s["index"]:s["index"] + 1] == [h]), None)
                    if k is None:
                        raise Fail(f"{entry['slug']}: sealed {label_of[h]} has no writing slot at t={t}")
                    g1[k] = block(h, "active")
            elif op == "admit":
                r = by_label[p["req"]]
                reused_b = (r["g1_reused"] + r["host_reused"]) // bs
                loaded_b = len(loaded.get(r["label"], []))
                for h in r["seq"][:max(reused_b, loaded_b)]:
                    k = find(g1, h)
                    if k is not None:
                        g1[k]["state"] = "recompute" if r["seq"].index(h) >= reused_b else "active"
                new = list(range(max(reused_b, loaded_b), r["token_blocks"]))
                for k in new:
                    put(g1, "G1", {"key": f"w:{r['label']}:{k}", "label": f"{r['label']}·b{k}", "owner": r["label"], "index": k,
                                   "tokens": min(bs, r["input"] - k * bs), "state": "writing"}, t)
                fenced = r["compute_start"] > t
                phase[r["label"]] = "Admitted, fenced" if fenced else "prefill"
                parts = [f"reused blocks: {reused_b} (G1: {r['g1_reused']} tokens, G2: {r['host_reused']} tokens)"]
                if loaded_b > reused_b:
                    parts.append(f"H2D block {loaded_b} requires full recomputation because a full prefix hit must recompute the last token")
                parts.append(f"new allocations: {len(new)}")
                note = f"{r['label']} admitted, {r['token_blocks']} blocks needed: " + ", ".join(parts) + (". Prefill waits for D2H to finish reading reused blocks." if fenced else ". Prefill starts.")
            elif op == "compute":
                phase[p["req"]] = "prefill"
            elif op == "finish":
                r = by_label[p["req"]]
                phase[r["label"]] = "Complete"
                for k, s in enumerate(g1):
                    if s and s["owner"] == r["label"] and s["state"] == "writing":
                        g1[k] = None
                    elif s and s["key"] in r["seq"] and s["state"] in ("active", "recompute"):
                        s["state"] = "cached"
            elif op == "arrive":
                phase[p["req"]] = "Queued"
            elif op == "reject":
                phase[p["req"]] = "Rejected"
            elif op == "g2_evict":
                for h in p["hashes"]:
                    g2[need(g2, h, "G2", t)] = None
            elif op == "g2_reserve":
                for h in p["hashes"]:
                    put(g2, "G2", block(h, "pending"), t)
            elif op == "d2h_start":
                transfers[p["id"]] = transfer("D2H", p, t, cfg["d2h_gbps"])
            elif op == "g2_resident":
                for h in p["hashes"]:
                    g2[need(g2, h, "G2", t)]["state"] = "resident"
                transfers.pop(p["id"], None)
            elif op == "h2d_start":
                phase[p["req"]] = "Waiting for H2D"
                loaded[p["req"]] = p["hashes"]
                for h in p["hashes"]:
                    g2[need(g2, h, "G2", t)]["state"] = "pinned"
                    put(g1, "G1", block(h, "reserved"), t)
                transfers[p["id"]] = transfer("H2D", p, t, cfg["h2d_gbps"])
            elif op == "h2d_done":
                for h in p["hashes"]:
                    g2[need(g2, h, "G2", t)]["state"] = "resident"
                    g1[need(g1, h, "G1", t)]["state"] = "cached"
                transfers.pop(p["id"], None)
            notes.append({"op": op, "text": note, "blocks": [label_of.get(h, h[:6]) for h in p.get("hashes", [])]})
        snapshots.append({"t": t, "notes": notes, "g1": [dict(s) if s else None for s in g1],
                          "g2": [dict(s) if s else None for s in g2],
                          "transfers": [dict(v) for v in transfers.values()], "phase": dict(phase)})
    all_transfers = {}
    for s in snapshots:
        for x in s["transfers"]:
            all_transfers[(x["dir"], x["queued"], x["end"])] = x
    return {"slug": entry["slug"], "title": entry["title"], "summary": entry["summary"], "finding": entry.get("finding", ""),
            "exit": entry.get("exit", 0), "changes": entry.get("changes", []), "cfg": cfg, "requests": requests,
            "owner_color": {r["label"]: r["color"] for r in requests},
            "snapshots": snapshots, "transfers": list(all_transfers.values()),
            "raw": sorted(raw, key=lambda x: x["t"]), "labels": label_of}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    scenarios = [load(e) for e in json.loads(args.manifest.read_text())]
    template = (Path(__file__).parent / "template.html").read_text()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(template.replace("/*__DATA__*/null", json.dumps(scenarios, ensure_ascii=False)))
    for s in scenarios:
        print(f"{s['slug']}: {len(s['snapshots'])} snapshots, capacity check passed (G1={s['cfg']['g1_blocks']}, G2={s['cfg']['g2_blocks']})")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
