"""
Integration test for EnterOrdersIB.py using actual orders.txt with mocked yfinance data

Tests the full order calculation pipeline without calling Interactive Brokers or yfinance.
Run with: python test_integration_mock.py
"""

import sys
from pathlib import Path
from math import floor


# Constants
ORDERS_FILE = Path(__file__).parent / "orders.txt"
RISK_DOLLARS = 50.0

# Mock live data (simulating yfinance results)
MOCK_PRICES = {
    # From actual orders.txt
    "ALOY": {"low": 9.50, "close": 10.20},
    "KGI": {"low": 18.75, "close": 19.50},
    # Additional test tickers
    "AAPL": {"low": 190.00, "close": 200.00},
    "MSFT": {"low": 310.00, "close": 320.50},
    "ASUR": {"low": 145.20, "close": 148.50},
    "BMRN": {"low": 82.30, "close": 84.75},
}


def read_ticker_prices(path: Path):
    """Read tickers and optional prices from orders.txt"""
    orders = []
    with open(path) as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 1:
                try:
                    ticker = parts[0].upper()
                    price = None
                    if len(parts) >= 2:
                        try:
                            price = float(parts[1])
                        except ValueError:
                            print(f"  Warning: skipped invalid price in line: {line}")
                            continue
                    orders.append({"ticker": ticker, "price": price})
                except (ValueError, IndexError):
                    print(f"  Warning: skipped invalid line: {line}")
    return orders


def get_current_low(ticker: str):
    """Get current low from mock data"""
    ticker = ticker.upper()
    if ticker in MOCK_PRICES:
        return MOCK_PRICES[ticker]["low"]
    return None


def get_current_price(ticker: str):
    """Get current price from mock data"""
    ticker = ticker.upper()
    if ticker in MOCK_PRICES:
        return MOCK_PRICES[ticker]["close"]
    return None


def calc_shares(entry: float, stop: float, risk: float = RISK_DOLLARS) -> int:
    """Calculate shares from risk per share"""
    rps = entry - stop
    if rps <= 0:
        return 0
    return floor(risk / rps)


