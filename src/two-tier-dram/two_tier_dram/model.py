"""Per-layer re-timing of decode on a two-tier DRAM system.

AISim prices a decode pass as one number and assumes every weight and KV byte
is already in device memory. This model replays the same decode steps layer by
layer on a small fast tier 1 and a large slow tier 2 joined by one shared link:

    [base weights resident?] -> top-k select (csa) -> fetch missing KV -> attention
        -> route -> fetch missing experts -> MoE

Tier 1 holds scratch, non-expert weights (all layers, or the current layer plus
a prefetched next layer), the KV every step reads in full, routed experts
(an LRU cache kept across steps, or released after each layer), and an LRU
cache of sparse top-k KV entries. Tier 2 holds everything. Compute times, byte
sizes and model geometry come from a `ModelProfile`, which AISim supplies in
production (see profile.py).

Units: hardware arrives in bytes, bytes/s and seconds (config.Hardware); the
simulation clock is milliseconds to match AISim's latencies. The link moves
data at the effective copy bandwidth `tier2_bandwidth * copy_efficiency` and
pays `transfer_overhead` once per transfer.

Not modelled, reported as a bound instead: copies write into tier 1 while
compute reads it. If compute is bandwidth-bound on tier 1, overlapping a copy
could slow it by at most copy_bandwidth / tier1_bandwidth of the overlapped
time; `metrics.tier1_contention_bound_ms` reports that upper bound.

The simulation is exact about its own state: tier-1 occupancy is checked on
every allocation, a phase never starts before its data arrived, and the link
never moves more than its bandwidth. A tier-1 overflow ends the run and returns
the trace so far in `error`.

Top-k entries and routed experts are synthetic: each layer keeps every pick
from its previous step with a configured probability and draws the rest
uniformly. AISim has no selected sets to replay.
"""

from __future__ import annotations

import random
from collections import OrderedDict

from .config import GB, ModelProfile, TwoTierConfig

PHASES_COMPUTE = ("attention", "moe", "tail")

EPS = 1e-9
PRIORITY = {"demand": 0, "prefetch": 1, "writeback": 2}
KINDS = ("demand_base", "prefetch_base", "demand_kv", "demand_expert", "prefetch_expert", "writeback")


class ModelError(Exception):
    """An invariant of the model was violated."""


class CapacityError(Exception):
    """A tier cannot hold what the workload needs."""


