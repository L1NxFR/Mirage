"""Configuration adapter for the top-level `two_tier_dram` section (AISim config-adapter ABI v3)."""

from __future__ import annotations

from typing import Any, Mapping

from aisim.config_adapter import PredictionAdapterContext
from aisim.sweeper.provider import AdapterReplaySpec

from .config import ConfigError, TwoTierConfig

NAME = "two_tier_dram.two_tier_dram"


def _perf_model(engine: Mapping[str, Any]) -> dict:
    perf = engine.get("ais_perf_model")
    entries = perf if isinstance(perf, list) else [perf] if isinstance(perf, Mapping) else []
    for entry in entries:
        if entry.get("worker_type") in (None, "aggregated"):
            return dict(entry)
    return {}


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
        # AISim normalizes `ais_perf_model` into top-level engine fields before adapters see it.
        perf = {**_perf_model(engine), **{k: engine[k] for k in ("database_mode", "systems_paths") if engine.get(k)}}
        return AdapterReplaySpec(config={
            "two_tier": cfg.to_mapping(),
            "aisim": {"model": engine["model"], "hardware": engine["hardware"], "backend": engine["backend"],
                      "database_mode": perf.get("database_mode", "SOL"), "systems_paths": perf.get("systems_paths"),
                      "backend_version": engine.get("backend_version")},
        })

    def compile_recommendation(self, config, context):
        raise ConfigError("two_tier_dram supports `aisim predict` only; it defines no search space")

    def materialize_candidate(self, plan, selection, context):
        raise ConfigError("two_tier_dram supports `aisim predict` only; it defines no search space")
