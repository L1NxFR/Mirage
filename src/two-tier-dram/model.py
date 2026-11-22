"""Discrete-event model of decode on a two-tier DRAM system.

Tier 1 is a small, fast DRAM (3D-stacked) that compute reads directly. Tier 2
is a large, slower DRAM (LPDDR) holding every layer's weights and the full KV.
One shared link moves data between them. Per decode step, per layer:

    weights resident? -> indexer -> top-k select -> fetch missing KV -> attention -> MoE

Scheme A from the design note: tier 1 keeps the current layer's bundle (weights
+ indexer KV) and prefetches the next layer's bundle while the current layer
computes. A software hot-KV cache keeps fetched attention KV across steps.

The model owns its state, so every snapshot is exact. When tier 1 cannot hold
what a step needs, the run stops and returns `error` with the trace so far. It
raises ModelError when an invariant breaks (compute before data arrived, link
faster than its bandwidth) and CapacityError when tier 2 is too small to start.

Simplifications, on purpose for a first, inspectable model:
  * one request, batch 1, fixed per-phase compute times (no AISim perf model);
  * a layer bundle is one transfer; MoE experts are not tracked individually;
  * top-k picks only from the initial context; newly generated tokens' KV is
    modelled as a dirty tier-1 entry plus a writeback, not as a top-k candidate;
  * a preempted transfer resumes without paying the setup cost again.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass

EPS = 1e-9
PRIORITY = {"demand": 0, "prefetch": 1, "writeback": 2}


class ModelError(Exception):
    """An invariant of the model was violated."""


class CapacityError(Exception):
    """Tier 1 or tier 2 cannot hold the data the workload needs."""


@dataclass(frozen=True)
class Config:
    # workload
    layers: int = 4
    steps: int = 3
    context_tokens: int = 12
    topk: int = 4
    overlap: float = 0.75  # chance a layer keeps each top-k token from its previous step
    seed: int = 0
    # sizes (MB)
    weight_mb: float = 8.0
    indexer_kv_mb: float = 1.0
    kv_entry_mb: float = 0.5  # one token's attention KV for one layer
    scratch_mb: float = 2.0
    tier1_mb: float = 32.0
    tier2_mb: float = 256.0
    # shared tier-2 -> tier-1 link
    link_mb_per_ms: float = 4.0
    link_setup_ms: float = 0.2  # fixed cost per transfer, paid serially
    link_policy: str = "demand_first"  # or "fifo"
    # compute (ms per layer)
    t_indexer_ms: float = 1.0
    t_attention_ms: float = 2.0
    t_moe_ms: float = 3.0
    # policies
    prefetch: bool = True
    hot_kv_entries: int = 24  # soft cap on cached attention-KV entries; 0 disables the cache

    @property
    def bundle_mb(self) -> float:
        return self.weight_mb + self.indexer_kv_mb


class Simulator:
    def __init__(self, cfg: Config):
        if cfg.link_policy not in ("demand_first", "fifo"):
            raise ValueError(f"unknown link_policy {cfg.link_policy!r}")
        self.cfg = cfg
        self.now = 0.0
        self.bundles: dict[int, dict] = {}  # layer -> {state, role, job}
        self.kv: dict[tuple[int, int], dict] = {}  # (layer, token) -> {state, dirty, pinned, used}
        self.jobs: list[dict] = []
        self.active: dict | None = None
        self.link_clock = 0.0
        self.link_busy_ms = 0.0
        self.use_counter = 0
        self.synced_new_kv = 0
        self.compute = {"step": None, "layer": None, "phase": "idle"}
        self.compute_segments: list[dict] = []
        self.link_segments: list[dict] = []
        self.events: list[dict] = []
        self.snapshots: list[dict] = []
        self.peak_tier1 = 0.0
        self.error: str | None = None
        self.m = {"lookups": 0, "hits": 0, "prefetches": 0, "prefetch_late": 0, "prefetch_skipped": 0,
                  "wait_weights_ms": 0.0, "wait_kv_ms": 0.0, "token_ms": [],
                  "link_mb": {"demand_weights": 0.0, "demand_kv": 0.0, "prefetch": 0.0, "writeback": 0.0}}
        self._rng = [random.Random(cfg.seed * 1009 + layer) for layer in range(cfg.layers)]
        self._prev_sel: dict[int, list[int]] = {}
        self._ever_sel: dict[int, set[int]] = {layer: set() for layer in range(cfg.layers)}
        full = cfg.layers * cfg.bundle_mb + cfg.layers * (cfg.context_tokens + cfg.steps) * cfg.kv_entry_mb
        if full > cfg.tier2_mb + EPS:
            raise CapacityError(f"二级 DRAM 放不下完整模型与 KV：需要 {full:g} MB，只有 {cfg.tier2_mb:g} MB")
        self.tier2_full_mb = full

    # ---- tier-1 ledger -------------------------------------------------
    def tier1_breakdown(self) -> dict:
        c = self.cfg
        cur = sum(c.bundle_mb for b in self.bundles.values() if b["role"] == "current")
        pre = sum(c.bundle_mb for b in self.bundles.values() if b["role"] == "prefetch")
        return {"scratch": c.scratch_mb, "current_bundle": cur, "prefetch_bundle": pre,
                "hot_kv": len(self.kv) * c.kv_entry_mb}

    def tier1_used(self) -> float:
        return sum(self.tier1_breakdown().values())

    def _check_tier1(self, what: str) -> None:
        used = self.tier1_used()
        if used > self.cfg.tier1_mb + EPS:
            raise CapacityError(f"一级 DRAM 容量不足：{what} 后需要 {used:g} MB，只有 {self.cfg.tier1_mb:g} MB")
        self.peak_tier1 = max(self.peak_tier1, used)

    def _evictable(self) -> list[tuple[int, int]]:
        keys = [k for k, e in self.kv.items() if e["state"] == "resident" and not e["pinned"] and not e["dirty"]]
        return sorted(keys, key=lambda k: self.kv[k]["used"])

    def _evict(self, key: tuple[int, int], why: str) -> None:
        del self.kv[key]
        self._event("kv_evict", f"热 KV 淘汰 L{key[0]}·t{key[1]}（{why}）")

    def _make_room_for_kv(self, incoming: int) -> None:
        """Honor the soft cache cap first, then the hard tier-1 capacity."""
        c = self.cfg
        cap = max(c.hot_kv_entries, 0)
        while len(self.kv) + incoming > cap and (victims := self._evictable()):
            self._evict(victims[0], "LRU，缓存已到软上限")
        while self.tier1_used() + incoming * c.kv_entry_mb > c.tier1_mb + EPS:
            victims = self._evictable()
            if not victims:
                need = self.tier1_used() + incoming * c.kv_entry_mb
                raise CapacityError(f"一级 DRAM 容量不足：取入 {incoming} 条 KV 需要 {need:g} MB，"
                                    f"只有 {c.tier1_mb:g} MB，且没有可淘汰的条目")
            self._evict(victims[0], "一级容量不足")

    # ---- shared link ---------------------------------------------------
    def _enqueue(self, cls: str, kind: str, mb: float, label: str, effect: dict) -> dict:
        job = {"id": len(self.jobs), "cls": cls, "kind": kind, "mb": mb, "left": mb, "label": label,
               "setup_left": self.cfg.link_setup_ms, "urgent": False, "done": False,
               "queued": self.now, "end": None, "effect": effect}
        self.jobs.append(job)
        self._pick()
        return job

    def _rank(self, job: dict) -> tuple:
        if self.cfg.link_policy == "fifo":
            return (0, job["id"])
        return (0 if job["urgent"] else PRIORITY[job["cls"]], job["id"])

    def _pick(self) -> None:
        pending = [j for j in self.jobs if not j["done"]]
        if self.cfg.link_policy == "fifo" and self.active and not self.active["done"]:
            return  # non-preemptive
        best = min(pending, key=self._rank) if pending else None
        if best is self.active:
            return
        if self.active and not self.active["done"]:
            self._event("link_preempt", f"链路让路：{self.active['label']} 暂停，让给 {best['label']}")
        self._close_link_segment()
        self.active = best
        if best:
            self.link_segments.append({"job": best["id"], "kind": best["kind"], "label": best["label"],
                                       "t0": self.now, "t1": None, "f0": 1 - best["left"] / best["mb"],
                                       "f1": None, "setup": best["setup_left"]})

    def _close_link_segment(self) -> None:
        if self.link_segments and self.link_segments[-1]["t1"] is None:
            seg, job = self.link_segments[-1], self.jobs[self.link_segments[-1]["job"]]
            seg["t1"], seg["f1"] = self.now, 1 - job["left"] / job["mb"]
            if seg["t1"] - seg["t0"] < EPS:
                self.link_segments.pop()

    def _advance_link(self, to: float) -> None:
        dt = to - self.link_clock
        self.link_clock = to
        job = self.active
        if not job or dt <= 0:
            return
        self.link_busy_ms += dt
        setup = min(dt, job["setup_left"])
        job["setup_left"] -= setup
        moved = min(job["left"], (dt - setup) * self.cfg.link_mb_per_ms)
        job["left"] -= moved
        self.m["link_mb"][job["kind"]] += moved

    def _link_finish_time(self) -> float | None:
        job = self.active
        return None if not job else self.now + job["setup_left"] + job["left"] / self.cfg.link_mb_per_ms

    def _complete(self, job: dict) -> None:
        job["done"], job["end"], job["left"] = True, self.now, 0.0
        eff = job["effect"]
        if "bundle" in eff:
            self.bundles[eff["bundle"]]["state"] = "resident"
            self._event("bundle_arrive", f"第 {eff['bundle']} 层的权重与 indexer KV 到达一级")
        elif "kv" in eff:
            for key in eff["kv"]:
                self.kv[key]["state"] = "resident"
            self._event("kv_arrive", f"缺失的 {len(eff['kv'])} 条 KV 到达一级：" + self._fmt(eff["kv"]))
        elif "writeback" in eff:
            key = eff["writeback"]
            if key in self.kv:
                self.kv[key]["dirty"] = False
            self.synced_new_kv += 1
            self._event("writeback_done", f"L{key[0]}·t{key[1]} 写回二级完成，一级副本变为干净")
            if self.cfg.hot_kv_entries <= 0 and key in self.kv and not self.kv[key]["pinned"]:
                self._evict(key, "未启用热 KV 缓存，写回后丢弃")
        self._close_link_segment()
        self.active = None
        self._pick()

    # ---- compute -------------------------------------------------------
    @staticmethod
    def _fmt(keys) -> str:
        return ", ".join(f"t{t}" for _, t in sorted(keys))

    def _event(self, kind: str, text: str) -> None:
        self.events.append({"t": self.now, "kind": kind, "text": text,
                            "step": self.compute["step"], "layer": self.compute["layer"]})

    def _select(self, layer: int) -> list[int]:
        """Synthetic top-k: keep each previous pick with probability `overlap`, fill with never-used context tokens."""
        c, rng = self.cfg, self._rng[layer]
        tokens = list(range(c.context_tokens))
        k = min(c.topk, len(tokens))
        prev = self._prev_sel.get(layer)
        keep = [t for t in prev if rng.random() < c.overlap] if prev else []
        fresh = [t for t in tokens if t not in self._ever_sel[layer]]
        pool = fresh if len(fresh) >= k - len(keep) else [t for t in tokens if t not in keep]
        sel = sorted(keep + rng.sample(pool, k - len(keep)))
        self._prev_sel[layer] = sel
        self._ever_sel[layer].update(sel)
        return sel

    def _fetch_bundle(self, layer: int, cls: str, role: str) -> dict:
        c = self.cfg
        self.bundles[layer] = {"state": "loading", "role": role, "job": None}
        self._check_tier1(f"为第 {layer} 层权重预留空间")
        kind = "prefetch" if cls == "prefetch" else "demand_weights"
        verb = "预取" if cls == "prefetch" else "按需取"
        job = self._enqueue(cls, kind, c.bundle_mb, f"{verb} L{layer} 权重+idx KV", {"bundle": layer})
        self.bundles[layer]["job"] = job["id"]
        return job

    def _try_prefetch(self, layer: int) -> None:
        c = self.cfg
        if layer in self.bundles:
            return
        if self.tier1_used() + c.bundle_mb > c.tier1_mb + EPS:
            self.m["prefetch_skipped"] += 1
            self._event("prefetch_skipped", f"一级放不下第 {layer} 层的预取缓冲，跳过预取，到时按需取入")
            return
        self.m["prefetches"] += 1
        self._fetch_bundle(layer, "prefetch", "prefetch")
        self._event("prefetch_start", f"开始预取第 {layer} 层的权重与 indexer KV（与当前层计算重叠）")

    def _process(self):
        c = self.cfg
        for step in range(c.steps):
            step_start = self.now
            for layer in range(c.layers):
                self.compute.update(step=step, layer=layer)
                # 1. the layer's weights and indexer KV must be resident
                bundle = self.bundles.get(layer)
                if bundle is None:
                    job = self._fetch_bundle(layer, "demand", "current")
                    self._event("weights_miss", f"第 {layer} 层权重不在一级，按需从二级取入，计算等待")
                    yield ("wait", job["id"], "wait_weights")
                elif bundle["state"] == "loading":
                    job = self.jobs[bundle["job"]]
                    job["urgent"] = True
                    self.m["prefetch_late"] += 1
                    self._event("prefetch_late", f"第 {layer} 层的预取没有按时完成，计算等待，传输提为最高优先级")
                    self._pick()
                    yield ("wait", job["id"], "wait_weights")
                if self.bundles[layer]["state"] != "resident":
                    raise ModelError(f"layer {layer} started before its weights arrived")
                self.bundles[layer]["role"] = "current"
                last = step == c.steps - 1 and layer == c.layers - 1
                if c.prefetch and c.layers > 1 and not last:
                    self._try_prefetch((layer + 1) % c.layers)
                # 2. indexer picks the top-k KV
                yield ("delay", c.t_indexer_ms, "indexer")
                sel = [(layer, t) for t in self._select(layer)]
                missing = [k for k in sel if k not in self.kv]
                hits = [k for k in sel if k in self.kv]
                self.m["lookups"] += len(sel)
                self.m["hits"] += len(hits)
                for key in hits:
                    self.use_counter += 1
                    self.kv[key].update(pinned=True, used=self.use_counter)
                self._event("topk", f"indexer 选出 top-k：{self._fmt(sel)}；命中 {len(hits)}，缺失 {len(missing)}")
                # 3. attention waits for the missing KV
                if missing:
                    self._make_room_for_kv(len(missing))
                    for key in missing:
                        self.use_counter += 1
                        self.kv[key] = {"state": "loading", "dirty": False, "pinned": True, "used": self.use_counter}
                    self._check_tier1("为缺失 KV 预留空间")
                    job = self._enqueue("demand", "demand_kv", len(missing) * c.kv_entry_mb,
                                        f"按需取 L{layer} KV {self._fmt(missing)}", {"kv": missing})
                    yield ("wait", job["id"], "wait_kv")
                if any(self.kv[k]["state"] != "resident" for k in sel):
                    raise ModelError(f"attention at layer {layer} started before its KV arrived")
                yield ("delay", c.t_attention_ms, "attention")
                yield ("delay", c.t_moe_ms, "moe")
                # 4. layer done: unpin, write the new token's KV, release the layer's weights
                for key in sel:
                    self.kv[key]["pinned"] = False
                new = (layer, c.context_tokens + step)
                self._make_room_for_kv(1)
                self.use_counter += 1
                self.kv[new] = {"state": "resident", "dirty": True, "pinned": False, "used": self.use_counter}
                self._check_tier1("写入新 token 的 KV")
                self._enqueue("writeback", "writeback", c.kv_entry_mb, f"写回 L{layer}·t{new[1]}", {"writeback": new})
                self._event("layer_done", f"第 {layer} 层完成：新 token t{new[1]} 的 KV 写入一级（脏），排队写回二级")
                if c.hot_kv_entries <= 0:
                    for key in [k for k in sel if k in self.kv]:
                        self._evict(key, "未启用热 KV 缓存，用完即丢")
                if c.layers > 1:
                    del self.bundles[layer]
                    self._event("bundle_release", f"释放第 {layer} 层的权重与 indexer KV")
            self.m["token_ms"].append(self.now - step_start)
            self._event("token", f"第 {step} 个 decode step 完成，输出 1 个 token，用时 {self.now - step_start:g} ms")
        self.compute.update(step=None, layer=None, phase="idle")

    # ---- engine --------------------------------------------------------
    def _snapshot(self) -> None:
        notes = [e for e in self.events if abs(e["t"] - self.now) < EPS]
        snap = {
            "t": self.now, "compute": dict(self.compute), "notes": notes,
            "bundles": [{"layer": layer, **b} for layer, b in sorted(self.bundles.items())],
            "kv": [{"layer": k[0], "token": k[1], **{f: e[f] for f in ("state", "dirty", "pinned")}}
                   for k, e in sorted(self.kv.items())],
            "tier1": self.tier1_breakdown(),
            "tier2": {"dirty_pending": sum(e["dirty"] for e in self.kv.values()), "synced_new_kv": self.synced_new_kv},
            "link": {"active": self.active["id"] if self.active else None,
                     "queue": [j["id"] for j in sorted((j for j in self.jobs if not j["done"]), key=self._rank)
                               if j is not self.active]},
        }
        if self.snapshots and abs(self.snapshots[-1]["t"] - self.now) < EPS:
            self.snapshots[-1] = snap
        else:
            self.snapshots.append(snap)

    def run(self) -> dict:
        proc = self._process()
        wake_at: float | None = None
        wait_job: int | None = None
        seg: dict | None = None
        alive = True

        def resume() -> None:
            nonlocal wake_at, wait_job, seg, alive
            while alive:
                if seg:
                    seg["t1"] = self.now
                    if seg["t1"] - seg["t0"] > EPS:
                        self.compute_segments.append(seg)
                        if seg["phase"] in ("wait_weights", "wait_kv"):
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
                    wake_at, wait_job = self.now + arg, None
                    return
                wake_at, wait_job = None, arg
                if not self.jobs[arg]["done"]:
                    return

        try:
            resume()
            self._snapshot()
            while True:
                times = [t for t in (wake_at, self._link_finish_time()) if t is not None]
                if not times:
                    break
                self.now = min(times)
                self._advance_link(self.now)
                # Compare times, not remaining bytes: on a very fast link the finish time
                # can round to `now`, and waiting for bytes to drain would never advance.
                if self.active and self._link_finish_time() <= self.now + EPS:
                    self.m["link_mb"][self.active["kind"]] += self.active["left"]
                    self._complete(self.active)
                if alive and ((wake_at is not None and wake_at <= self.now + EPS)
                              or (wait_job is not None and self.jobs[wait_job]["done"])):
                    wake_at = None
                    resume()
                self._snapshot()
        except CapacityError as error:
            # Keep the trace up to the failure so the replay can show how tier 1 filled up.
            self.error = str(error)
            self.compute["phase"] = "failed"
            self._event("capacity_error", self.error)
            self._close_link_segment()
            self._snapshot()
            return self._result()
        if alive:
            raise ModelError("simulation stalled before decode finished")
        moved = sum(self.m["link_mb"].values())
        if moved > self.link_busy_ms * self.cfg.link_mb_per_ms + 1e-6:
            raise ModelError("link moved more bytes than its bandwidth allows")
        return self._result()

    def _result(self) -> dict:
        m, c = self.m, self.cfg
        tokens = m["token_ms"]
        metrics = {
            "total_ms": round(self.now, 6),
            "decode_ms": round(sum(tokens), 6),
            "token_ms": [round(t, 6) for t in tokens],
            "mean_token_ms": round(sum(tokens) / len(tokens), 6) if tokens else None,
            "steady_token_ms": round(sum(tokens[1:]) / len(tokens[1:]), 6) if len(tokens) > 1 else None,
            "compute_only_token_ms": c.layers * (c.t_indexer_ms + c.t_attention_ms + c.t_moe_ms),
            "wait_weights_ms": round(m["wait_weights_ms"], 6), "wait_kv_ms": round(m["wait_kv_ms"], 6),
            "kv_lookups": m["lookups"], "kv_hits": m["hits"],
            "kv_hit_rate": round(m["hits"] / m["lookups"], 6) if m["lookups"] else None,
            "prefetches": m["prefetches"], "prefetch_late": m["prefetch_late"], "prefetch_skipped": m["prefetch_skipped"],
            "link_mb": {k: round(v, 6) for k, v in m["link_mb"].items()},
            "link_busy_ms": round(self.link_busy_ms, 6),
            "peak_tier1_mb": round(self.peak_tier1, 6), "tier2_full_mb": self.tier2_full_mb,
        }
        jobs = [{k: j[k] for k in ("id", "cls", "kind", "mb", "label", "queued", "end")} for j in self.jobs]
        return {"config": asdict(c), "error": self.error, "metrics": metrics, "events": self.events, "snapshots": self.snapshots,
                "compute_segments": self.compute_segments, "link_segments": self.link_segments, "jobs": jobs}


def simulate(cfg: Config) -> dict:
    """Run one decode. A tier-1 capacity failure is returned as `error` with the partial trace."""
    return Simulator(cfg).run()
