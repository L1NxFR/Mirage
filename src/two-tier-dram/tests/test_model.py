"""Behavior checks of the two-tier model on a small synthetic profile (no AISim needed).

Run from src/two-tier-dram:  python3 -m unittest discover -s tests -v
"""

import unittest

from two_tier_dram.config import (ConfigError, TwoTierConfig, parse_bandwidth, parse_bytes, parse_seconds,
                                  resolve_hardware)
from two_tier_dram.model import TwoTierSim, simulate
from two_tier_dram.profile import synthetic_profile

P = synthetic_profile()  # 6 layers, 32 experts/layer of 64 MB, 4 routed per token, 256 MB base per layer
SMALL = {"hardware": "exi_figure", "tier1_capacity": "4 GB", "scratch": "0.5 GB", "tier2_capacity": "64 GB",
         "tier2_bandwidth": "1 GB/s", "transfer_overhead": "10 us", "hot_kv_entries": 512, "max_decode_steps": 3}


def cfg(**overrides) -> TwoTierConfig:
    return TwoTierConfig.from_mapping({**SMALL, **overrides})


class Units(unittest.TestCase):
    def test_decimal_binary_and_bit_units_are_distinct(self):
        self.assertEqual(parse_bytes("36 GB"), 36e9)
        self.assertEqual(parse_bytes("36 GiB"), 36 * 2**30)
        self.assertEqual(parse_bandwidth("2.2 TB/s"), 2.2e12)
        self.assertEqual(parse_bandwidth("1.6 Tb/s"), 1.6e12 / 8)
        self.assertEqual(parse_bandwidth("64 GB/s"), 64e9)
        self.assertAlmostEqual(parse_seconds("10 us"), 1e-5, delta=1e-18)
        self.assertAlmostEqual(parse_seconds("0.01 ms"), 1e-5, delta=1e-18)

    def test_values_without_units_or_with_the_wrong_kind_are_rejected(self):
        for bad in (36, "36", "36 G", "8 Gb", "2.2 TB/s"):
            with self.assertRaises(ConfigError):
                parse_bytes(bad)
        for bad in (2.2, "2.2 TB", "1.6 Tb", "10 us"):
            with self.assertRaises(ConfigError):
                parse_bandwidth(bad)
        with self.assertRaises(ConfigError):
            parse_seconds("10 GB")

    def test_exi_preset_matches_the_figure_and_records_sources(self):
        hw = resolve_hardware("exi_figure", {})
        self.assertEqual((hw.tier1_capacity, hw.tier1_bandwidth, hw.tier2_capacity, hw.tier2_bandwidth),
                         (36e9, 18e12, 128e9, 2.2e12))
        self.assertEqual(hw.copy_bandwidth, 2.2e12)
        self.assertIn("Ask", hw.sources["interconnect_bandwidth"])
        self.assertIn("假设", hw.sources["transfer_overhead"])
        explore = resolve_hardware("exi_96gb_explore", {})
        self.assertEqual(explore.tier1_capacity, 96e9)
        self.assertIn("不是 EXI 图示配置", explore.sources["tier1_capacity"])

    def test_copy_efficiency_derates_the_copy_bandwidth_only(self):
        hw = resolve_hardware("exi_figure", {"tier2_bandwidth": "1.1 TB/s", "copy_efficiency": 0.7})
        self.assertAlmostEqual(hw.copy_bandwidth, 0.77e12)
        self.assertEqual(hw.tier1_bandwidth, 18e12)

    def test_config_round_trips_through_its_mapping(self):
        c = cfg(expert_cache_capacity="1 GB", copy_efficiency=0.5)
        self.assertEqual(TwoTierConfig.from_mapping(c.to_mapping()), c)


