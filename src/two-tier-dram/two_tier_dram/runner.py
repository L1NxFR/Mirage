"""`--stack two_tier_dram`: AISim's engine replay, then a per-layer re-timing of each decode step.

AISim runs the workload exactly as `--stack engine` does: it loads the trace,
schedules requests, and prices every pass with its perf model. This runner asks
the same native runtime for replay artifacts, takes each request's context
length and token timeline from them, and re-times the decode steps on a
two-tier DRAM system. The native report is returned unchanged with the two-tier
results added beside it; AISim's own pass times are not altered, so waits do
not feed back into scheduling. That is exact for requests that do not overlap,
and this runner refuses overlapping decode.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, replace
from pathlib import Path

from aisim.runner import EngineReplayRunnerFactory, InvalidRunnerError
from aisim.sweeper.replay import ReplayReport

from .adapter import NAME
from .config import TwoTierConfig
from .model import simulate
from .profile import build_profile


class _ArtifactRuntime:
    """Engine runtime seam: the same replay loop, plus AISim's native request/output artifacts."""

    def __init__(self) -> None:
        self.artifacts: dict | None = None

    def run_replay_json(self, execution_spec_json: str) -> str:
        import aisim._runtime as runtime

        output = json.loads(runtime.run_replay_with_artifacts_json(execution_spec_json))
        self.artifacts = output["artifacts"]
        return json.dumps(output["report"], allow_nan=False, separators=(",", ":"))


def compute_basis(cfg: TwoTierConfig, profile, hardware: str) -> dict:
    """Whether AISim priced compute with the same tier-1 bandwidth the two-tier memory assumes."""
    priced, assumed = profile.compute_bandwidth, cfg.hardware.tier1_bandwidth
    consistent = priced is not None and abs(priced - assumed) <= 0.01 * assumed
    label = (f"AISim computes latency using {hardware} with {priced / 1e12:g} TB/s of read bandwidth, consistent with the tier 1 assumption." if consistent else
             f"Hybrid experiment combining AISim compute latency for {hardware} ({priced / 1e12:g} TB/s read bandwidth) "
             f"with the {cfg.hardware.preset} memory configuration ({assumed / 1e12:g} TB/s at tier 1).")
    return {"consistent": consistent, "aisim_hardware": hardware, "priced_bandwidth": priced,
            "assumed_tier1_bandwidth": assumed, "label": label}


def retime(config: dict, artifacts: dict) -> dict:
    """Re-time every completed request's decode steps. Returns the trace document."""
    cfg, aisim = TwoTierConfig.from_mapping(config["two_tier"]), config["aisim"]
    tokens: dict[str, list[float]] = {}
    for out in artifacts["outputs"]:  # one record per output token
        if not out["rejected"]:
            tokens.setdefault(out["request_id"], []).append(out["observed_at_ms"])
    decoding = sorted((times[0], times[-1], rid) for rid, times in tokens.items() if len(times) > 1)
    for (_, end, a), (start, _, b) in zip(decoding, decoding[1:]):
        if start < end:
            raise InvalidRunnerError(
                f"two_tier_dram re-times one request at a time, but requests {a} and {b} decode concurrently; "
                "use non-overlapping requests (batch 1)")
    requests = []
    for req in sorted(artifacts["requests"], key=lambda r: r["observed_at_ms"]):
        times = sorted(tokens.get(req["request_id"], []))
        steps = min(len(times) - 1, cfg.max_decode_steps)
        entry = {"request_id": req["request_id"], "arrival_ms": req["observed_at_ms"], "input_tokens": req["input_length"],
                 "native_token_times_ms": times,
                 "native_itl_ms": [round(b - a, 6) for a, b in zip(times, times[1:])], "retimed_steps": max(steps, 0)}
        if steps >= 1:
            profile = build_profile(aisim["model"], aisim["hardware"], aisim["backend"], req["input_length"],
                                    aisim["database_mode"], aisim.get("systems_paths"), aisim.get("backend_version"))
            entry["profile"] = profile.to_json()
            entry["compute_basis"] = compute_basis(cfg, profile, aisim["hardware"])
            entry["decode_start_ms"] = times[0]
            # The profile and the replay must be priced by the same AISim perf model.
            native = entry["native_itl_ms"][0]
            entry["native_itl_matches_profile"] = abs(profile.native_step_ms - native) <= 1e-3 * max(native, 1e-9)
            entry.update(simulate(cfg, profile, steps))
        requests.append(entry)
    return {"schema": 2, "aisim": aisim, "config": cfg.to_json(), "requests": requests}


