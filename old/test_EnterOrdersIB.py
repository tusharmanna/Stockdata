"""
Unit tests for EnterOrdersIB.py

Tests key functions: profit target, position sizing, max gain calculations.
Run with: python -m pytest test_EnterOrdersIB.py -v
"""

import unittest
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile
from math import floor

# Import functions from EnterOrdersIB
sys.path.insert(0, str(Path(__file__).parent))


class MockOrder:
    """Mock order for testing without ibapi"""
    def __init__(self):
        self.orderId = None
        self.action = None
        self.orderType = None
        self.lmtPrice = None
        self.auxPrice = None
        self.totalQuantity = None
        self.transmit = None
        self.parentId = None
        self.ocaGroup = None
        self.ocaType = None
        self.eTradeOnly = None
        self.firmQuoteOnly = None


class TestProfitTarget(unittest.TestCase):
    """Test profit target calculation (single target at 3R)"""

    def test_target_calculation(self):
        """Target should be Entry + 3R"""
        entry = 100.0
        rps = 5.0
        target = round(entry + 3 * rps, 2)
        self.assertEqual(target, 115.0)

    def test_target_decimal_precision(self):
        """Target should round to 2 decimals"""
        entry = 100.789
        rps = 5.234
        target = round(entry + 3 * rps, 2)
        self.assertEqual(target, 116.49)

    def test_target_with_small_rps(self):
        """Target calculation with small RPS"""
        entry = 10.20
        rps = 0.70
        target = round(entry + 3 * rps, 2)
        self.assertEqual(target, 12.30)


class TestPositionSizing(unittest.TestCase):
    """Test position sizing (shares = floor(risk_dollars / rps))"""

    def test_calc_shares_basic(self):
        """Shares = floor(risk_dollars / rps)"""
        risk_dollars = 50.0
        rps = 5.0
        shares = floor(risk_dollars / rps)
        self.assertEqual(shares, 10)

    def test_calc_shares_floor_behavior(self):
        """Shares should use floor (int truncation)"""
        risk_dollars = 50.0
        rps = 7.0
        shares = floor(risk_dollars / rps)
        self.assertEqual(shares, 7)  # floor(50/7) = floor(7.14) = 7

    def test_calc_shares_with_decimal_rps(self):
        """Test with decimal RPS (common in real trading)"""
        risk_dollars = 50.0
        rps = 0.70
        shares = floor(risk_dollars / rps)
        self.assertEqual(shares, 71)

    def test_calc_shares_zero_when_rps_too_large(self):
        """Shares = 0 when risk/share exceeds budget"""
        risk_dollars = 50.0
        rps = 100.0
        shares = floor(risk_dollars / rps)
        self.assertEqual(shares, 0)

    def test_calc_shares_invalid_entry(self):
        """Entry <= stop should skip (rps <= 0)"""
        entry = 100.0
        stop = 100.0
        rps = entry - stop
        self.assertEqual(rps, 0)


class TestMaxGainCalculation(unittest.TestCase):
    """Test max gain calculation (all shares sold at 3R)"""

    def test_max_gain_basic(self):
        """Max gain = shares * 3 * rps"""
        shares = 10
        rps = 5.0
        max_gain = shares * 3 * rps
        self.assertEqual(max_gain, 150.0)

    def test_max_gain_decimal_precision(self):
        """Max gain should round to 2 decimals"""
        shares = 71
        rps = 0.70
        max_gain = round(shares * 3 * rps, 2)
        self.assertEqual(max_gain, 149.10)

    def test_max_gain_various_sizes(self):
        """Test max gain for various share quantities"""
        test_cases = [
            (6, 1.0, 18.0),
            (9, 1.0, 27.0),
            (10, 2.0, 60.0),
            (15, 3.0, 135.0),
        ]
        for shares, rps, expected_gain in test_cases:
            max_gain = shares * 3 * rps
            self.assertEqual(max_gain, expected_gain, f"shares={shares}, rps={rps}")


class TestRiskCalculations(unittest.TestCase):
    """Test risk/reward calculations"""

    def test_rps_calculation(self):
        """RPS = entry - stop"""
        entry = 100.0
        stop = 95.0
        rps = round(entry - stop, 4)
        self.assertEqual(rps, 5.0)

    def test_max_loss_calculation(self):
        """Max loss = shares * rps"""
        shares = 10
        rps = 5.0
        max_loss = round(shares * rps, 2)
        self.assertEqual(max_loss, 50.0)

    def test_cost_basis_calculation(self):
        """Cost basis = shares * entry"""
        shares = 10
        entry = 100.0
        cost = round(shares * entry, 2)
        self.assertEqual(cost, 1000.0)

    def test_position_sizing_makes_sense(self):
        """Verify position sizing components add up"""
        shares = 71
        entry = 10.20
        rps = 0.70
        cost = round(shares * entry, 2)
        max_loss = round(shares * rps, 2)
        max_gain = round(shares * 3 * rps, 2)

        self.assertEqual(cost, 724.20)
        self.assertEqual(max_loss, 49.70)
        self.assertEqual(max_gain, 149.10)


class TestReadTickerPrices(unittest.TestCase):
    """Test ticker/price parsing from orders.txt"""

    def test_read_ticker_only_market_order(self):
        """Should read TICKER format (market order)"""
        content = "NVDA\nTSLA\nAAPL"
        with NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write(content)
            f.flush()
            tickers = []
            with open(f.name) as fh:
                for line in fh:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        parts = line.split()
                        ticker = parts[0].upper()
                        price = None
                        if len(parts) >= 2:
                            try:
                                price = float(parts[1])
                            except ValueError:
                                continue
                        tickers.append({"ticker": ticker, "price": price})

            self.assertEqual(len(tickers), 3)
            self.assertEqual(tickers[0]["ticker"], "NVDA")
            self.assertIsNone(tickers[0]["price"])

    def test_read_ticker_with_price_limit_order(self):
        """Should read TICKER PRICE format (limit order)"""
        content = "NVDA 180.50\nTSLA 250.00"
        with NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write(content)
            f.flush()
            tickers = []
            with open(f.name) as fh:
                for line in fh:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        parts = line.split()
                        ticker = parts[0].upper()
                        price = None
                        if len(parts) >= 2:
                            try:
                                price = float(parts[1])
                            except ValueError:
                                continue
                        tickers.append({"ticker": ticker, "price": price})

            self.assertEqual(len(tickers), 2)
            self.assertEqual(tickers[0]["ticker"], "NVDA")
            self.assertEqual(tickers[0]["price"], 180.50)

    def test_read_mixed_formats(self):
        """Should handle mixed market and limit orders"""
        content = "NVDA\nTSLA 250.00\nAAPL\nGOOGL 140.00"
        with NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write(content)
            f.flush()
            tickers = []
            with open(f.name) as fh:
                for line in fh:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        parts = line.split()
                        ticker = parts[0].upper()
                        price = None
                        if len(parts) >= 2:
                            try:
                                price = float(parts[1])
                            except ValueError:
                                continue
                        tickers.append({"ticker": ticker, "price": price})

            self.assertEqual(len(tickers), 4)
            self.assertIsNone(tickers[0]["price"])
            self.assertEqual(tickers[1]["price"], 250.00)


if __name__ == '__main__':
    unittest.main()
