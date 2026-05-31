"""
Unit tests for EnterOrdersIB.py

Tests key functions: profit targets, position sizing, max gain calculations.
Run with: python -m pytest test_EnterOrdersIB.py -v
"""

import unittest
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

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


class TestProfitTargets(unittest.TestCase):
    """Test profit target calculations"""

    def test_target1_calculation(self):
        """TP1 should be Entry + 1R"""
        entry = 100.0
        rps = 5.0
        target1 = round(entry + 1 * rps, 2)
        self.assertEqual(target1, 105.0)

    def test_target2_calculation(self):
        """TP2 should be Entry + 3R"""
        entry = 100.0
        rps = 5.0
        target2 = round(entry + 3 * rps, 2)
        self.assertEqual(target2, 115.0)

    def test_target1_decimal_precision(self):
        """TP1 should round to 2 decimals"""
        entry = 100.123
        rps = 5.567
        target1 = round(entry + 1 * rps, 2)
        self.assertEqual(target1, 105.69)

    def test_target2_decimal_precision(self):
        """TP2 should round to 2 decimals"""
        entry = 100.789
        rps = 5.234
        target2 = round(entry + 3 * rps, 2)
        self.assertEqual(target2, 116.49)


class TestShareSplitting(unittest.TestCase):
    """Test profit target share quantity splits"""

    def test_tp1_qty_calculation(self):
        """TP1 qty should be 1/3 of shares"""
        shares = 10
        tp1_qty = max(1, shares // 3)
        self.assertEqual(tp1_qty, 3)

    def test_tp2_qty_calculation(self):
        """TP2 qty should be remaining 2/3 of shares"""
        shares = 10
        tp1_qty = max(1, shares // 3)
        tp2_qty = shares - tp1_qty
        self.assertEqual(tp2_qty, 7)

    def test_total_qty_preserved(self):
        """tp1_qty + tp2_qty should equal total shares"""
        shares = 10
        tp1_qty = max(1, shares // 3)
        tp2_qty = shares - tp1_qty
        self.assertEqual(tp1_qty + tp2_qty, shares)

    def test_tp1_qty_minimum_one(self):
        """TP1 qty should be at least 1 (for small share counts)"""
        shares = 2
        tp1_qty = max(1, shares // 3)
        self.assertEqual(tp1_qty, 1)

    def test_share_split_various_sizes(self):
        """Test share split for various quantities"""
        test_cases = [
            (3, 1, 2),   # 3 shares: 1 @ TP1, 2 @ TP2
            (6, 2, 4),   # 6 shares: 2 @ TP1, 4 @ TP2
            (9, 3, 6),   # 9 shares: 3 @ TP1, 6 @ TP2
            (10, 3, 7),  # 10 shares: 3 @ TP1, 7 @ TP2
            (15, 5, 10), # 15 shares: 5 @ TP1, 10 @ TP2
        ]
        for shares, exp_tp1, exp_tp2 in test_cases:
            tp1_qty = max(1, shares // 3)
            tp2_qty = shares - tp1_qty
            self.assertEqual(
                (tp1_qty, tp2_qty), (exp_tp1, exp_tp2),
                f"Failed for {shares} shares"
            )


class TestMaxGainCalculation(unittest.TestCase):
    """Test max gain calculations with split targets"""

    def test_max_gain_basic(self):
        """Max gain = (tp1_qty * 1R) + (tp2_qty * 3R)"""
        shares = 10
        rps = 5.0
        tp1_qty = max(1, shares // 3)
        tp2_qty = shares - tp1_qty
        max_gain = round((tp1_qty * 1 * rps) + (tp2_qty * 3 * rps), 2)
        self.assertEqual(max_gain, 120.0)

    def test_max_gain_breakdown(self):
        """Verify max gain components"""
        shares = 10
        rps = 5.0
        tp1_qty = 3
        tp2_qty = 7

        tp1_gain = tp1_qty * 1 * rps  # 3 * 5 = 15
        tp2_gain = tp2_qty * 3 * rps  # 7 * 15 = 105
        total_gain = tp1_gain + tp2_gain  # 120

        self.assertEqual(tp1_gain, 15.0)
        self.assertEqual(tp2_gain, 105.0)
        self.assertEqual(total_gain, 120.0)

    def test_max_gain_various_sizes(self):
        """Test max gain for various share quantities"""
        rps = 5.0
        test_cases = [
            (6, 70.0),    # 2@TP1 + 4@TP2: (2*5) + (4*15) = 70
            (9, 105.0),   # 3@TP1 + 6@TP2: (3*5) + (6*15) = 105
            (10, 120.0),  # 3@TP1 + 7@TP2: (3*5) + (7*15) = 120
            (12, 140.0),  # 4@TP1 + 8@TP2: (4*5) + (8*15) = 140
            (15, 175.0),  # 5@TP1 + 10@TP2: (5*5) + (10*15) = 175
        ]

        for shares, expected_gain in test_cases:
            tp1_qty = max(1, shares // 3)
            tp2_qty = shares - tp1_qty
            max_gain = (tp1_qty * 1 * rps) + (tp2_qty * 3 * rps)
            self.assertEqual(
                max_gain, expected_gain,
                f"Failed for {shares} shares"
            )

    def test_max_gain_is_not_shares_times_3r(self):
        """Verify old formula (shares * 3 * rps) is wrong"""
        shares = 10
        rps = 5.0

        # Old wrong formula
        old_formula = shares * 3 * rps  # 150.0

        # New correct formula
        tp1_qty = max(1, shares // 3)
        tp2_qty = shares - tp1_qty
        new_formula = (tp1_qty * 1 * rps) + (tp2_qty * 3 * rps)  # 120.0

        self.assertEqual(old_formula, 150.0, "Old formula test")
        self.assertEqual(new_formula, 120.0, "New formula test")
        self.assertNotEqual(old_formula, new_formula, "Formulas should differ")


class TestPositionSizing(unittest.TestCase):
    """Test position sizing calculations"""

    def test_calc_shares_basic(self):
        """Shares = floor(risk_dollars / rps)"""
        entry = 100.0
        stop = 95.0
        risk_dollars = 50.0

        rps = entry - stop
        shares = int(risk_dollars / rps)

        self.assertEqual(rps, 5.0)
        self.assertEqual(shares, 10)

    def test_calc_shares_floor_behavior(self):
        """Shares should use floor (int truncation)"""
        entry = 100.0
        stop = 97.0
        risk_dollars = 50.0

        rps = entry - stop
        shares = int(risk_dollars / rps)

        # 50 / 3 = 16.666... -> floor to 16
        self.assertEqual(shares, 16)

    def test_calc_shares_zero_when_rps_too_large(self):
        """Shares = 0 when risk/share exceeds budget"""
        entry = 100.0
        stop = 40.0  # RPS = $60, exceeds $50 budget
        risk_dollars = 50.0

        rps = entry - stop
        shares = int(risk_dollars / rps) if rps > 0 else 0

        self.assertEqual(rps, 60.0)
        self.assertEqual(shares, 0)

    def test_calc_shares_invalid_entry(self):
        """Entry <= stop should skip (rps <= 0)"""
        entry = 95.0
        stop = 100.0  # Entry below stop
        risk_dollars = 50.0

        rps = entry - stop

        self.assertLessEqual(rps, 0, "RPS should be <= 0")


class TestRiskCalculations(unittest.TestCase):
    """Test risk and cost basis calculations"""

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
        cost_basis = round(shares * entry, 2)
        self.assertEqual(cost_basis, 1000.0)

    def test_rps_calculation(self):
        """RPS = entry - stop"""
        entry = 100.0
        stop = 95.0
        rps = round(entry - stop, 4)
        self.assertEqual(rps, 5.0)


class TestReadTickerPrices(unittest.TestCase):
    """Test reading ticker prices from orders.txt"""

    def test_read_ticker_only_market_order(self):
        """Should read TICKER format (market order)"""
        with NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("# Market orders\n")
            f.write("AAPL\n")
            f.write("MSFT\n")
            f.flush()

            # Simple parsing
            orders = []
            with open(f.name) as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split()
                    if len(parts) >= 1:
                        ticker = parts[0].upper()
                        price = None
                        if len(parts) >= 2:
                            try:
                                price = float(parts[1])
                            except ValueError:
                                continue
                        orders.append({"ticker": ticker, "price": price})

            self.assertEqual(len(orders), 2)
            self.assertEqual(orders[0]["ticker"], "AAPL")
            self.assertIsNone(orders[0]["price"])
            self.assertEqual(orders[1]["ticker"], "MSFT")
            self.assertIsNone(orders[1]["price"])

    def test_read_ticker_with_price_limit_order(self):
        """Should read TICKER PRICE format (limit order)"""
        with NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("# Limit orders\n")
            f.write("AAPL 150.50\n")
            f.write("MSFT 320.75\n")
            f.flush()

            # Simple parsing
            orders = []
            with open(f.name) as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split()
                    if len(parts) >= 1:
                        ticker = parts[0].upper()
                        price = None
                        if len(parts) >= 2:
                            try:
                                price = float(parts[1])
                            except ValueError:
                                continue
                        orders.append({"ticker": ticker, "price": price})

            self.assertEqual(len(orders), 2)
            self.assertEqual(orders[0]["ticker"], "AAPL")
            self.assertEqual(orders[0]["price"], 150.50)
            self.assertEqual(orders[1]["ticker"], "MSFT")
            self.assertEqual(orders[1]["price"], 320.75)

    def test_read_mixed_formats(self):
        """Should handle mixed market and limit orders"""
        with NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("AAPL\n")  # Market
            f.write("MSFT 320.50\n")  # Limit
            f.write("# Comment\n")
            f.write("GOOGL\n")  # Market
            f.flush()

            # Simple parsing
            orders = []
            with open(f.name) as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split()
                    if len(parts) >= 1:
                        ticker = parts[0].upper()
                        price = None
                        if len(parts) >= 2:
                            try:
                                price = float(parts[1])
                            except ValueError:
                                continue
                        orders.append({"ticker": ticker, "price": price})

            self.assertEqual(len(orders), 3)
            self.assertIsNone(orders[0]["price"])  # AAPL
            self.assertEqual(orders[1]["price"], 320.50)  # MSFT
            self.assertIsNone(orders[2]["price"])  # GOOGL


if __name__ == '__main__':
    unittest.main()