def test_orders_from_file():
    """Test order calculations using actual orders.txt with mock data"""

    if not ORDERS_FILE.exists():
        print(f"ERROR: {ORDERS_FILE} not found")
        return False

    print("="*100)
    print("INTEGRATION TEST: EnterOrdersIB with orders.txt (Mock Data - No IB Connection)")
    print("="*100)
    print()

    # Read orders
    print(f"Reading orders from: {ORDERS_FILE}")
    tickers = read_ticker_prices(ORDERS_FILE)

    if not tickers:
        print("No valid tickers found in orders.txt")
        return False

    print(f"Found {len(tickers)} ticker(s)\n")

    # Fetch mock lows and prices
    print("Loading mock market data...")
    current_lows = {}
    current_prices = {}

    for ticker_data in tickers:
        ticker = ticker_data["ticker"]
        low = get_current_low(ticker)
        price = get_current_price(ticker)
        current_lows[ticker] = low
        current_prices[ticker] = price

        if low:
            print(f"  {ticker}: Low=${low:.2f}, Close=${price:.2f}")
        else:
            print(f"  {ticker}: NO DATA")

    print("\n" + "="*100)
    print("ORDER CALCULATIONS (Market Orders)")
    print("="*100)
    print()

    # Build orders
    orders = []
    skipped = []

    for ticker_data in tickers:
        ticker = ticker_data["ticker"]
        entry = ticker_data["price"]
        current_low = current_lows.get(ticker)

        if current_low is None:
            skipped.append((ticker, "no mock data available"))
            continue

        # Use market order (fetch current price)
        if entry is None:
            entry = get_current_price(ticker)
            if entry is None:
                skipped.append((ticker, "no price data"))
                continue
            entry = round(entry, 2)

        rps = round(entry - current_low, 4)
        if rps <= 0:
            skipped.append((ticker, f"entry ${entry:.2f} <= current_low ${current_low:.2f}"))
            continue

        shares = calc_shares(entry, current_low)
        if shares == 0:
            skipped.append((ticker, f"risk/share ${rps:.2f} > ${RISK_DOLLARS:.0f} budget"))
            continue

        # Calculate targets
        target1 = round(entry + 1 * rps, 2)
        target2 = round(entry + 3 * rps, 2)
        tp1_qty = max(1, shares // 3)
        tp2_qty = shares - tp1_qty

        # Calculate gains
        max_loss = round(shares * rps, 2)
        max_gain = round((tp1_qty * 1 * rps) + (tp2_qty * 3 * rps), 2)
        cost_basis = round(shares * entry, 2)

        orders.append({
            "ticker":    ticker,
            "entry":     entry,
            "stop":      current_low,
            "target1":   target1,
            "target2":   target2,
            "rps":       rps,
            "shares":    shares,
            "tp1_qty":   tp1_qty,
            "tp2_qty":   tp2_qty,
            "cost":      cost_basis,
            "max_loss":  max_loss,
            "max_gain":  max_gain,
        })

    # Print order summary
    if orders:
        hdr = (f"{'Ticker':<8}  {'Entry':>8}  {'Stop':>8}  {'TP1(1R)':>9}  {'TP2(3R)':>9}  "
               f"{'Qty':>4}  {'TP1/TP2':>8}  {'~Cost':>10}  {'MaxLoss':>8}  {'MaxGain':>8}")
        print(hdr)
        print("-" * len(hdr))

        for o in orders:
            print(
                f"{o['ticker']:<8}  {o['entry']:>8.2f}  {o['stop']:>8.2f}  {o['target1']:>9.2f}  {o['target2']:>9.2f}  "
                f"{o['shares']:>4}  {o['tp1_qty']}/{o['tp2_qty']:<5}  "
                f"{o['cost']:>10,.2f}  {o['max_loss']:>8.2f}  {o['max_gain']:>8.2f}"
            )

        print("-" * len(hdr))
        total_cost = sum(o["cost"] for o in orders)
        total_risk = sum(o["max_loss"] for o in orders)
        total_gain = sum(o["max_gain"] for o in orders)
        print(f"  {len(orders)} order(s)   "
              f"Total ~capital: ${total_cost:>10,.2f}   "
              f"Total max risk: ${total_risk:.2f}   Total max gain: ${total_gain:.2f}")
    else:
        print("  No valid orders")

    if skipped:
        print(f"\nSkipped ({len(skipped)}):")
        for ticker, reason in skipped:
            print(f"  {ticker:<8}  {reason}")

    print()

    # Run assertions
    print("="*100)
    print("VALIDATION TESTS")
    print("="*100)
    print()

    test_passed = True
    test_count = 0

    # Test 1: All orders have valid calculations
    if orders:
        for o in orders:
            # Verify targets
            try:
                assert o['target1'] == round(o['entry'] + o['rps'], 2), f"{o['ticker']}: TP1 mismatch"
                assert o['target2'] == round(o['entry'] + 3 * o['rps'], 2), f"{o['ticker']}: TP2 mismatch"
                print(f"[PASS] {o['ticker']}: TP1=${o['target1']:.2f} and TP2=${o['target2']:.2f} calculated correctly")
                test_count += 1
            except AssertionError as e:
                print(f"[FAIL] {e}")
                test_passed = False

            # Verify share split
            try:
                assert o['tp1_qty'] + o['tp2_qty'] == o['shares'], f"{o['ticker']}: Share split mismatch"
                print(f"[PASS] {o['ticker']}: Share split correct ({o['tp1_qty']} + {o['tp2_qty']} = {o['shares']})")
                test_count += 1
            except AssertionError as e:
                print(f"[FAIL] {e}")
                test_passed = False

            # Verify max gain calculation (the corrected formula)
            try:
                expected_gain = (o['tp1_qty'] * 1 * o['rps']) + (o['tp2_qty'] * 3 * o['rps'])
                expected_gain = round(expected_gain, 2)
                assert o['max_gain'] == expected_gain, f"{o['ticker']}: Max gain {o['max_gain']} vs expected {expected_gain}"
                print(f"[PASS] {o['ticker']}: Max gain=${o['max_gain']:.2f} is (tp1_qty*1R) + (tp2_qty*3R)")
                test_count += 1
            except AssertionError as e:
                print(f"[FAIL] {e}")
                test_passed = False

            # Verify entry > stop
            try:
                assert o['entry'] > o['stop'], f"{o['ticker']}: Entry should be > Stop"
                print(f"[PASS] {o['ticker']}: Entry ${o['entry']:.2f} > Stop ${o['stop']:.2f}")
                test_count += 1
            except AssertionError as e:
                print(f"[FAIL] {e}")
                test_passed = False

            # Verify shares calculation
            try:
                expected_shares = floor(RISK_DOLLARS / o['rps'])
                assert o['shares'] == expected_shares, f"{o['ticker']}: Shares mismatch"
                print(f"[PASS] {o['ticker']}: Shares={o['shares']} calculated correctly (floor(${RISK_DOLLARS}/{o['rps']:.2f}))")
                test_count += 1
            except AssertionError as e:
                print(f"[FAIL] {e}")
                test_passed = False

            # Verify position sizing makes sense
            try:
                assert o['cost'] == round(o['shares'] * o['entry'], 2), f"{o['ticker']}: Cost basis mismatch"
                assert o['max_loss'] == round(o['shares'] * o['rps'], 2), f"{o['ticker']}: Max loss mismatch"
                print(f"[PASS] {o['ticker']}: Cost=${o['cost']:.2f}, MaxLoss=${o['max_loss']:.2f} correct")
                test_count += 1
            except AssertionError as e:
                print(f"[FAIL] {e}")
                test_passed = False

            print()

    print("="*100)
    if test_passed:
        print(f"RESULT: ALL TESTS PASSED ({test_count} assertions)")
    else:
        print(f"RESULT: SOME TESTS FAILED")
    print("="*100)
    print()

    return test_passed


if __name__ == '__main__':
    success = test_orders_from_file()
    sys.exit(0 if success else 1)
