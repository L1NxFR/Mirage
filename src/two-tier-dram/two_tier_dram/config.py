"""The `two_tier_dram` configuration section: hardware with units and sources, policies, and the model profile.

Hardware quantities are written with explicit units ("36 GB", "2.2 TB/s",
"10 us") and parsed once, here, into bytes, bytes per second and seconds.
Decimal and binary prefixes are kept apart (GB = 1e9 bytes, GiB = 2**30
bytes) and bits are kept apart from bytes (Gb/s = 1e9 bits/s = 1.25e8 B/s).

Hardware fields retain source labels alongside parsed values. Scenario
overrides update the value and its label together.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, fields, replace
from typing import Any, Mapping

GB = 1e9  # decimal gigabyte, used only for display


class ConfigError(ValueError):
    """The two_tier_dram section is invalid."""


# ---- units ---------------------------------------------------------------
_PREFIX = {"": 1.0, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12, "P": 1e15}
_BINARY = {"Ki": 2.0**10, "Mi": 2.0**20, "Gi": 2.0**30, "Ti": 2.0**40}
_TIME = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "µs": 1e-6, "ns": 1e-9}
_QUANTITY = re.compile(r"^\s*([0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)\s*([A-Za-zµ/]+)\s*$")


def _split(text: Any, what: str) -> tuple[float, str]:
    if not isinstance(text, str):
        raise ConfigError(f"{what} must be a string with a unit, e.g. '36 GB' or '2.2 TB/s'; got {text!r}")
    match = _QUANTITY.match(text)
    if not match:
        raise ConfigError(f"{what}: cannot parse {text!r}; write a number and a unit, e.g. '36 GB'")
    return float(match.group(1)), match.group(2)


def _unit_scale(unit: str) -> tuple[float, str] | None:
    """(bytes per unit, 'B' or 'b') for B/kB/MB/GB/TB, KiB/MiB/GiB/TiB and their bit forms."""
    for prefixes in (_BINARY, _PREFIX):
        for prefix, scale in prefixes.items():
            if unit == f"{prefix}B":
                return scale, "B"
            if unit == f"{prefix}b":
                return scale / 8, "b"
    return None


def parse_bytes(text: Any, what: str = "size") -> float:
    value, unit = _split(text, what)
    scale = _unit_scale(unit)
    if scale is None or scale[1] != "B":
        raise ConfigError(f"{what}: {text!r} is not a size in bytes; use B, kB, MB, GB, TB or KiB, MiB, GiB, TiB")
    return value * scale[0]


def parse_bandwidth(text: Any, what: str = "bandwidth") -> float:
    """Bytes per second from '2.2 TB/s', '64 GB/s', '800 Gb/s' (bits) or '1 GiB/s'."""
    value, unit = _split(text, what)
    scale = _unit_scale(unit[:-2]) if unit.endswith("/s") else None
    if scale is None:
        raise ConfigError(f"{what}: {text!r} is not a bandwidth; write e.g. '2.2 TB/s' or '800 Gb/s'")
    return value * scale[0]


def parse_seconds(text: Any, what: str = "time") -> float:
    value, unit = _split(text, what)
    if unit not in _TIME:
        raise ConfigError(f"{what}: {text!r} is not a time; use s, ms, us or ns")
    return value * _TIME[unit]


# ---- hardware ------------------------------------------------------------
TABLE = "EXI-3DDRAM 架构表"
TABLE_ASK = "EXI-3DDRAM 架构表（Ask，未确定）"
DESIGN = "研究记录《初期目标》96 GB 方案"
ASSUME = "假设"
LEGACY = "旧假设（无硬件依据，已撤回）"
AISIM_B200 = "AISim b200_sxm 规格"
OVERRIDE = "场景覆盖"

HARDWARE_FIELDS = {  # field -> parser (None = plain number)
    "tier1_capacity": parse_bytes,
    "tier1_bandwidth": parse_bandwidth,
    "tier2_capacity": parse_bytes,
    "tier2_bandwidth": parse_bandwidth,
    "copy_efficiency": None,
    "transfer_overhead": parse_seconds,
    "interconnect_bandwidth": parse_bandwidth,
    "scratch": parse_bytes,
}

_EXI = {
    "tier1_capacity": ("36 GB", TABLE),
    "tier1_bandwidth": ("18 TB/s", TABLE),
    "tier2_capacity": ("128 GB", TABLE + "：默认 128 GB，范围 64–512 GB"),
    "tier2_bandwidth": ("2.2 TB/s", TABLE + "：LPDDR6 1.1–2.2 TB/s 的上端"),
    "copy_efficiency": (1.0, ASSUME + "：理想复制，二级标称带宽全部可用"),
    "transfer_overhead": ("0 s", ASSUME + "：表中未给出，理想为 0"),
    "interconnect_bandwidth": ("1.6 TB/s", TABLE_ASK + "：UALink 2.0 双向合计；TP1 下未使用"),
    "scratch": ("4 GB", ASSUME + "：激活与临时空间，表中未给出"),
}

HARDWARE_PRESETS: dict[str, dict[str, tuple[Any, str]]] = {
    "exi_figure": _EXI,
    "exi_96gb_explore": {**_EXI, "tier1_capacity": ("96 GB", DESIGN + "；不是 EXI 图示配置")},
    "legacy_64gbps": {
        "tier1_capacity": ("96 GB", DESIGN),
        "tier1_bandwidth": ("7.7 TB/s", AISIM_B200),
        "tier2_capacity": ("2048 GB", LEGACY + "：为装下 1579 GB 模型而虚构"),
        "tier2_bandwidth": ("64 GB/s", LEGACY),
        "copy_efficiency": (1.0, LEGACY),
        "transfer_overhead": ("10 us", LEGACY),
        "interconnect_bandwidth": ("900 GB/s", AISIM_B200 + "：单向；TP1 下未使用"),
        "scratch": ("4 GB", ASSUME),
    },
}


@dataclass(frozen=True)
class Hardware:
    """Resolved hardware in SI units: bytes, bytes per second, seconds."""

    preset: str
    tier1_capacity: float  # bytes
    tier1_bandwidth: float  # bytes/s that compute reads tier 1 with
    tier2_capacity: float  # bytes
    tier2_bandwidth: float  # bytes/s, nominal tier-2 (LPDDR) bandwidth
    copy_efficiency: float  # fraction of tier2_bandwidth a tier2 -> tier1 copy achieves
    transfer_overhead: float  # seconds of fixed cost per transfer, paid serially on the link
    interconnect_bandwidth: float  # bytes/s between cards; recorded only (single card, TP1)
    scratch: float  # bytes of tier 1 reserved for activations and temporaries
    sources: dict = field(default_factory=dict)  # field -> where the value came from
    written: dict = field(default_factory=dict)  # field -> value as written

    @property
    def copy_bandwidth(self) -> float:
        """Effective tier2 -> tier1 copy bandwidth in bytes/s."""
        return self.tier2_bandwidth * self.copy_efficiency

    def to_json(self) -> dict:
        return asdict(self) | {"copy_bandwidth": self.copy_bandwidth}


def resolve_hardware(preset: str, overrides: Mapping[str, Any]) -> Hardware:
    if preset not in HARDWARE_PRESETS:
        raise ConfigError(f"two_tier_dram.hardware: unknown preset {preset!r}; choose from {sorted(HARDWARE_PRESETS)}")
    values, sources, written = {}, {}, {}
    for name, parse in HARDWARE_FIELDS.items():
        raw, source = HARDWARE_PRESETS[preset][name]
        if name in overrides:
            raw, source = overrides[name], OVERRIDE
        written[name], sources[name] = raw, source
        if parse is None:
            if not isinstance(raw, (int, float)) or isinstance(raw, bool) or not 0 < raw <= 1:
                raise ConfigError(f"two_tier_dram.{name} must be a number in (0, 1]; got {raw!r}")
            values[name] = float(raw)
        else:
            values[name] = parse(raw, f"two_tier_dram.{name}")
    for name in ("tier1_capacity", "tier1_bandwidth", "tier2_capacity", "tier2_bandwidth"):
        if values[name] <= 0:
            raise ConfigError(f"two_tier_dram.{name} must be positive")
    if not 0 <= values["scratch"] < values["tier1_capacity"]:
        raise ConfigError("two_tier_dram.scratch must be within tier1_capacity")
    if values["transfer_overhead"] < 0:
        raise ConfigError("two_tier_dram.transfer_overhead must be non-negative")
    return Hardware(preset=preset, sources=sources, written=written, **values)


# ---- policies ------------------------------------------------------------
@dataclass(frozen=True)
class TwoTierConfig:
    hardware: Hardware
    # tier 2 must hold every weight and the full KV; "counterfactual" runs anyway and marks the result infeasible
    tier2_capacity_check: str = "enforce"  # enforce | counterfactual
    link_policy: str = "demand_first"  # demand_first (demand reads preempt prefetch and writeback) | fifo
    # non-expert weights: all resident in tier 1, or rotated layer by layer (current + prefetched next layer)
    base_weights: str = "resident"  # resident | layer_rotation
    # routed experts: an LRU cache kept across decode steps, or released when the layer finishes
    expert_cache: str = "lru"  # lru | per_layer
    expert_cache_capacity: float | None = None  # bytes; None = whatever tier 1 has left
    expert_overlap: float = 0.5  # chance a layer routes to each of its previous step's experts again (synthetic)
    expert_prefetch: str = "none"  # none | last_step (prefetch the next layer's previous-step experts)
    hot_kv_entries: int = 65536  # LRU cache of sparse top-k KV entries; 0 = drop after the layer
    topk_overlap: float = 0.75  # chance a layer keeps each top-k entry from its previous step (synthetic)
    seed: int = 0
    max_decode_steps: int = 16  # decode steps re-timed per request
    trace_detail: str = "full"  # full (events + snapshots for the replay) | summary (metrics and per-step stats)
    trace_dir: str | None = None

    def __post_init__(self) -> None:
        def need(ok: bool, message: str) -> None:
            if not ok:
                raise ConfigError(f"two_tier_dram: {message}")

        need(self.tier2_capacity_check in ("enforce", "counterfactual"), "tier2_capacity_check must be enforce or counterfactual")
        need(self.link_policy in ("demand_first", "fifo"), "link_policy must be demand_first or fifo")
        need(self.base_weights in ("resident", "layer_rotation"), "base_weights must be resident or layer_rotation")
        need(self.expert_cache in ("lru", "per_layer"), "expert_cache must be lru or per_layer")
        need(self.expert_prefetch in ("none", "last_step"), "expert_prefetch must be none or last_step")
        need(self.expert_cache_capacity is None or self.expert_cache_capacity > 0, "expert_cache_capacity must be positive")
        need(0 <= self.expert_overlap <= 1 and 0 <= self.topk_overlap <= 1, "overlaps must be within [0, 1]")
        need(self.hot_kv_entries >= 0 and self.max_decode_steps >= 1, "hot_kv_entries >= 0 and max_decode_steps >= 1")
        need(self.trace_detail in ("full", "summary"), "trace_detail must be full or summary")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "TwoTierConfig":
        raw = dict(raw)
        preset = raw.pop("hardware", "exi_figure")
        hw = {k: raw.pop(k) for k in list(raw) if k in HARDWARE_FIELDS}
        if raw.get("expert_cache_capacity") is not None:
            raw["expert_cache_capacity"] = parse_bytes(raw["expert_cache_capacity"], "two_tier_dram.expert_cache_capacity")
        known = {f.name for f in fields(cls)} - {"hardware"}
        unknown = sorted(set(raw) - known)
        if unknown:
            raise ConfigError(f"two_tier_dram: unknown fields {unknown}; known fields are "
                              f"{sorted(known | set(HARDWARE_FIELDS) | {'hardware'})}")
        try:
            return cls(hardware=resolve_hardware(preset, hw), **raw)
        except TypeError as error:
            raise ConfigError(f"two_tier_dram: {error}") from error

    def to_mapping(self) -> dict:
        """The section as written; from_mapping(to_mapping()) reproduces the config."""
        data = {f.name: getattr(self, f.name) for f in fields(self) if f.name != "hardware"}
        if self.expert_cache_capacity is not None:
            data["expert_cache_capacity"] = f"{self.expert_cache_capacity:.0f} B"
        overrides = {k: v for k, v in self.hardware.written.items() if self.hardware.sources[k] == OVERRIDE}
        return {"hardware": self.hardware.preset, **data, **overrides}

    def to_json(self) -> dict:
        data = {f.name: getattr(self, f.name) for f in fields(self) if f.name != "hardware"}
        return {**data, "hardware": self.hardware.to_json()}

    def with_steps(self, steps: int) -> "TwoTierConfig":
        return replace(self, max_decode_steps=steps)


# ---- model profile -------------------------------------------------------
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
    compute_bandwidth: float | None = None  # bytes/s of tier-1 reads the compute times were priced with
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
