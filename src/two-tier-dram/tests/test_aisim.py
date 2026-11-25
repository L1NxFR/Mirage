"""Integration checks against a real AISim install (run with AISim's venv Python).

    ../aisim/python/aisim/.venv/bin/python -m unittest discover -s tests -v
"""

import unittest
from pathlib import Path

try:
    import aisim  # noqa: F401
    from aisim_core.sdk.engine import EngineHandle
except ImportError:  # pragma: no cover
    EngineHandle = None

SYSTEMS = str(Path(__file__).resolve().parents[1] / "systems")
MODEL, BACKEND, CONTEXT = "deepseek-ai/DeepSeek-V4-Pro", "vllm", 200_000
EXI = {"hardware": "exi_3ddram", "systems_paths": [SYSTEMS, "default"], "backend_version": "0.30.0"}


def profile(hardware="exi_3ddram", model=MODEL):
    from two_tier_dram.profile import build_profile

    if hardware == "exi_3ddram":
        return build_profile(model, hardware, BACKEND, CONTEXT, "SOL", EXI["systems_paths"], EXI["backend_version"])
    return build_profile(model, hardware, BACKEND, CONTEXT)


@unittest.skipIf(EngineHandle is None, "AISim is not installed in this interpreter")
class WithAisim(unittest.TestCase):
    def test_stack_and_config_section_are_registered(self):
        from aisim.config_adapter import resolve_config_adapters
        from aisim.stack import resolve_runner_factory

        self.assertEqual(type(resolve_runner_factory("two_tier_dram")).__name__, "TwoTierRunnerFactory")
        self.assertIn("two_tier_dram.two_tier_dram", resolve_config_adapters(["two_tier_dram.two_tier_dram"]))

    def test_exi_spec_carries_the_preset_bandwidth_into_aisim(self):
        p = profile()
        self.assertEqual(p.compute_bandwidth, 18e12)
        handle = EngineHandle.compile(MODEL, "exi_3ddram", BACKEND, database_mode="SOL", systems_path=SYSTEMS,
                                      backend_version="0.30.0")
        self.assertAlmostEqual(p.native_step_ms, sum(lat for _, lat, *_ in handle.decode_step_per_op(1, CONTEXT, 2)), places=9)

    def test_batch1_decode_is_bandwidth_bound_so_exi_and_b200_differ_by_the_bandwidth_ratio(self):
        exi, b200 = profile(), profile("b200_sxm")
        self.assertEqual(b200.compute_bandwidth, 7.7e12)
        self.assertAlmostEqual(b200.layers[0].attention_ms / exi.layers[0].attention_ms, 18 / 7.7, places=3)

    def test_profile_bytes_add_up_to_aisim_weight_inventory(self):
        from aisim_core.sdk import config
        from aisim_core.sdk.models import get_model

        for model in (MODEL, "sgl-project/DeepSeek-V4-Pro-FP8"):
            p = profile(model=model)
            m = get_model(model, config.ModelConfig(tp_size=1, moe_tp_size=1, moe_ep_size=1), BACKEND)
            rebuilt = p.global_bytes + sum(l.base_bytes for l in p.layers) + len(p.layers) * p.experts_per_layer * p.expert_bytes
            self.assertAlmostEqual(rebuilt / m.get_resident_weights_bytes(), 1.0, places=9)

    def test_compute_basis_flags_a_hybrid_run(self):
        from two_tier_dram.config import TwoTierConfig
        from two_tier_dram.runner import compute_basis

        cfg = TwoTierConfig.from_mapping({"hardware": "exi_figure"})
        self.assertTrue(compute_basis(cfg, profile(), "exi_3ddram")["consistent"])
        hybrid = compute_basis(cfg, profile("b200_sxm"), "b200_sxm")
        self.assertFalse(hybrid["consistent"])
        self.assertIn("Hybrid experiment", hybrid["label"])

    def test_the_official_model_does_not_fit_a_single_reference_device(self):
        from two_tier_dram.config import TwoTierConfig
        from two_tier_dram.model import simulate

        p = profile()
        self.assertGreater(p.full_weights_bytes, 512e9)  # beyond even the largest modeled LPDDR capacity
        result = simulate(TwoTierConfig.from_mapping({"hardware": "exi_figure", "base_weights": "layer_rotation"}), p, 2)
        self.assertIn("infeasible on a single device", result["error"])

    def test_fast_link_reproduces_aisim_native_step_time(self):
        from two_tier_dram.config import TwoTierConfig
        from two_tier_dram.model import simulate

        p = profile()
        cfg = TwoTierConfig.from_mapping({"hardware": "exi_96gb_explore", "tier2_bandwidth": "1 PB/s",
                                          "tier2_capacity_check": "counterfactual"})
        for token in simulate(cfg, p, 3)["metrics"]["token_ms"]:
            self.assertAlmostEqual(token / p.native_step_ms, 1.0, delta=0.01)


if __name__ == "__main__":
    unittest.main()
