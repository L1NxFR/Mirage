"""The `two_tier_dram` configuration section and the model profile it runs against."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Mapping

GB = 1e9


class ConfigError(ValueError):
    """The two_tier_dram section is invalid."""


@dataclass(frozen=True)
class TwoTierConfig:
    # tier 1: small, fast DRAM that compute reads directly
    tier1_gb: float = 96.0
    scratch_gb: float = 4.0
    # tier 2: large, slow DRAM holding all weights and the full KV
    tier2_gb: float = 2048.0
    # one shared link between the tiers
    link_gbps: float = 64.0
    link_overhead_ms: float = 0.01  # fixed cost per transfer, paid serially
    link_policy: str = "demand_first"  # demand_first (preemptive) | fifo
    # non-expert weights: kept in tier 1, or swapped layer by layer with prefetch (scheme A)
    base_weights: str = "resident"  # resident | layer_prefetch
    # routed MoE experts: LRU cache in tier 1 (scheme B)
    expert_cache_gb: float | None = None  # None = whatever tier 1 has left
    expert_overlap: float = 0.5  # chance a layer routes to each of its previous step's experts again
    expert_prefetch: str = "none"  # none | last_step (prefetch the next layer's previous-step experts)
    # sparse attention KV: LRU cache of top-k compressed entries in tier 1
    hot_kv_entries: int = 65536  # 0 = no cache, fetched entries are dropped after the layer
    topk_overlap: float = 0.75  # chance a layer keeps each top-k entry from its previous step
    # run control
    seed: int = 0
    max_decode_steps: int = 3  # re-time at most this many decode steps per request
    trace_dir: str | None = None  # where to write trace.json and replay.html

    def __post_init__(self) -> None:
        def need(ok: bool, message: str) -> None:
            if not ok:
                raise ConfigError(f"two_tier_dram: {message}")

        need(self.tier1_gb > 0 and self.tier2_gb > 0, "tier capacities must be positive")
        need(0 <= self.scratch_gb < self.tier1_gb, "scratch_gb must be within tier1_gb")
        need(self.link_gbps > 0 and self.link_overhead_ms >= 0, "link bandwidth must be positive and overhead non-negative")
        need(self.link_policy in ("demand_first", "fifo"), "link_policy must be demand_first or fifo")
        need(self.base_weights in ("resident", "layer_prefetch"), "base_weights must be resident or layer_prefetch")
        need(self.expert_prefetch in ("none", "last_step"), "expert_prefetch must be none or last_step")
        need(self.expert_cache_gb is None or self.expert_cache_gb > 0, "expert_cache_gb must be positive when set")
        need(0 <= self.expert_overlap <= 1 and 0 <= self.topk_overlap <= 1, "overlaps must be within [0, 1]")
        need(self.hot_kv_entries >= 0 and self.max_decode_steps >= 1, "hot_kv_entries >= 0 and max_decode_steps >= 1")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "TwoTierConfig":
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(raw) - known)
        if unknown:
            raise ConfigError(f"two_tier_dram: unknown fields {unknown}; known fields are {sorted(known)}")
        try:
            return cls(**raw)
        except TypeError as error:
            raise ConfigError(f"two_tier_dram: {error}") from error

    def to_json(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Layer:
    kind: str  # "csa" (sparse top-k attention) | "hca" (reads all its compressed entries)
    attention_ms: float
    moe_ms: float
    base_bytes: float  # attention, shared-expert, router and norm weights of this layer
    indexer_bytes: float  # indexer cache scanned to pick the top-k (csa only)
    static_kv_bytes: float  # KV every step reads in full: sliding window, plus hca compressed entries
    topk_candidates: int  # compressed entries the top-k is drawn from (csa only)


@dataclass(frozen=True)
class ModelProfile:
    """What the two-tier model needs to know about one model at one context length."""

    layers: tuple[Layer, ...]
    tail_ms: float  # per-step work outside the layers (embedding, logits)
    global_bytes: float  # weights outside the layers, always resident
    expert_bytes: float
    experts_per_layer: int
    experts_per_token: int
    index_topk: int
    kv_entry_bytes: float
    new_token_kv_bytes: float
    full_weights_bytes: float
    full_kv_bytes: float
    source: dict = field(default_factory=dict)  # provenance: model, hardware, backend, context, per-op latencies

    @property
    def native_step_ms(self) -> float:
        return sum(layer.attention_ms + layer.moe_ms for layer in self.layers) + self.tail_ms

    def to_json(self) -> dict:
        data = asdict(self)
        data["layers"] = {"count": len(self.layers), "csa": sum(l.kind == "csa" for l in self.layers),
                          "hca": sum(l.kind == "hca" for l in self.layers), "first": asdict(self.layers[0]),
                          "kinds": "".join("C" if l.kind == "csa" else "H" for l in self.layers)}
        data["native_step_ms"] = self.native_step_ms
        return data
