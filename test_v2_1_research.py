"""Deterministic tests for the isolated V2.1 research engine."""

import unittest

import numpy as np
import pandas as pd

from v2_1_research import (
    MarketData,
    StrategyConfig,
    annualized_vol,
    apply_deadband,
    binary_regime,
    conservative_tax_path,
    pareto_frontier,
)
from v2_1_walkforward import choose_on_training, safety_family
from v2_1_shadow_signal import classify_action


class V21ResearchTests(unittest.TestCase):
    def test_rolling_vol_has_no_backfill_lookahead(self):
        idx = pd.date_range("2020-01-01", periods=30, freq="B")
        ret = pd.Series(np.linspace(-0.02, 0.02, len(idx)), index=idx)
        vol = annualized_vol(ret, "roll20")
        self.assertTrue(vol.iloc[:19].isna().all())
        self.assertTrue(np.isfinite(vol.iloc[19]))

    def test_future_return_does_not_change_past_vol(self):
        idx = pd.date_range("2020-01-01", periods=80, freq="B")
        base = pd.Series(np.sin(np.arange(80)) / 100, index=idx)
        changed = base.copy()
        changed.iloc[-1] = 0.50
        left = annualized_vol(base, "roll20")
        right = annualized_vol(changed, "roll20")
        pd.testing.assert_series_equal(left.iloc[:-1], right.iloc[:-1])

    def test_hybrid_vol_is_never_below_roll20(self):
        idx = pd.date_range("2020-01-01", periods=100, freq="B")
        ret = pd.Series(np.sin(np.arange(100)) / 50, index=idx)
        roll = annualized_vol(ret, "roll20")
        hybrid = annualized_vol(ret, "maxroll20_down20")
        valid = roll.notna() & hybrid.notna()
        self.assertTrue((hybrid[valid] >= roll[valid]).all())

    def test_deadband_reduces_small_rebalances(self):
        idx = pd.date_range("2020-01-01", periods=5, freq="B")
        target = pd.Series([0.50, 0.51, 0.515, 0.53, 0.52], index=idx)
        actual = apply_deadband(target, 0.02)
        expected = pd.Series([0.50, 0.50, 0.50, 0.53, 0.53], index=idx)
        pd.testing.assert_series_equal(actual, expected)

    def test_binary_gate_requires_reentry_days(self):
        idx = pd.date_range("2020-01-01", periods=8, freq="B")
        close = pd.Series([100, 100, 100, 80, 86, 86, 86, 86], index=idx)
        regime, _ = binary_regime(close, high_period=3, threshold=0.15, reentry_days=3)
        self.assertEqual(regime.iloc[3], 0.0)
        self.assertEqual(regime.iloc[5], 0.0)
        self.assertEqual(regime.iloc[6], 1.0)

    def test_tax_stress_never_increases_terminal_value(self):
        idx = pd.date_range("2020-01-01", periods=504, freq="B")
        ret = pd.Series(0.0005, index=idx)
        taxed = conservative_tax_path(ret, 0.24)
        self.assertLess((1 + taxed).prod(), (1 + ret).prod())

    def test_pareto_frontier_removes_dominated_row(self):
        frame = pd.DataFrame({
            "name": ["a", "b", "c"],
            "cagr": [0.20, 0.22, 0.18],
            "dd": [-0.30, -0.35, -0.40],
        })
        names = set(pareto_frontier(frame, "cagr", "dd")["name"])
        self.assertEqual(names, {"a", "b"})

    def test_default_config_preserves_no_margin_cap(self):
        self.assertEqual(StrategyConfig(name="x").cap, 1.0)

    def test_walkforward_choice_cannot_see_future_returns(self):
        idx = pd.date_range("2010-01-01", "2016-12-31", freq="B")
        rng = np.random.default_rng(7)
        qret = pd.Series(rng.normal(0.0003, 0.01, len(idx)), index=idx)
        tret = (3.0 * qret).clip(lower=-0.90)

        def market(asset_ret):
            return MarketData(
                index=idx,
                qqq_close=100.0 * (1.0 + qret).cumprod(),
                qqq_ret=qret,
                tqqq_ret=asset_ret,
                synthetic_ret=asset_ret,
                combined_ret=asset_ret,
                rf_daily=pd.Series(0.02 / 252, index=idx),
                vix=pd.Series(20.0, index=idx),
                vix3m=pd.Series(22.0, index=idx),
                actual_mask=pd.Series(True, index=idx),
            )

        changed = tret.copy()
        changed.loc[changed.index > "2014-12-31"] = -0.25
        first, score1 = choose_on_training(market(tret), safety_family(), "2014-12-31")
        second, score2 = choose_on_training(market(changed), safety_family(), "2014-12-31")
        self.assertEqual(first, second)
        self.assertAlmostEqual(score1, score2)

    def test_shadow_action_classification(self):
        self.assertEqual(classify_action(0.0, 0.5), "ENTER")
        self.assertEqual(classify_action(0.5, 0.0), "EXIT")
        self.assertEqual(classify_action(0.50, 0.53), "INCREASE")
        self.assertEqual(classify_action(0.50, 0.49), "REDUCE")
        self.assertEqual(classify_action(0.50, 0.503), "HOLD")


if __name__ == "__main__":
    unittest.main()
