"""Behavior checks for the two-tier DRAM model. Run: python3 -m unittest -v test_model (from this folder)."""

import unittest

from model import CapacityError, Config, simulate


def phases(result, step, layer):
    return [s for s in result["compute_segments"] if s["step"] == step and s["layer"] == layer]


class TwoTierDram(unittest.TestCase):
    def test_tier1_never_exceeds_capacity(self):
        for cfg in (Config(), Config(tier1_mb=28.0), Config(hot_kv_entries=0), Config(link_mb_per_ms=1.0)):
            result = simulate(cfg)
            self.assertIsNone(result["error"])
            for snap in result["snapshots"]:
                self.assertLessEqual(sum(snap["tier1"].values()), cfg.tier1_mb + 1e-9)
            self.assertLessEqual(result["metrics"]["peak_tier1_mb"], cfg.tier1_mb + 1e-9)

    def test_compute_starts_only_after_data_arrives(self):
        result = simulate(Config(prefetch=False, hot_kv_entries=0))
        jobs = result["jobs"]
        for step in range(3):
            for layer in range(4):
                segs = {s["phase"]: s for s in phases(result, step, layer)}
                weights = [j for j in jobs if j["kind"] == "demand_weights" and j["label"].startswith(f"按需取 L{layer} ")
                           and j["queued"] <= segs["indexer"]["t0"]][-1]
                kv = [j for j in jobs if j["kind"] == "demand_kv" and j["label"].startswith(f"按需取 L{layer} ")
                      and j["queued"] <= segs["attention"]["t0"]][-1]
                self.assertGreaterEqual(segs["indexer"]["t0"], weights["end"] - 1e-9)
                self.assertGreaterEqual(segs["attention"]["t0"], kv["end"] - 1e-9)

    def test_link_never_exceeds_bandwidth_and_serves_one_job_at_a_time(self):
        cfg = Config(link_mb_per_ms=1.0)
        result = simulate(cfg)
        moved = sum(result["metrics"]["link_mb"].values())
        self.assertLessEqual(moved, result["metrics"]["link_busy_ms"] * cfg.link_mb_per_ms + 1e-6)
        segs = sorted(result["link_segments"], key=lambda s: s["t0"])
        for a, b in zip(segs, segs[1:]):
            self.assertLessEqual(a["t1"], b["t0"] + 1e-9)

    def test_every_byte_requested_is_delivered(self):
        result = simulate(Config())
        self.assertAlmostEqual(sum(j["mb"] for j in result["jobs"]), sum(result["metrics"]["link_mb"].values()), places=6)

    def test_without_prefetch_or_cache_every_layer_pays_two_demand_fetches(self):
        cfg = Config(prefetch=False, hot_kv_entries=0)
        m = simulate(cfg)["metrics"]
        per_layer = (cfg.t_indexer_ms + cfg.t_attention_ms + cfg.t_moe_ms + 2 * cfg.link_setup_ms
                     + (cfg.bundle_mb + cfg.topk * cfg.kv_entry_mb) / cfg.link_mb_per_ms)
        self.assertEqual(m["token_ms"], [round(cfg.layers * per_layer, 6)] * cfg.steps)
        self.assertEqual(m["kv_hits"], 0)
        self.assertEqual(m["link_mb"]["prefetch"], 0)

    def test_very_fast_link_degenerates_to_compute_only(self):
        # 1e6 MB/ms keeps each transfer above float resolution; faster links round busy time to zero.
        cfg = Config(link_mb_per_ms=1e6, link_setup_ms=0.0)
        m = simulate(cfg)["metrics"]
        for token in m["token_ms"]:
            self.assertAlmostEqual(token, m["compute_only_token_ms"], places=3)

    def test_zero_overlap_never_hits_and_full_overlap_always_hits_after_warmup(self):
        self.assertEqual(simulate(Config(overlap=0.0))["metrics"]["kv_hits"], 0)
        cfg = Config(overlap=1.0)
        m = simulate(cfg)["metrics"]
        self.assertEqual(m["kv_hits"], (cfg.steps - 1) * cfg.layers * cfg.topk)

    def test_demand_first_makes_kv_wait_shorter_than_fifo(self):
        fifo = simulate(Config(link_mb_per_ms=1.0, link_policy="fifo"))["metrics"]
        prio = simulate(Config(link_mb_per_ms=1.0))["metrics"]
        self.assertLess(prio["wait_kv_ms"], fifo["wait_kv_ms"])

    def test_tier1_too_small_stops_with_a_partial_trace(self):
        result = simulate(Config(tier1_mb=22.0))
        self.assertIn("一级 DRAM 容量不足", result["error"])
        self.assertTrue(result["snapshots"])
        self.assertEqual(result["events"][-1]["kind"], "capacity_error")

    def test_tier2_too_small_is_rejected_before_running(self):
        with self.assertRaises(CapacityError):
            simulate(Config(tier2_mb=10.0))

    def test_runs_are_deterministic(self):
        self.assertEqual(simulate(Config(seed=3)), simulate(Config(seed=3)))


if __name__ == "__main__":
    unittest.main()
