"""Behavior checks of the two-tier model on a small synthetic profile (no AISim needed).

Run from src/two-tier-dram:  python3 -m unittest discover -s tests -v
"""

import unittest

from two_tier_dram.config import GB, ConfigError, TwoTierConfig
from two_tier_dram.model import simulate
from two_tier_dram.profile import synthetic_profile

P = synthetic_profile()
SMALL = dict(tier1_gb=4.0, scratch_gb=0.5, tier2_gb=64.0, link_gbps=1.0, hot_kv_entries=512)


def cfg(**overrides) -> TwoTierConfig:
    return TwoTierConfig(**{**SMALL, **overrides})


class TwoTierModel(unittest.TestCase):
    def test_tier1_never_exceeds_capacity(self):
        for c in (cfg(), cfg(base_weights="layer_prefetch"), cfg(hot_kv_entries=0), cfg(expert_prefetch="last_step")):
            result = simulate(c, P)
            self.assertIsNone(result["error"])
            for snap in result["snapshots"]:
                self.assertLessEqual(sum(snap["tier1"].values()), c.tier1_gb * GB + 1)

    def test_phases_start_only_after_their_data_arrived(self):
        result = simulate(cfg(), P)
        jobs = result["jobs"]
        for seg in result["compute_segments"]:
            if seg["phase"] not in ("attention", "moe"):
                continue
            kind, name = ("demand_kv", "top-k KV") if seg["phase"] == "attention" else ("demand_expert", "专家")
            for job in jobs:
                if job["kind"] == kind and job["label"].startswith(f"按需取 L{seg['layer']} {name}") and job["queued"] <= seg["t0"]:
                    self.assertLessEqual(job["end"], seg["t0"] + 1e-9)

    def test_link_serves_one_transfer_at_a_time_within_its_bandwidth(self):
        c = cfg(base_weights="layer_prefetch")
        result = simulate(c, P)
        moved_gb = sum(result["metrics"]["link_gb"].values())
        self.assertLessEqual(moved_gb, result["metrics"]["link_busy_ms"] * c.link_gbps * 1e-3 + 1e-9)
        segs = sorted(result["link_segments"], key=lambda s: s["t0"])
        for a, b in zip(segs, segs[1:]):
            self.assertLessEqual(a["t1"], b["t0"] + 1e-9)

    def test_every_requested_byte_is_delivered(self):
        result = simulate(cfg(), P)
        self.assertAlmostEqual(sum(j["bytes"] for j in result["jobs"]) / GB, sum(result["metrics"]["link_gb"].values()), places=5)

    def test_very_fast_link_degenerates_to_the_native_step_time(self):
        m = simulate(cfg(link_gbps=1e6, link_overhead_ms=0.0), P)["metrics"]
        for token in m["token_ms"]:
            self.assertAlmostEqual(token, m["native_token_ms"], places=2)

    def test_cold_step_pays_for_every_expert_and_topk_entry(self):
        c = cfg(link_overhead_ms=0.0, max_decode_steps=1)
        m = simulate(c, P)["metrics"]
        layers, csa = len(P.layers), sum(l.kind == "csa" for l in P.layers)
        expected_bytes = layers * P.experts_per_token * P.expert_bytes + csa * P.index_topk * P.kv_entry_bytes
        self.assertAlmostEqual(m["token_ms"][0], P.native_step_ms + expected_bytes / (c.link_gbps * 1e6), places=6)
        self.assertEqual((m["expert_hits"], m["kv_hits"]), (0, 0))

    def test_full_overlap_hits_everything_after_the_cold_step(self):
        m = simulate(cfg(expert_overlap=1.0, topk_overlap=1.0), P)["metrics"]
        layers, csa = len(P.layers), sum(l.kind == "csa" for l in P.layers)
        self.assertEqual(m["expert_hits"], 2 * layers * P.experts_per_token)
        self.assertEqual(m["kv_hits"], 2 * csa * P.index_topk)
        self.assertAlmostEqual(m["token_ms"][1], m["native_token_ms"], places=6)

    def test_without_hot_kv_cache_nothing_hits(self):
        self.assertEqual(simulate(cfg(hot_kv_entries=0, topk_overlap=1.0), P)["metrics"]["kv_hits"], 0)

    def test_expert_cache_smaller_than_one_step_never_hits(self):
        one_step_gb = len(P.layers) * P.experts_per_token * P.expert_bytes / GB
        m = simulate(cfg(expert_cache_gb=one_step_gb / 2, expert_overlap=1.0), P)["metrics"]
        self.assertEqual(m["expert_hits"], 0)

    def test_demand_first_makes_compute_wait_less_than_fifo(self):
        slow = dict(base_weights="layer_prefetch", link_gbps=0.5)
        fifo = simulate(cfg(link_policy="fifo", **slow), P)["metrics"]
        prio = simulate(cfg(**slow), P)["metrics"]
        self.assertLess(prio["wait_kv_ms"] + prio["wait_experts_ms"], fifo["wait_kv_ms"] + fifo["wait_experts_ms"])

    def test_tier1_too_small_returns_error_with_a_trace(self):
        result = simulate(cfg(tier1_gb=1.0, scratch_gb=0.1), P)
        self.assertIn("一级 DRAM", result["error"])
        self.assertEqual(result["events"][-1]["kind"], "capacity_error")
        self.assertTrue(result["snapshots"])

    def test_tier2_too_small_returns_error(self):
        self.assertIn("二级 DRAM", simulate(cfg(tier2_gb=1.0), P)["error"])

    def test_runs_are_deterministic(self):
        self.assertEqual(simulate(cfg(seed=3), P), simulate(cfg(seed=3), P))

    def test_unknown_config_fields_are_rejected(self):
        with self.assertRaises(ConfigError):
            TwoTierConfig.from_mapping({"tier1": 96})


if __name__ == "__main__":
    unittest.main()
