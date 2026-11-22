"""Build a ModelProfile from AISim: model geometry, byte sizes, and per-operator decode latency.

Everything here is read from AISim's own model registry and perf model, so the
two-tier model runs on the same numbers AISim uses to price a decode pass:

  * layer count and per-layer attention kind from the model's compress ratios;
  * weights from each operator's `get_weights()`;
  * KV sizes from the model's KV-cache accounting;
  * compute time from `EngineHandle.decode_step_per_op`, which sums to AISim's
    decode-step latency.

AISim prices an operator once for all layers, so per-layer time is the
operator's latency divided evenly across layers. Only DeepSeek-V4 style models
(compressed sparse attention + MoE) are supported.
"""

from __future__ import annotations

from .config import Layer, ModelProfile

ATTENTION_OPS = ("generation_mhc_pre", "generation_attn_norm", "generation_attention", "generation_mhc_post")
MOE_OPS = ("generation_ffn_norm", "generation_moe_overlap")
GLOBAL_WEIGHT_OPS = ("context_embedding", "context_logits_gemm")


class UnsupportedModelError(ValueError):
    pass


def build_profile(model_path: str, hardware: str, backend: str, context_tokens: int,
                  database_mode: str = "SOL") -> ModelProfile:
    from aisim_core.sdk import common, config
    from aisim_core.sdk.engine import EngineHandle
    from aisim_core.sdk.models import get_model

    model = get_model(model_path, config.ModelConfig(tp_size=1, moe_tp_size=1, moe_ep_size=1), backend)
    dsv4 = getattr(model, "extra_params", None)
    ratios = getattr(model, "_compress_ratios", None)
    if ratios is None or not hasattr(dsv4, "index_topk") or not hasattr(model, "_num_experts"):
        raise UnsupportedModelError(
            f"two_tier_dram supports DeepSeek-V4 style models (compressed sparse attention + MoE); got {model_path}")
    n = len(ratios)

    handle = EngineHandle.compile(model_path, hardware, backend, database_mode=database_mode)
    per_op = {name: latency for name, latency, *_ in handle.decode_step_per_op(1, context_tokens, 2)}
    attention_ms = sum(per_op.get(name, 0.0) for name in ATTENTION_OPS) / n
    moe_ms = sum(per_op.get(name, 0.0) for name in MOE_OPS) / n
    tail_ms = sum(v for name, v in per_op.items() if name not in ATTENTION_OPS + MOE_OPS)

    weights: dict[str, float] = {}
    for op in model.context_ops:
        if not op._name.startswith("draft_"):
            weights[op._name] = weights.get(op._name, 0.0) + float(op.get_weights())
    full_weights = sum(weights.values())
    routed = weights.get("context_moe", 0.0)
    if routed <= 0:
        raise UnsupportedModelError(f"{model_path} exposes no routed MoE weights (context_moe)")
    global_bytes = sum(weights.get(name, 0.0) for name in GLOBAL_WEIGHT_OPS)
    base_per_layer = (full_weights - routed - global_bytes) / n
    expert_bytes = routed / (n * model._num_experts)

    entry = dsv4.head_dim * model.config.kvcache_quant_mode.value.memory
    indexer_entry = common.deepseek_v4_indexer_cache_entry_bytes(dsv4.index_head_dim)
    window = min(context_tokens, dsv4.sliding_window) * entry
    layers = []
    for ratio in ratios:
        compressed = context_tokens // ratio if ratio else 0
        if ratio == 4:
            layers.append(Layer("csa", attention_ms, moe_ms, base_per_layer, compressed * indexer_entry, window, compressed))
        else:
            layers.append(Layer("hca", attention_ms, moe_ms, base_per_layer, 0.0, window + compressed * entry, 0))
    full_kv = float(model.get_kvcache_bytes_per_sequence(context_tokens))
    return ModelProfile(
        layers=tuple(layers), tail_ms=tail_ms, global_bytes=global_bytes, expert_bytes=expert_bytes,
        experts_per_layer=model._num_experts, experts_per_token=model._topk, index_topk=dsv4.index_topk,
        kv_entry_bytes=entry,
        new_token_kv_bytes=float(model.get_kvcache_bytes_per_sequence(context_tokens + 128) - full_kv) / 128,
        full_weights_bytes=full_weights, full_kv_bytes=full_kv,
        source={"provider": "aisim", "model": model_path, "hardware": hardware, "backend": backend,
                "database_mode": database_mode, "context_tokens": context_tokens,
                "per_op_ms": {k: round(v, 9) for k, v in per_op.items()},
                "weights_gb": {k: round(v / 1e9, 6) for k, v in sorted(weights.items(), key=lambda kv: -kv[1])},
                "note": "per-layer time = operator latency / layer count"})


def synthetic_profile(layers: int = 6, context_tokens: int = 4096, attention_ms: float = 1.0, moe_ms: float = 1.0,
                      tail_ms: float = 0.5, expert_mb: float = 64.0, experts_per_layer: int = 32,
                      experts_per_token: int = 4, index_topk: int = 64, base_mb: float = 256.0) -> ModelProfile:
    """A small hand-made profile for tests and demos that must not depend on AISim."""
    entry, mb = 512.0, 1e6
    made = []
    for i in range(layers):
        if i % 2 == 0:
            made.append(Layer("csa", attention_ms, moe_ms, base_mb * mb, context_tokens // 4 * 64.0, 128 * entry, context_tokens // 4))
        else:
            made.append(Layer("hca", attention_ms, moe_ms, base_mb * mb, 0.0, (128 + context_tokens // 128) * entry, 0))
    full_weights = layers * (base_mb * mb + experts_per_layer * expert_mb * mb) + 100 * mb
    return ModelProfile(layers=tuple(made), tail_ms=tail_ms, global_bytes=100 * mb, expert_bytes=expert_mb * mb,
                        experts_per_layer=experts_per_layer, experts_per_token=experts_per_token, index_topk=index_topk,
                        kv_entry_bytes=entry, new_token_kv_bytes=layers * entry, full_weights_bytes=full_weights,
                        full_kv_bytes=layers * context_tokens * entry / 2,
                        source={"provider": "synthetic", "context_tokens": context_tokens})
