"""Integration checks against a real AISim install (run with AISim's venv Python).

    ../aisim/python/aisim/.venv/bin/python -m unittest discover -s tests -v
"""

import unittest

try:
    import aisim  # noqa: F401
    from aisim_core.sdk.engine import EngineHandle
except ImportError:  # pragma: no cover
    EngineHandle = None

MODEL, HARDWARE, BACKEND, CONTEXT = "sgl-project/DeepSeek-V4-Pro-FP8", "b200_sxm", "vllm", 200_000


@unittest.skipIf(EngineHandle is None, "AISim is not installed in this interpreter")
class WithAisim(unittest.TestCase):
    def test_stack_and_config_section_are_registered(self):
        from aisim.config_adapter import resolve_config_adapters
        from aisim.stack import resolve_runner_factory

        self.assertEqual(type(resolve_runner_factory("two_tier_dram")).__name__, "TwoTierRunnerFactory")
        self.assertIn("two_tier_dram.two_tier_dram", resolve_config_adapters(["two_tier_dram.two_tier_dram"]))

    def test_profile_step_time_equals_aisim_decode_step_latency(self):
        from two_tier_dram.profile import build_profile

        profile = build_profile(MODEL, HARDWARE, BACKEND, CONTEXT)
        per_op = EngineHandle.compile(MODEL, HARDWARE, BACKEND, database_mode="SOL").decode_step_per_op(1, CONTEXT, 2)
        self.assertAlmostEqual(profile.native_step_ms, sum(latency for _, latency, *_ in per_op), places=9)

    def test_profile_bytes_add_up_to_aisim_weight_inventory(self):
        from aisim_core.sdk import config
        from aisim_core.sdk.models import get_model
        from two_tier_dram.profile import build_profile

        profile = build_profile(MODEL, HARDWARE, BACKEND, CONTEXT)
        model = get_model(MODEL, config.ModelConfig(tp_size=1, moe_tp_size=1, moe_ep_size=1), BACKEND)
        rebuilt = (profile.global_bytes + sum(l.base_bytes for l in profile.layers)
                   + len(profile.layers) * profile.experts_per_layer * profile.expert_bytes)
        self.assertAlmostEqual(rebuilt / model.get_resident_weights_bytes(), 1.0, places=9)

    def test_fast_link_reproduces_aisim_native_step_time(self):
        from two_tier_dram.config import TwoTierConfig
        from two_tier_dram.model import simulate
        from two_tier_dram.profile import build_profile

        profile = build_profile(MODEL, HARDWARE, BACKEND, CONTEXT)
        m = simulate(TwoTierConfig(link_gbps=1e6, link_overhead_ms=0.0), profile)["metrics"]
        for token in m["token_ms"]:
            self.assertAlmostEqual(token / profile.native_step_ms, 1.0, delta=0.01)


if __name__ == "__main__":
    unittest.main()