class TwoTierSim:
    def __init__(self, cfg: TwoTierConfig, profile: ModelProfile):
        self.cfg, self.p, self.hw = cfg, profile, cfg.hardware
        self.steps = cfg.max_decode_steps
        self.n = len(profile.layers)
        self.now = 0.0
        self.resident_base = cfg.base_weights == "resident"
        self.bundles: dict[int, dict] = {}  # layer -> {state, role, job}; layer_prefetch only
        self.experts: OrderedDict[tuple[int, int], dict] = OrderedDict()  # (layer, expert) -> {state, pinned, job}
        self.kv: OrderedDict[tuple[int, int], bool] = OrderedDict()  # (layer, entry) -> pinned
        self.kv_loading = 0
        self.expert_count = [0] * self.n  # per-layer entries in the expert cache, loading included
        self.kv_count = [0] * self.n  # per-layer resident hot-KV entries
        self.evicted_experts = self.evicted_kv = self.released_experts = 0
        self.step_hits = self.step_lookups = 0
        self.infeasible: list[str] = []
        self.step_marks: list[dict] = []
        self.dirty_bytes = 0.0
        self.synced_tokens = 0
        self.jobs: list[dict] = []
        self.active: dict | None = None
        self.link_clock = 0.0
        self.link_busy_ms = 0.0
        self.compute = {"step": None, "layer": None, "phase": "idle"}
        self.detail: dict = {}
        self.compute_segments: list[dict] = []
        self.link_segments: list[dict] = []
        self.events: list[dict] = []
        self.snapshots: list[dict] = []
        self._touched: set[int] = set()
        self._last_counts = [(0, 0, 0)] * self.n
        self.peak_tier1 = 0.0
        self.error: str | None = None
        self.token_ms: list[float] = []
        self.m = {"expert_lookups": 0, "expert_hits": 0, "expert_late": 0, "kv_lookups": 0, "kv_hits": 0,
                  "base_prefetches": 0, "base_late": 0, "expert_prefetched": 0, "expert_prefetch_used": 0,
                  "wait_base_ms": 0.0, "wait_kv_ms": 0.0, "wait_experts_ms": 0.0,
                  "link_bytes": {kind: 0.0 for kind in KINDS}}
        self._rng = random.Random(cfg.seed)
        self._prev_kv: dict[int, list[int]] = {}
        self._prev_experts: dict[int, list[int]] = {}

        p = profile
        self.fixed_bytes = self.hw.scratch + p.global_bytes
        self.static_bytes = sum(l.static_kv_bytes for l in p.layers)
        if self.resident_base:
            self.static_bytes += sum(l.indexer_bytes for l in p.layers)
            self.base_reserved = sum(l.base_bytes for l in p.layers)
        else:
            self.base_reserved = 2 * max(l.base_bytes + l.indexer_bytes for l in p.layers)
        hot_kv_reserved = max(cfg.hot_kv_entries, p.index_topk) * p.kv_entry_bytes
        # every new token's KV may still be dirty (not yet written back) at the end
        self.dirty_reserved = self.steps * p.new_token_kv_bytes
        left = self.hw.tier1_capacity - self.fixed_bytes - self.static_bytes - self.base_reserved - hot_kv_reserved - self.dirty_reserved
        self.expert_left = left
        self.expert_cap = max(min(left, cfg.expert_cache_capacity) if cfg.expert_cache_capacity else left, 0.0)
        self.expert_slots = int(self.expert_cap // p.expert_bytes)

    def _check_fits(self) -> None:
        """Static capacity checks, run before the first step so a failure still yields a trace."""
        p, cfg = self.p, self.cfg
        full = p.full_weights_bytes + p.full_kv_bytes
        if full > self.hw.tier2_capacity:
            reason = (f"Tier 2 DRAM cannot hold the full weights and KV cache. They require {full / GB:.1f} GB, but tier 2 has {self.hw.tier2_capacity / GB:.1f} GB. "
                      "The model is infeasible on a single device. Multi-device sharding is unimplemented.")
            if cfg.tier2_capacity_check == "enforce":
                raise CapacityError(reason)
            self.infeasible.append(reason)
            self._event("infeasible", reason + " Continuing with tier2_capacity_check=counterfactual for comparison only.")
        need = p.experts_per_token * p.expert_bytes
        if self.expert_cap < need:
            how = "all layers resident" if self.resident_base else "current layer and prefetched next layer"
            raise CapacityError(
                f"Tier 1 DRAM ({self.hw.tier1_capacity / GB:g} GB) cannot hold one layer's routed experts. Scratch and global weights use {self.fixed_bytes / GB:.1f} GB, "
                f"resident KV uses {self.static_bytes / GB:.2f} GB, and non-expert weights ({how}) reserve {self.base_reserved / GB:.1f} GB. "
                f"The expert cache has {max(self.expert_left, 0) / GB:.2f} GB left and one layer needs {need / GB:.2f} GB.")

    # ---- tier-1 ledger -------------------------------------------------
    def tier1(self) -> dict:
        p = self.p
        base = sum(l.base_bytes for l in p.layers) if self.resident_base else sum(
            p.layers[i].base_bytes + p.layers[i].indexer_bytes for i in self.bundles)
        return {"fixed": self.fixed_bytes, "base": base, "static_kv": self.static_bytes,
                "experts": len(self.experts) * p.expert_bytes,
                "hot_kv": (len(self.kv) + self.kv_loading) * p.kv_entry_bytes, "dirty": self.dirty_bytes}

    def _check_tier1(self, what: str) -> None:
        used = sum(self.tier1().values())
        if used > self.hw.tier1_capacity + 1:
            raise CapacityError(f"Tier 1 DRAM capacity exceeded after {what}. Required {used / GB:.2f} GB, available {self.hw.tier1_capacity / GB:g} GB.")
        self.peak_tier1 = max(self.peak_tier1, used)

    def _evict_experts_for(self, incoming: int) -> None:
        """Make room for `incoming` experts by evicting least-recently-used ones.

        Protected, never evicted: experts still being transferred (state "loading") and experts the
        current layer uses (pinned). A prefetched expert that has arrived but is not yet used is
        evictable; it sits at the LRU end where it was inserted.
        """
        while len(self.experts) + incoming > self.expert_slots:
            victim = next((k for k, e in self.experts.items() if e["state"] == "resident" and not e["pinned"]), None)
            if victim is None:
                raise CapacityError(f"The {self.expert_cap / GB:.2f} GB expert cache needs room for {incoming} more experts and has no eviction candidates.")
            del self.experts[victim]
            self.expert_count[victim[0]] -= 1
            self._touched.add(victim[0])
            self.evicted_experts += 1

    def _evict_kv_for(self, incoming: int) -> None:
        cap = max(self.cfg.hot_kv_entries, 0)
        while len(self.kv) + self.kv_loading + incoming > cap:
            victim = next((k for k, pinned in self.kv.items() if not pinned), None)
            if victim is None:
                break  # everything left is in use by the current layer; the hard check decides
            del self.kv[victim]
            self.kv_count[victim[0]] -= 1
            self._touched.add(victim[0])
            self.evicted_kv += 1

    # ---- shared link ---------------------------------------------------
    def _enqueue(self, cls: str, kind: str, nbytes: float, label: str, effect: dict) -> dict:
        job = {"id": len(self.jobs), "cls": cls, "kind": kind, "bytes": nbytes, "left": nbytes, "label": label,
               "setup_left": self.hw.transfer_overhead * 1e3, "urgent": False, "done": False,
               "queued": self.now, "end": None, "effect": effect}
        self.jobs.append(job)
        self._pick()
        return job

    def _rank(self, job: dict) -> tuple:
        if self.cfg.link_policy == "fifo":
            return (0, job["id"])
        return (0 if job["urgent"] else PRIORITY[job["cls"]], job["id"])

    def _pick(self) -> None:
        if self.cfg.link_policy == "fifo" and self.active and not self.active["done"]:
            return
        pending = [j for j in self.jobs if not j["done"]]
        best = min(pending, key=self._rank) if pending else None
        if best is self.active:
            return
        if self.active and not self.active["done"]:
            self._event("link_preempt", f"Link paused {self.active['label']} for {best['label']}")
        self._close_link_segment()
        self.active = best
        if best:
            self.link_segments.append({"job": best["id"], "kind": best["kind"], "label": best["label"], "t0": self.now,
                                       "t1": None, "f0": 1 - best["left"] / best["bytes"], "f1": None,
                                       "setup": best["setup_left"]})

    def _close_link_segment(self) -> None:
        if self.link_segments and self.link_segments[-1]["t1"] is None:
            seg = self.link_segments[-1]
            job = self.jobs[seg["job"]]
            seg["t1"], seg["f1"] = self.now, 1 - job["left"] / job["bytes"]
            if seg["t1"] - seg["t0"] < EPS:
                self.link_segments.pop()

    def _rate(self) -> float:
        return self.hw.copy_bandwidth / 1e3  # bytes per ms

    def _advance_link(self, to: float) -> None:
        dt = to - self.link_clock
        self.link_clock = to
        job = self.active
        if not job or dt <= 0:
            return
        self.link_busy_ms += dt
        setup = min(dt, job["setup_left"])
        job["setup_left"] -= setup
        moved = min(job["left"], (dt - setup) * self._rate())
        job["left"] -= moved
        self.m["link_bytes"][job["kind"]] += moved

    def _link_finish_time(self) -> float | None:
        job = self.active
        return None if not job else self.now + job["setup_left"] + job["left"] / self._rate()

    def _complete(self, job: dict) -> None:
        self.m["link_bytes"][job["kind"]] += job["left"]
        job["done"], job["end"], job["left"] = True, self.now, 0.0
        eff = job["effect"]
        if "bundle" in eff:
            self.bundles[eff["bundle"]]["state"] = "resident"
            self._event("base_arrive", f"Non-expert weights for layer {eff['bundle']} arrived in tier 1")
        elif "kv" in eff:
            layer, entries = eff["kv"]
            self.kv_loading -= len(entries)
            for entry in entries:
                self.kv[(layer, entry)] = True
            self.kv_count[layer] += len(entries)
            self._touched.add(layer)
            self._event("kv_arrive", f"The {len(entries)} missing top-k KV entries for layer {layer} arrived in tier 1")
        elif "experts" in eff:
            layer, ids = eff["experts"]
            for i in ids:
                if (layer, i) in self.experts:
                    self.experts[(layer, i)]["state"] = "resident"
            self._touched.add(layer)
            verb = "prefetched" if job["cls"] == "prefetch" else "missing"
            self._event("experts_arrive", f"Layer {layer}: {len(ids)} {verb} experts arrived in tier 1: " + ", ".join(f"e{i}" for i in ids))
        elif "writeback" in eff:
            self.dirty_bytes -= eff["writeback"]
            self.synced_tokens += 1
            self._event("writeback_done", "KV writeback for the new token completed in tier 2")
        self._close_link_segment()
        self.active = None
        self._pick()

    # ---- compute -------------------------------------------------------
    def _event(self, kind: str, text: str) -> None:
        self.events.append({"t": self.now, "kind": kind, "text": text,
                            "step": self.compute["step"], "layer": self.compute["layer"]})

    def _pick_set(self, prev: list[int] | None, universe: int, k: int, overlap: float) -> list[int]:
        k = min(k, universe)
        chosen = {x for x in prev if self._rng.random() < overlap} if prev else set()
        while len(chosen) < k:
            chosen.add(self._rng.randrange(universe))
        return sorted(chosen)

    def _fetch_bundle(self, layer: int, cls: str, role: str) -> dict:
        l = self.p.layers[layer]
        self.bundles[layer] = {"state": "loading", "role": role, "job": None}
        self._check_tier1(f"reserving space for layer {layer} non-expert weights")
        kind = "prefetch_base" if cls == "prefetch" else "demand_base"
        verb = "Prefetch" if cls == "prefetch" else "Fetch on demand:"
        job = self._enqueue(cls, kind, l.base_bytes + l.indexer_bytes, f"{verb} L{layer} non-expert weights", {"bundle": layer})
        self.bundles[layer]["job"] = job["id"]
        self._touched.add(layer)
        return job

    def _prefetch_experts(self, layer: int) -> None:
        predicted = [i for i in self._prev_experts.get(layer, []) if (layer, i) not in self.experts]
        if not predicted:
            return
        self._evict_experts_for(len(predicted))
        job = self._enqueue("prefetch", "prefetch_expert", len(predicted) * self.p.expert_bytes,
                            f"Prefetch {len(predicted)} experts for L{layer}", {"experts": (layer, predicted)})
        for i in predicted:
            self.experts[(layer, i)] = {"state": "loading", "pinned": False, "job": job["id"], "prefetched": True}
        self.expert_count[layer] += len(predicted)
        self.m["expert_prefetched"] += len(predicted)
        self._touched.add(layer)
        self._check_tier1("reserving space for prefetched experts")
        self._touched.add(layer)
        self._event("expert_prefetch", f"Prefetching {len(predicted)} experts for layer {layer} using the previous step's routing")

    def _process(self, steps: int):
        p, cfg = self.p, self.cfg
        for step in range(steps):
            step_start = self.now
            self.step_hits = self.step_lookups = 0
            for layer, l in enumerate(p.layers):
                self.compute.update(step=step, layer=layer)
                self.detail = {"experts": [], "kv": None}
                last = step == steps - 1 and layer == self.n - 1
                # 1. non-expert weights of this layer
                if not self.resident_base:
                    bundle = self.bundles.get(layer)
                    if bundle is None:
                        job = self._fetch_bundle(layer, "demand", "current")
                        self._event("base_miss", f"Compute waits for an on-demand fetch of layer {layer} non-expert weights")
                        yield ("wait", [job["id"]], "wait_base")
                    elif bundle["state"] == "loading":
                        job = self.jobs[bundle["job"]]
                        job["urgent"] = True
                        self.m["base_late"] += 1
                        self._event("base_late", f"Compute waits for the late layer {layer} weight prefetch")
                        self._pick()
                        yield ("wait", [job["id"]], "wait_base")
                    if self.bundles[layer]["state"] != "resident":
                        raise ModelError(f"layer {layer} started before its base weights arrived")
                    self.bundles[layer]["role"] = "current"
                    nxt = (layer + 1) % self.n
                    if not last and self.n > 1 and nxt not in self.bundles:
                        self.m["base_prefetches"] += 1
                        self._fetch_bundle(nxt, "prefetch", "prefetch")
                if cfg.expert_prefetch == "last_step" and not last and self.n > 1:
                    self._prefetch_experts((layer + 1) % self.n)
                # 2. sparse attention: pick top-k, fetch what is missing
                sel_kv: list[tuple[int, int]] = []
                if l.kind == "csa":
                    picks = self._pick_set(self._prev_kv.get(layer), l.topk_candidates, p.index_topk, cfg.topk_overlap)
                    self._prev_kv[layer] = picks
                    sel_kv = [(layer, e) for e in picks]
                    missing = [e for e in picks if (layer, e) not in self.kv]
                    for key in sel_kv:
                        if key in self.kv:
                            self.kv[key] = True
                            self.kv.move_to_end(key)
                    hits = len(picks) - len(missing)
                    self.m["kv_lookups"] += len(picks)
                    self.m["kv_hits"] += hits
                    self.detail["kv"] = {"topk": len(picks), "hits": hits, "missing": len(missing), "job": None}
                    self._event("topk", f"Indexer selected {len(picks)} top-k entries ({hits} hits, {len(missing)} missing)")
                    if missing:
                        self._evict_kv_for(len(missing))
                        self.kv_loading += len(missing)
                        self._check_tier1("reserving space for missing top-k KV entries")
                        job = self._enqueue("demand", "demand_kv", len(missing) * p.kv_entry_bytes,
                                            f"Fetch {len(missing)} top-k KV entries for L{layer} on demand", {"kv": (layer, missing)})
                        self.detail["kv"]["job"] = job["id"]
                        self._touched.add(layer)
                        yield ("wait", [job["id"]], "wait_kv")
                    if any(key not in self.kv for key in sel_kv):
                        raise ModelError(f"attention at layer {layer} started before its KV arrived")
                yield ("delay", l.attention_ms, "attention")
                # 3. MoE: route, fetch missing experts
                routed = self._pick_set(self._prev_experts.get(layer), p.experts_per_layer, p.experts_per_token, cfg.expert_overlap)
                self._prev_experts[layer] = routed
                waits, missing, hits, late = [], [], 0, 0
                for i in routed:
                    entry = self.experts.get((layer, i))
                    if entry is None:
                        missing.append(i)
                    elif entry["state"] == "loading":
                        late += 1
                        self.jobs[entry["job"]]["urgent"] = True
                        if entry["job"] not in waits:
                            waits.append(entry["job"])
                        entry["pinned"] = True
                    else:
                        hits += 1
                        if entry.pop("prefetched", False):
                            self.m["expert_prefetch_used"] += 1
                        entry["pinned"] = True
                        self.experts.move_to_end((layer, i))
                self.m["expert_lookups"] += len(routed)
                self.m["expert_hits"] += hits
                self.step_lookups += len(routed)
                self.step_hits += hits
                self.m["expert_late"] += late
                if missing:
                    self._evict_experts_for(len(missing))
                    job = self._enqueue("demand", "demand_expert", len(missing) * p.expert_bytes,
                                        f"Fetch {len(missing)} experts for L{layer} on demand", {"experts": (layer, missing)})
                    for i in missing:
                        self.experts[(layer, i)] = {"state": "loading", "pinned": True, "job": job["id"]}
                    self.expert_count[layer] += len(missing)
                    waits.append(job["id"])
                    self._check_tier1("reserving space for missing experts")
                self._touched.add(layer)
                self.detail["experts"] = [{"id": i, "was": "miss" if i in missing else "hit"} for i in routed]
                self._event("route", f"Router selected {', '.join(f'e{i}' for i in routed)}: {hits} hits, "
                                     f"{len(missing)} missing" + (f", {late} late prefetches" if late else ""))
                if waits:
                    self._pick()
                    yield ("wait", waits, "wait_experts")
                if any(self.experts[(layer, i)]["state"] != "resident" for i in routed):
                    raise ModelError(f"MoE at layer {layer} started before its experts arrived")
                yield ("delay", l.moe_ms, "moe")
                # 4. layer done
                for i in routed:
                    self.experts[(layer, i)]["pinned"] = False
                if cfg.expert_cache == "per_layer":
                    for i in routed:  # rotation: this layer's experts leave tier 1 once it is done
                        del self.experts[(layer, i)]
                    self.expert_count[layer] -= len(routed)
                    self.released_experts += len(routed)
                for key in sel_kv:
                    if cfg.hot_kv_entries <= 0:
                        del self.kv[key]
                        self.kv_count[layer] -= 1
                    else:
                        self.kv[key] = False
                self._touched.add(layer)
                if not self.resident_base and self.n > 1:
                    del self.bundles[layer]
            yield ("delay", p.tail_ms, "tail")
            self.dirty_bytes += p.new_token_kv_bytes
            self._check_tier1("writing KV for the new token")
            self._enqueue("writeback", "writeback", p.new_token_kv_bytes, f"Write back KV for the new token at step {step + 1}",
                          {"writeback": p.new_token_kv_bytes})
            self.token_ms.append(self.now - step_start)
            self.step_marks.append({
                "end_ms": self.now, "expert_hits": self.step_hits, "expert_lookups": self.step_lookups,
                "kv_hits": self.m["kv_hits"], "kv_lookups": self.m["kv_lookups"],
                "evicted_experts": self.evicted_experts, "evicted_kv": self.evicted_kv,
                "cache_experts": len(self.experts), "link_bytes": dict(self.m["link_bytes"]),
                "link_busy_ms": self.link_busy_ms, "tier1_bytes": sum(self.tier1().values())})
            self.compute["layer"] = None
            self._event("token", f"Decode step {step + 1} completed in {self.now - step_start:.3f} ms"
                                 f" (native AISim time {p.native_step_ms:.3f} ms)")
        self.compute.update(step=None, layer=None, phase="idle")
        self.detail = {}

    # ---- engine --------------------------------------------------------
    def _layer_counts(self, layer: int) -> tuple[int, int, int]:
        experts, kv = self.expert_count[layer], self.kv_count[layer]
        bundle = self.bundles.get(layer)
        base = 2 if self.resident_base else 0 if bundle is None else 1 if bundle["state"] == "loading" else 2
        return (experts, kv, base)

    def _snapshot(self) -> None:
        changed = {}
        for layer in sorted(self._touched):
            counts = self._layer_counts(layer)
            if counts != self._last_counts[layer]:
                self._last_counts[layer] = counts
                changed[layer] = counts
        self._touched.clear()
        detail = dict(self.detail)
        if detail.get("experts"):
            layer = self.compute["layer"]
            detail["experts"] = [{**e, "state": self.experts[(layer, e["id"])]["state"],
                                  "job": self.experts[(layer, e["id"])].get("job")}
                                 if (layer, e["id"]) in self.experts else {**e, "state": "gone"} for e in detail["experts"]]
        cache = {"experts": len(self.experts), "slots": self.expert_slots, "evicted": self.evicted_experts,
                 "released": self.released_experts, "step_hits": self.step_hits, "step_lookups": self.step_lookups,
                 "kv": len(self.kv), "kv_cap": self.cfg.hot_kv_entries}
        snap = {"t": round(self.now, 9), "compute": dict(self.compute), "detail": detail, "layers": changed, "cache": cache,
                "tier1": {k: round(v) for k, v in self.tier1().items()},
                "tier2": {"dirty_bytes": round(self.dirty_bytes), "synced_tokens": self.synced_tokens},
                "link": {"active": self.active["id"] if self.active else None,
                         "queue": [j["id"] for j in sorted((j for j in self.jobs if not j["done"]), key=self._rank)
                                   if j is not self.active][:6]},
                # events[n0:n1] happened at this instant
                "n0": self.snapshots[-1]["n1"] if self.snapshots else 0, "n1": len(self.events)}
        if self.snapshots and abs(self.snapshots[-1]["t"] - self.now) < EPS:
            snap["layers"] = {**self.snapshots[-1]["layers"], **changed}
            snap["n0"] = self.snapshots[-1]["n0"]
            self.snapshots[-1] = snap
        else:
            self.snapshots.append(snap)

    def run(self, steps: int) -> dict:
        proc = self._process(steps)
        wake_at: float | None = None
        waiting: list[int] = []
        seg: dict | None = None
        alive = True

        def resume() -> None:
            nonlocal wake_at, waiting, seg, alive
            while alive:
                if seg:
                    seg["t1"] = self.now
                    if seg["t1"] - seg["t0"] > EPS:
                        self.compute_segments.append(seg)
                        if seg["phase"].startswith("wait_"):
                            self.m[seg["phase"] + "_ms"] += seg["t1"] - seg["t0"]
                    seg = None
                try:
                    op, arg, phase = next(proc)
                except StopIteration:
                    alive = False
                    return
                self.compute["phase"] = phase
                seg = {"phase": phase, "step": self.compute["step"], "layer": self.compute["layer"], "t0": self.now, "t1": None}
                if op == "delay":
                    wake_at, waiting = self.now + arg, []
                    return
                wake_at, waiting = None, arg
                if any(not self.jobs[j]["done"] for j in waiting):
                    return

        try:
            self._snapshot()
            self._check_fits()
            resume()
            self._snapshot()
            while True:
                times = [t for t in (wake_at, self._link_finish_time()) if t is not None]
                if not times:
                    break
                self.now = min(times)
                self._advance_link(self.now)
                # Compare times, not remaining bytes: a fast link's finish time can round to `now`.
                if self.active and self._link_finish_time() <= self.now + EPS:
                    self._complete(self.active)
                if alive and ((wake_at is not None and wake_at <= self.now + EPS)
                              or (waiting and all(self.jobs[j]["done"] for j in waiting))):
                    wake_at = None
                    resume()
                self._snapshot()
        except CapacityError as error:
            self.error = str(error)
            self.compute["phase"] = "failed"
            self._event("capacity_error", self.error)
            self._close_link_segment()
            self._snapshot()
            return self._result()
        if alive:
            raise ModelError("simulation stalled before decode finished")
        moved = sum(self.m["link_bytes"].values())
        if moved > self.link_busy_ms * self._rate() * (1 + 1e-9) + 1:
            raise ModelError("link moved more bytes than its bandwidth allows")
        return self._result()

    def _per_step(self) -> list[dict]:
        """Per-step compute, waits, bytes, link use, hit rates, evictions and cache occupancy."""
        out, prev = [], {"end_ms": 0.0, "kv_hits": 0, "kv_lookups": 0, "evicted_experts": 0, "evicted_kv": 0,
                         "link_bytes": {k: 0.0 for k in KINDS}, "link_busy_ms": 0.0}
        by_step: dict[int, dict] = {}
        for seg in self.compute_segments:
            acc = by_step.setdefault(seg["step"], {})
            key = "compute_ms" if seg["phase"] in PHASES_COMPUTE else seg["phase"] + "_ms"
            acc[key] = acc.get(key, 0.0) + seg["t1"] - seg["t0"]
        for k, mark in enumerate(self.step_marks):
            acc = by_step.get(k, {})
            dur = mark["end_ms"] - prev["end_ms"]
            moved = {kind: mark["link_bytes"][kind] - prev["link_bytes"][kind] for kind in KINDS}
            kv_l = mark["kv_lookups"] - prev["kv_lookups"]
            out.append({
                "step": k + 1, "token_ms": round(dur, 6), "compute_ms": round(acc.get("compute_ms", 0.0), 6),
                "wait_base_ms": round(acc.get("wait_base_ms", 0.0), 6), "wait_kv_ms": round(acc.get("wait_kv_ms", 0.0), 6),
                "wait_experts_ms": round(acc.get("wait_experts_ms", 0.0), 6),
                "link_bytes": {kind: round(v) for kind, v in moved.items()}, "link_total_bytes": round(sum(moved.values())),
                "link_utilization": round((mark["link_busy_ms"] - prev["link_busy_ms"]) / dur, 6) if dur > 0 else None,
                "expert_hits": mark["expert_hits"], "expert_lookups": mark["expert_lookups"],
                "expert_hit_rate": round(mark["expert_hits"] / mark["expert_lookups"], 6) if mark["expert_lookups"] else None,
                "kv_hit_rate": round((mark["kv_hits"] - prev["kv_hits"]) / kv_l, 6) if kv_l else None,
                "evicted_experts": mark["evicted_experts"] - prev["evicted_experts"],
                "evicted_kv": mark["evicted_kv"] - prev["evicted_kv"],
                "cache_experts": mark["cache_experts"], "cache_slots": self.expert_slots,
                "tier1_bytes": round(mark["tier1_bytes"]),
            })
            prev = mark
        cumulative = 0
        for row in out:
            cumulative += row["evicted_experts"]
            if row["step"] == 1:
                row["phase"] = "cold"
            elif self.cfg.expert_cache == "per_layer":
                row["phase"] = "no_cache"
            elif cumulative == 0:
                row["phase"] = "filling"
            else:
                row["phase"] = "evicting"
        return out

    @staticmethod
    def steady_state(per_step: list[dict], window: int = 6, tolerance: float = 0.05) -> dict:
        """Steady state is claimed only if the last `window` steps vary by at most `tolerance` and none is cold or filling."""
        tail = per_step[-window:]
        if len(per_step) < window + 1 or any(r["phase"] in ("cold", "filling") for r in tail):
            return {"reached": False, "reason": f"Fewer than {window} steps after the cache filling phase", "window": window}
        times = [r["token_ms"] for r in tail]
        mean = sum(times) / len(times)
        spread = (max(times) - min(times)) / mean if mean else 0.0
        if spread > tolerance:
            return {"reached": False, "reason": f"Variation of {spread:.1%} over the last {window} steps exceeds {tolerance:.0%}", "window": window}
        return {"reached": True, "from_step": tail[0]["step"], "window": window, "spread": round(spread, 6),
                "token_ms": round(mean, 6),
                "expert_hit_rate": round(sum(r["expert_hits"] for r in tail) / max(sum(r["expert_lookups"] for r in tail), 1), 6)}

    def _contention_bound_ms(self) -> float:
        """Upper bound on extra compute time if copies into tier 1 steal tier-1 read bandwidth from compute."""
        ratio = self.hw.copy_bandwidth / self.hw.tier1_bandwidth
        links = sorted((s["t0"], s["t1"]) for s in self.link_segments if s["t1"] is not None)
        total, j = 0.0, 0
        for seg in sorted((s for s in self.compute_segments if s["phase"] in PHASES_COMPUTE), key=lambda s: s["t0"]):
            while j < len(links) and links[j][1] <= seg["t0"]:
                j += 1
            k = j
            while k < len(links) and links[k][0] < seg["t1"]:
                total += max(0.0, min(seg["t1"], links[k][1]) - max(seg["t0"], links[k][0]))
                k += 1
        return total * min(ratio, 1.0)

    def _result(self) -> dict:
        m, p = self.m, self.p
        tokens = self.token_ms
        per_step = self._per_step()

        def rate(hits: int, lookups: int) -> float | None:
            return round(hits / lookups, 6) if lookups else None

        compute_ms = sum(s["t1"] - s["t0"] for s in self.compute_segments if s["phase"] in PHASES_COMPUTE)
        metrics = {
            "token_ms": [round(t, 6) for t in tokens],
            "mean_token_ms": round(sum(tokens) / len(tokens), 6) if tokens else None,
            "steady": self.steady_state(per_step) if per_step else {"reached": False, "reason": "No completed steps"},
            "native_token_ms": round(p.native_step_ms, 6),
            "total_ms": round(self.now, 6), "compute_ms": round(compute_ms, 6),
            "wait_base_ms": round(m["wait_base_ms"], 6), "wait_kv_ms": round(m["wait_kv_ms"], 6),
            "wait_experts_ms": round(m["wait_experts_ms"], 6),
            "expert_lookups": m["expert_lookups"], "expert_hits": m["expert_hits"], "expert_late": m["expert_late"],
            "expert_hit_rate": rate(m["expert_hits"], m["expert_lookups"]),
            "expert_prefetched": m["expert_prefetched"], "expert_prefetch_used": m["expert_prefetch_used"],
            "kv_lookups": m["kv_lookups"], "kv_hits": m["kv_hits"], "kv_hit_rate": rate(m["kv_hits"], m["kv_lookups"]),
            "base_prefetches": m["base_prefetches"], "base_late": m["base_late"],
            "evicted_experts": self.evicted_experts, "released_experts": self.released_experts, "evicted_kv": self.evicted_kv,
            "link_bytes": {k: round(v) for k, v in m["link_bytes"].items()},
            "link_total_bytes": round(sum(m["link_bytes"].values())),
            "link_busy_ms": round(self.link_busy_ms, 6),
            "link_utilization": round(self.link_busy_ms / self.now, 6) if self.now > 0 else None,
            "tier1_contention_bound_ms": round(self._contention_bound_ms(), 6),
            "peak_tier1_bytes": round(self.peak_tier1),
            "expert_cache_bytes": round(self.expert_cap), "expert_cache_slots": self.expert_slots,
            "copy_bandwidth": self.hw.copy_bandwidth,
        }
        result = {"error": self.error, "feasible": not self.infeasible and not self.error, "infeasible": self.infeasible,
                  "metrics": metrics, "per_step": per_step}
        if self.cfg.trace_detail == "full":
            for seg in self.compute_segments + self.link_segments:
                for key in ("t0", "t1", "f0", "f1", "setup"):
                    if isinstance(seg.get(key), float):
                        seg[key] = round(seg[key], 9)
            for event in self.events:
                event["t"] = round(event["t"], 9)
            jobs = [{"id": j["id"], "cls": j["cls"], "kind": j["kind"], "bytes": round(j["bytes"]), "label": j["label"],
                     "queued": round(j["queued"], 9), "end": None if j["end"] is None else round(j["end"], 9)} for j in self.jobs]
            result.update(events=self.events, snapshots=self.snapshots, compute_segments=self.compute_segments,
                          link_segments=self.link_segments, jobs=jobs)
        return result


def simulate(cfg: TwoTierConfig, profile: ModelProfile, steps: int | None = None) -> dict:
    """Re-time `steps` decode steps of one request. A capacity failure is returned as `error` with the partial trace."""
    if steps is not None:
        cfg = cfg.with_steps(steps)
    return TwoTierSim(cfg, profile).run(cfg.max_decode_steps)
