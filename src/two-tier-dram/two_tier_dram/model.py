"""Per-layer re-timing of decode on a two-tier DRAM system.

AISim prices a decode pass as one number and assumes every weight and KV byte
is already in device memory. This model replays the same decode steps layer by
layer on a small fast tier 1 and a large slow tier 2 joined by one shared link:

    [base weights resident?] -> top-k select (csa) -> fetch missing KV -> attention
        -> route -> fetch missing experts -> MoE

Tier 1 holds scratch, non-expert weights (all layers, or the current layer plus
a prefetched next layer), the KV every step reads in full, an LRU cache of
routed experts, and an LRU cache of sparse top-k KV entries. Tier 2 holds
everything. Compute times, byte sizes and model geometry come from a
`ModelProfile`, which AISim supplies in production (see profile.py).

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

EPS = 1e-9
PRIORITY = {"demand": 0, "prefetch": 1, "writeback": 2}
KINDS = ("demand_base", "prefetch_base", "demand_kv", "demand_expert", "prefetch_expert", "writeback")


class ModelError(Exception):
    """An invariant of the model was violated."""


class CapacityError(Exception):
    """A tier cannot hold what the workload needs."""


class TwoTierSim:
    def __init__(self, cfg: TwoTierConfig, profile: ModelProfile):
        self.cfg, self.p = cfg, profile
        self.n = len(profile.layers)
        self.now = 0.0
        self.resident_base = cfg.base_weights == "resident"
        self.bundles: dict[int, dict] = {}  # layer -> {state, role, job}; layer_prefetch only
        self.experts: OrderedDict[tuple[int, int], dict] = OrderedDict()  # (layer, expert) -> {state, pinned, job}
        self.kv: OrderedDict[tuple[int, int], bool] = OrderedDict()  # (layer, entry) -> pinned
        self.kv_loading = 0
        self.expert_count = [0] * self.n  # per-layer entries in the expert cache, loading included
        self.kv_count = [0] * self.n  # per-layer resident hot-KV entries
        self.evicted_experts = self.evicted_kv = 0
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
        self.fixed_bytes = cfg.scratch_gb * GB + p.global_bytes
        self.static_bytes = sum(l.static_kv_bytes for l in p.layers)
        if self.resident_base:
            self.static_bytes += sum(l.indexer_bytes for l in p.layers)
            self.base_reserved = sum(l.base_bytes for l in p.layers)
        else:
            self.base_reserved = 2 * max(l.base_bytes + l.indexer_bytes for l in p.layers)
        hot_kv_reserved = max(cfg.hot_kv_entries, p.index_topk) * p.kv_entry_bytes
        left = cfg.tier1_gb * GB - self.fixed_bytes - self.static_bytes - self.base_reserved - hot_kv_reserved - 64 * p.new_token_kv_bytes
        self.expert_cap = max(min(left, cfg.expert_cache_gb * GB) if cfg.expert_cache_gb else left, 0.0)

    def _check_fits(self) -> None:
        """Static capacity checks, run before the first step so a failure still yields a trace."""
        p, cfg = self.p, self.cfg
        full = p.full_weights_bytes + p.full_kv_bytes
        if full > cfg.tier2_gb * GB:
            raise CapacityError(f"二级 DRAM 放不下完整权重与 KV：需要 {full / GB:.1f} GB，只有 {cfg.tier2_gb:g} GB")
        need = p.experts_per_token * p.expert_bytes
        if self.expert_cap < need:
            raise CapacityError(
                f"一级 DRAM 放不下一层的路由专家：scratch 与全局权重 {self.fixed_bytes / GB:.1f} GB、常驻 KV {self.static_bytes / GB:.2f} GB、"
                f"非专家权重 {self.base_reserved / GB:.1f} GB 之后，专家缓存只剩 {self.expert_cap / GB:.2f} GB，一层需要 {need / GB:.2f} GB")

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
        if used > self.cfg.tier1_gb * GB + 1:
            raise CapacityError(f"一级 DRAM 容量不足：{what} 后需要 {used / GB:.2f} GB，只有 {self.cfg.tier1_gb:g} GB")
        self.peak_tier1 = max(self.peak_tier1, used)

    def _evict_experts_for(self, incoming: int) -> None:
        eb = self.p.expert_bytes
        while (len(self.experts) + incoming) * eb > self.expert_cap + 1:
            victim = next((k for k, e in self.experts.items() if e["state"] == "resident" and not e["pinned"]), None)
            if victim is None:
                raise CapacityError(f"专家缓存放不下：需要再放 {incoming} 个专家，缓存上限 {self.expert_cap / GB:.2f} GB，没有可淘汰的专家")
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
               "setup_left": self.cfg.link_overhead_ms, "urgent": False, "done": False,
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
            self._event("link_preempt", f"链路让路：{self.active['label']} 暂停，让给 {best['label']}")
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
        return self.cfg.link_gbps * 1e6  # bytes per ms

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
            self._event("base_arrive", f"第 {eff['bundle']} 层的非专家权重到达一级")
        elif "kv" in eff:
            layer, entries = eff["kv"]
            self.kv_loading -= len(entries)
            for entry in entries:
                self.kv[(layer, entry)] = True
            self.kv_count[layer] += len(entries)
            self._touched.add(layer)
            self._event("kv_arrive", f"第 {layer} 层缺失的 {len(entries)} 条 top-k KV 到达一级")
        elif "experts" in eff:
            layer, ids = eff["experts"]
            for i in ids:
                if (layer, i) in self.experts:
                    self.experts[(layer, i)]["state"] = "resident"
            self._touched.add(layer)
            verb = "预取的" if job["cls"] == "prefetch" else "缺失的"
            self._event("experts_arrive", f"第 {layer} 层{verb} {len(ids)} 个专家到达一级：" + ", ".join(f"e{i}" for i in ids))
        elif "writeback" in eff:
            self.dirty_bytes -= eff["writeback"]
            self.synced_tokens += 1
            self._event("writeback_done", "新 token 的 KV 写回二级完成")
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
        self._check_tier1(f"为第 {layer} 层的非专家权重预留空间")
        kind = "prefetch_base" if cls == "prefetch" else "demand_base"
        verb = "预取" if cls == "prefetch" else "按需取"
        job = self._enqueue(cls, kind, l.base_bytes + l.indexer_bytes, f"{verb} L{layer} 非专家权重", {"bundle": layer})
        self.bundles[layer]["job"] = job["id"]
        self._touched.add(layer)
        return job

    def _prefetch_experts(self, layer: int) -> None:
        predicted = [i for i in self._prev_experts.get(layer, []) if (layer, i) not in self.experts]
        if not predicted:
            return
        self._evict_experts_for(len(predicted))
        job = self._enqueue("prefetch", "prefetch_expert", len(predicted) * self.p.expert_bytes,
                            f"预取 L{layer} 专家 ×{len(predicted)}", {"experts": (layer, predicted)})
        for i in predicted:
            self.experts[(layer, i)] = {"state": "loading", "pinned": False, "job": job["id"], "prefetched": True}
        self.expert_count[layer] += len(predicted)
        self.m["expert_prefetched"] += len(predicted)
        self._touched.add(layer)
        self._check_tier1("为预取的专家预留空间")
        self._event("expert_prefetch", f"按上一步的路由预取第 {layer} 层的 {len(predicted)} 个专家")

    def _process(self, steps: int):
        p, cfg = self.p, self.cfg
        for step in range(steps):
            step_start = self.now
            for layer, l in enumerate(p.layers):
                self.compute.update(step=step, layer=layer)
                self.detail = {"experts": [], "kv": None}
                last = step == steps - 1 and layer == self.n - 1
                # 1. non-expert weights of this layer
                if not self.resident_base:
                    bundle = self.bundles.get(layer)
                    if bundle is None:
                        job = self._fetch_bundle(layer, "demand", "current")
                        self._event("base_miss", f"第 {layer} 层的非专家权重不在一级，按需取入，计算等待")
                        yield ("wait", [job["id"]], "wait_base")
                    elif bundle["state"] == "loading":
                        job = self.jobs[bundle["job"]]
                        job["urgent"] = True
                        self.m["base_late"] += 1
                        self._event("base_late", f"第 {layer} 层的权重预取没有按时完成，计算等待")
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
                    self._event("topk", f"indexer 选出 top-k {len(picks)} 条：命中 {hits}，缺失 {len(missing)}")
                    if missing:
                        self._evict_kv_for(len(missing))
                        self.kv_loading += len(missing)
                        self._check_tier1("为缺失的 top-k KV 预留空间")
                        job = self._enqueue("demand", "demand_kv", len(missing) * p.kv_entry_bytes,
                                            f"按需取 L{layer} top-k KV ×{len(missing)}", {"kv": (layer, missing)})
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
                self.m["expert_late"] += late
                if missing:
                    self._evict_experts_for(len(missing))
                    job = self._enqueue("demand", "demand_expert", len(missing) * p.expert_bytes,
                                        f"按需取 L{layer} 专家 ×{len(missing)}", {"experts": (layer, missing)})
                    for i in missing:
                        self.experts[(layer, i)] = {"state": "loading", "pinned": True, "job": job["id"]}
                    self.expert_count[layer] += len(missing)
                    waits.append(job["id"])
                    self._check_tier1("为缺失的专家预留空间")
                self._touched.add(layer)
                self.detail["experts"] = [{"id": i, "was": "miss" if i in missing else "hit"} for i in routed]
                self._event("route", f"router 选出专家 {', '.join(f'e{i}' for i in routed)}：命中 {hits}，"
                                     f"缺失 {len(missing)}" + (f"，预取未到 {late}" if late else ""))
                if waits:
                    self._pick()
                    yield ("wait", waits, "wait_experts")
                if any(self.experts[(layer, i)]["state"] != "resident" for i in routed):
                    raise ModelError(f"MoE at layer {layer} started before its experts arrived")
                yield ("delay", l.moe_ms, "moe")
                # 4. layer done
                for i in routed:
                    self.experts[(layer, i)]["pinned"] = False
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
            self._check_tier1("写入新 token 的 KV")
            self._enqueue("writeback", "writeback", p.new_token_kv_bytes, f"写回 step {step + 1} 新 token 的 KV",
                          {"writeback": p.new_token_kv_bytes})
            self.token_ms.append(self.now - step_start)
            self.compute["layer"] = None
            self._event("token", f"第 {step + 1} 个 decode step 完成：{self.now - step_start:.3f} ms"
                                 f"（AISim 原生 {p.native_step_ms:.3f} ms）")
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
        snap = {"t": self.now, "compute": dict(self.compute), "detail": detail, "layers": changed,
                "tier1": self.tier1(), "tier2": {"dirty_bytes": self.dirty_bytes, "synced_tokens": self.synced_tokens},
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

    def _result(self) -> dict:
        m, p = self.m, self.p
        tokens = self.token_ms

        def rate(hits: int, lookups: int) -> float | None:
            return round(hits / lookups, 6) if lookups else None

        metrics = {
            "token_ms": [round(t, 6) for t in tokens],
            "mean_token_ms": round(sum(tokens) / len(tokens), 6) if tokens else None,
            "steady_token_ms": round(sum(tokens[1:]) / len(tokens[1:]), 6) if len(tokens) > 1 else None,
            "native_token_ms": round(p.native_step_ms, 6),
            "total_ms": round(self.now, 6),
            "wait_base_ms": round(m["wait_base_ms"], 6), "wait_kv_ms": round(m["wait_kv_ms"], 6),
            "wait_experts_ms": round(m["wait_experts_ms"], 6),
            "expert_lookups": m["expert_lookups"], "expert_hits": m["expert_hits"], "expert_late": m["expert_late"],
            "expert_hit_rate": rate(m["expert_hits"], m["expert_lookups"]),
            "expert_prefetched": m["expert_prefetched"], "expert_prefetch_used": m["expert_prefetch_used"],
            "kv_lookups": m["kv_lookups"], "kv_hits": m["kv_hits"], "kv_hit_rate": rate(m["kv_hits"], m["kv_lookups"]),
            "base_prefetches": m["base_prefetches"], "base_late": m["base_late"],
            "evicted_experts": self.evicted_experts, "evicted_kv": self.evicted_kv,
            "link_gb": {k: round(v / GB, 6) for k, v in m["link_bytes"].items()},
            "link_busy_ms": round(self.link_busy_ms, 6),
            "peak_tier1_gb": round(self.peak_tier1 / GB, 6),
            "expert_cache_gb": round(self.expert_cap / GB, 6),
            "expert_cache_slots": int(self.expert_cap // p.expert_bytes),
        }
        jobs = [{k: j[k] for k in ("id", "cls", "kind", "bytes", "label", "queued", "end")} for j in self.jobs]
        return {"error": self.error, "metrics": metrics, "events": self.events, "snapshots": self.snapshots,
                "compute_segments": self.compute_segments, "link_segments": self.link_segments, "jobs": jobs}


def simulate(cfg: TwoTierConfig, profile: ModelProfile, steps: int | None = None) -> dict:
    """Re-time `steps` decode steps of one request. A tier-1 overflow is returned as `error` with the partial trace."""
    return TwoTierSim(cfg, profile).run(steps or cfg.max_decode_steps)
