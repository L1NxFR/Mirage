"""Configuration adapter for the top-level `two_tier_dram` section (AISim config-adapter ABI v3)."""

from __future__ import annotations

from typing import Any, Mapping

from aisim.config_adapter import PredictionAdapterContext
from aisim.sweeper.provider import AdapterReplaySpec

from .config import ConfigError, TwoTierConfig

NAME = "two_tier_dram.two_tier_dram"


def _database_mode(engine: Mapping[str, Any]) -> str:
    perf = engine.get("ais_perf_model")
    entries = perf if isinstance(perf, list) else [perf] if isinstance(perf, Mapping) else []
    for entry in entries:
        if entry.get("worker_type") in (None, "aggregated") and entry.get("database_mode"):
            return str(entry["database_mode"])
    return "SOL"


class TwoTierConfigAdapter:
    name = NAME
    section = "two_tier_dram"
    config_adapter_api_version = 3

    def compile_prediction(self, config: Mapping[str, Any], context: PredictionAdapterContext) -> AdapterReplaySpec:
        cfg = TwoTierConfig.from_mapping(dict(config))
        engine = context.engine
        if engine.get("mode", "aggregated") != "aggregated":
            raise ConfigError("two_tier_dram re-times one aggregated worker; engine.mode must be aggregated")
        missing = [key for key in ("model", "hardware", "backend") if not isinstance(engine.get(key), str)]
        if missing:
            raise ConfigError(f"two_tier_dram needs concrete engine.{'/'.join(missing)}")
        return AdapterReplaySpec(config={
            "two_tier": cfg.to_json(),
            "aisim": {"model": engine["model"], "hardware": engine["hardware"], "backend": engine["backend"],
                      "database_mode": _database_mode(engine)},
        })

    def compile_recommendation(self, config, context):
        raise ConfigError("two_tier_dram supports `aisim predict` only; it defines no search space")

    def materialize_candidate(self, plan, selection, context):
        raise ConfigError("two_tier_dram supports `aisim predict` only; it defines no search space")