@dataclass(frozen=True)
class TwoTierRunnerFactory:
    def capabilities(self):
        return EngineReplayRunnerFactory().capabilities()

    def create(self, worker_id: int) -> "TwoTierRunner":
        return TwoTierRunner(worker_id)


class TwoTierRunner:
    def __init__(self, worker_id: int) -> None:
        self._runtime = _ArtifactRuntime()
        self._engine = EngineReplayRunnerFactory(runtime=self._runtime).create(worker_id)

    def run(self, spec, *, output_requirements=None) -> ReplayReport:
        adapter = spec.adapters.get(NAME)
        if adapter is None:
            raise InvalidRunnerError("--stack two_tier_dram needs a top-level `two_tier_dram:` section in the config")
        report = self._engine.run(replace(spec, adapters={}), output_requirements=output_requirements)
        trace = retime(adapter.config, self._runtime.artifacts or {"requests": [], "outputs": []})
        retimed = [r for r in trace["requests"] if r.get("metrics")]
        metrics, summary = dict(report.metrics), {"requests": len(trace["requests"]), "retimed_requests": len(retimed)}
        errors = [r["error"] for r in retimed if r["error"]]
        done = [r["metrics"] for r in retimed if not r["error"]]
        if done:
            all_tokens = [t for m in done for t in m["token_ms"]]
            metrics["two_tier_mean_itl_ms"] = sum(all_tokens) / len(all_tokens)
            metrics["two_tier_native_itl_ms"] = sum(m["native_token_ms"] for m in done) / len(done)
            summary["per_request"] = [{k: m[k] for k in ("token_ms", "native_token_ms", "steady", "expert_hit_rate",
                                                         "kv_hit_rate", "wait_experts_ms", "wait_kv_ms", "wait_base_ms",
                                                         "peak_tier1_bytes", "link_utilization")}
                                      for m in done]
            summary["feasible"] = all(r["feasible"] for r in retimed)
            summary["compute_basis"] = [r["compute_basis"]["label"] for r in retimed]
        if errors:
            summary["errors"] = errors
            sys.stderr.write("two_tier_dram: " + "; ".join(errors) + "\n")
        mismatched = [r["request_id"] for r in retimed if not r["native_itl_matches_profile"]]
        if mismatched:
            sys.stderr.write(f"two_tier_dram: warning: AISim's replay ITL differs from the per-operator profile for {mismatched}; "
                             "the engine timing model is not the op-level perf model the profile uses\n")
        for r in retimed:
            m = r["metrics"]
            steady = m["steady"]
            took = (f"steady {steady['token_ms']:.3f} ms from step {steady['from_step']}" if steady["reached"]
                    else f"no steady state ({steady['reason']}); mean {m['mean_token_ms'] or 0:.3f} ms")
            print(f"two_tier_dram: {r['input_tokens']} context tokens, {len(m['token_ms'])} steps: {took}; "
                  f"AISim native {m['native_token_ms']:.3f} ms; expert hits {m['expert_hits']}/{m['expert_lookups']}, "
                  f"top-k KV hits {m['kv_hits']}/{m['kv_lookups']}")
            print(f"two_tier_dram: {r['compute_basis']['label']}")
            for reason in r["infeasible"]:
                print(f"two_tier_dram: INFEASIBLE (counterfactual run): {reason}")
        trace_dir = trace["config"].get("trace_dir")
        if trace_dir:
            from .render import write_replay

            folder = Path(trace_dir)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "trace.json").write_text(json.dumps(trace, ensure_ascii=False, separators=(",", ":")))
            (folder / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
            write_replay([{"title": "two_tier_dram", "trace": trace}], folder / "replay.html")
            summary["trace_dir"] = str(folder)
        return ReplayReport(metrics=metrics, metadata={**report.metadata, "two_tier_dram": summary})

    def close(self) -> None:
        self._engine.close()