class LinkTiming(unittest.TestCase):
    def test_cold_step_equals_compute_plus_bytes_over_bandwidth_plus_overheads(self):
        c = cfg(max_decode_steps=1)
        result = simulate(c, P)
        layers, csa = len(P.layers), sum(l.kind == "csa" for l in P.layers)
        moved = layers * P.experts_per_token * P.expert_bytes + csa * P.index_topk * P.kv_entry_bytes
        transfers = layers + csa  # one expert transfer per layer, one KV transfer per CSA layer
        expected = P.native_step_ms + moved / c.hardware.copy_bandwidth * 1e3 + transfers * c.hardware.transfer_overhead * 1e3
        self.assertAlmostEqual(result["metrics"]["token_ms"][0], expected, places=6)
        self.assertEqual(result["per_step"][0]["link_bytes"]["demand_expert"], round(layers * P.experts_per_token * P.expert_bytes))

    def test_link_serves_one_transfer_at_a_time_within_its_bandwidth(self):
        c = cfg(base_weights="layer_rotation")
        result = simulate(c, P)
        m = result["metrics"]
        self.assertLessEqual(m["link_total_bytes"], m["link_busy_ms"] * 1e-3 * c.hardware.copy_bandwidth * (1 + 1e-9) + 1)
        segs = sorted(result["link_segments"], key=lambda s: s["t0"])
        for a, b in zip(segs, segs[1:]):
            self.assertLessEqual(a["t1"], b["t0"] + 1e-9)
        self.assertLessEqual(m["link_utilization"], 1.0 + 1e-9)

    def test_every_requested_byte_is_delivered(self):
        result = simulate(cfg(), P)
        self.assertAlmostEqual(sum(j["bytes"] for j in result["jobs"]), result["metrics"]["link_total_bytes"], delta=1)

    def test_very_fast_link_degenerates_to_the_native_step_time(self):
        m = simulate(cfg(tier2_bandwidth="1 PB/s", transfer_overhead="0 s"), P)["metrics"]
        for token in m["token_ms"]:  # what remains is bytes / 1 PB/s: 1.5 GB of cold experts -> 1.5 us
            self.assertAlmostEqual(token, m["native_token_ms"], delta=0.01)

    def test_demand_first_makes_compute_wait_less_than_fifo(self):
        slow = dict(base_weights="layer_rotation", tier2_bandwidth="0.5 GB/s")
        fifo = simulate(cfg(link_policy="fifo", **slow), P)["metrics"]
        prio = simulate(cfg(**slow), P)["metrics"]
        self.assertLess(prio["wait_kv_ms"] + prio["wait_experts_ms"], fifo["wait_kv_ms"] + fifo["wait_experts_ms"])

    def test_contention_bound_is_at_most_the_bandwidth_ratio_times_compute(self):
        c = cfg(base_weights="layer_rotation")
        m = simulate(c, P)["metrics"]
        ratio = c.hardware.copy_bandwidth / c.hardware.tier1_bandwidth
        self.assertGreater(m["tier1_contention_bound_ms"], 0)
        self.assertLessEqual(m["tier1_contention_bound_ms"], m["compute_ms"] * ratio + 1e-9)


class Capacity(unittest.TestCase):
    def test_tier1_never_exceeds_capacity(self):
        for c in (cfg(), cfg(base_weights="layer_rotation"), cfg(hot_kv_entries=0), cfg(expert_prefetch="last_step"),
                  cfg(expert_cache="per_layer")):
            result = simulate(c, P)
            self.assertIsNone(result["error"])
            for snap in result["snapshots"]:
                self.assertLessEqual(sum(snap["tier1"].values()), c.hardware.tier1_capacity + 1)

    def test_tier1_too_small_returns_error_with_a_trace(self):
        result = simulate(cfg(tier1_capacity="1 GB", scratch="0.1 GB"), P)
        self.assertIn("一级 DRAM", result["error"])
        self.assertEqual(result["events"][-1]["kind"], "capacity_error")
        self.assertTrue(result["snapshots"])
        self.assertFalse(result["feasible"])

    def test_tier2_too_small_stops_when_enforced(self):
        result = simulate(cfg(tier2_capacity="1 GB"), P)
        self.assertIn("二级 DRAM", result["error"])
        self.assertEqual(result["metrics"]["token_ms"], [])

    def test_tier2_too_small_runs_but_is_marked_infeasible_when_counterfactual(self):
        result = simulate(cfg(tier2_capacity="1 GB", tier2_capacity_check="counterfactual"), P)
        self.assertIsNone(result["error"])
        self.assertFalse(result["feasible"])
        self.assertIn("单卡不可行", result["infeasible"][0])
        self.assertEqual(len(result["metrics"]["token_ms"]), 3)


class ExpertCache(unittest.TestCase):
    def assert_within_slots(self, result, slots):
        for snap in result["snapshots"]:
            self.assertLessEqual(snap["cache"]["experts"], slots)
            self.assertLessEqual(snap["tier1"]["experts"], slots * P.expert_bytes + 1)

    def test_cache_accumulates_without_eviction_while_it_has_room(self):
        result = simulate(cfg(tier1_capacity="64 GB", tier2_capacity="128 GB", max_decode_steps=6), P)
        m = result["metrics"]
        self.assertEqual(m["evicted_experts"], 0)
        misses = m["expert_lookups"] - m["expert_hits"]
        self.assertEqual(result["per_step"][-1]["cache_experts"], misses)  # one entry per distinct (layer, expert)
        self.assertTrue(all(r["phase"] in ("cold", "filling") for r in result["per_step"]))

    def test_full_cache_evicts_and_stays_within_its_slots(self):
        slots = 2 * len(P.layers) * P.experts_per_token  # two steps' worth
        result = simulate(cfg(tier1_capacity="16 GB", tier2_capacity="128 GB", max_decode_steps=12,
                              expert_cache_capacity=f"{slots * P.expert_bytes:.0f} B"), P)
        m = result["metrics"]
        self.assertEqual(m["expert_cache_slots"], slots)
        self.assertGreater(m["evicted_experts"], 0)
        self.assert_within_slots(result, slots)
        self.assertIn("evicting", [r["phase"] for r in result["per_step"]])
        self.assertEqual(result["per_step"][-1]["cache_experts"], slots)  # stays full; contents are replaced

    def test_experts_in_use_or_in_transfer_are_never_evicted(self):
        # Exactly one layer's worth of slots: each layer evicts the previous layer's experts, never its own.
        slots = P.experts_per_token
        result = simulate(cfg(expert_cache_capacity=f"{slots * P.expert_bytes:.0f} B", expert_overlap=0.0), P)
        self.assertIsNone(result["error"])
        m = result["metrics"]
        self.assertEqual(m["evicted_experts"], m["expert_lookups"] - slots)

    def test_cache_smaller_than_one_layer_is_rejected(self):
        result = simulate(cfg(expert_cache_capacity=f"{(P.experts_per_token - 1) * P.expert_bytes:.0f} B"), P)
        self.assertIn("放不下一层的路由专家", result["error"])

    def test_cache_smaller_than_one_step_never_hits(self):
        one_step = len(P.layers) * P.experts_per_token * P.expert_bytes
        m = simulate(cfg(expert_cache_capacity=f"{one_step / 2:.0f} B", expert_overlap=1.0), P)["metrics"]
        self.assertEqual(m["expert_hits"], 0)

    def test_per_layer_policy_releases_experts_and_never_hits(self):
        result = simulate(cfg(expert_cache="per_layer", expert_overlap=1.0), P)
        m = result["metrics"]
        self.assertEqual((m["expert_hits"], m["evicted_experts"]), (0, 0))
        self.assertEqual(m["released_experts"], m["expert_lookups"])
        self.assertEqual(result["per_step"][-1]["cache_experts"], 0)

    def test_full_overlap_hits_everything_after_the_cold_step(self):
        m = simulate(cfg(expert_overlap=1.0, topk_overlap=1.0), P)["metrics"]
        layers, csa = len(P.layers), sum(l.kind == "csa" for l in P.layers)
        self.assertEqual(m["expert_hits"], 2 * layers * P.experts_per_token)
        self.assertEqual(m["kv_hits"], 2 * csa * P.index_topk)
        self.assertAlmostEqual(m["token_ms"][1], m["native_token_ms"], places=6)

    def test_without_hot_kv_cache_nothing_hits(self):
        self.assertEqual(simulate(cfg(hot_kv_entries=0, topk_overlap=1.0), P)["metrics"]["kv_hits"], 0)


class SteadyState(unittest.TestCase):
    def test_not_claimed_while_the_cache_is_still_filling(self):
        result = simulate(cfg(tier1_capacity="64 GB", tier2_capacity="128 GB", max_decode_steps=10), P)
        self.assertFalse(result["metrics"]["steady"]["reached"])

    def test_claimed_for_a_flat_tail_after_eviction_starts(self):
        rows = [{"step": i + 1, "phase": "cold" if i == 0 else "evicting", "token_ms": 10.0 if i == 0 else 5.0,
                 "expert_hits": 1, "expert_lookups": 2} for i in range(10)]
        steady = TwoTierSim.steady_state(rows)
        self.assertTrue(steady["reached"])
        self.assertEqual((steady["from_step"], steady["token_ms"]), (5, 5.0))

    def test_not_claimed_for_a_noisy_tail(self):
        rows = [{"step": i + 1, "phase": "evicting", "token_ms": 5.0 + (i % 2), "expert_hits": 1, "expert_lookups": 2}
                for i in range(10)]
        self.assertFalse(TwoTierSim.steady_state(rows)["reached"])


class Determinism(unittest.TestCase):
    def test_runs_are_deterministic(self):
        self.assertEqual(simulate(cfg(seed=3), P), simulate(cfg(seed=3), P))

    def test_unknown_config_fields_are_rejected(self):
        with self.assertRaises(ConfigError):
            TwoTierConfig.from_mapping({"tier1_gb": 96})


if __name__ == "__main__":
    unittest.main()
