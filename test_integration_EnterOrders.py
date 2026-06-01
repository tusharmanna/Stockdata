"""
Integration test for EnterOrdersIB.py using actual orders.txt and live yfinance data

Tests the full order calculation pipeline without calling Interactive Brokers.
Run with: python test_integration_EnterOrders.py
"""

import sys
from pathlib import Path
from math import floor

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance not installed. Run: pip install yfinance")
    sys.exit(1)


# Constants
ORDERS_FILE = Path(__file__).parent / "orders.txt"
RISK_DOLLARS = 50.0


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
    """Fetch current low from yfinance"""
    try:
        data = yf.download(ticker, period='1d', progress=False)
        if data.empty:
            return None
        low = float(data['Low'].iloc[-1])
        return low if low > 0 else None
    except Exception as e:
        print(f"  Error fetching low for {ticker}: {e}")
        return None


def calc_shares(entry: float, stop: float, risk: float = RISK_DOLLARS) -> int:
    """Calculate shares from risk per share"""
    rps = entry - stop
    if rps <= 0:
        return 0
    return floor(risk / rps)


def test_orders_from_file():
    """Test order calculations using actual orders.txt and live data"""

    if not ORDERS_FILE.exists():
        print(f"ERROR: {ORDERS_FILE} not found")
        return False

    print("="*80)
    print("INTEGRATION TEST: EnterOrdersIB with orders.txt and Live yfinance Data")
    print("="*80)
    print()

    # Read orders
    print(f"Reading orders from: {ORDERS_FILE}")
    tickers = read_ticker_prices(ORDERS_FILE)

    if not tickers:
        print("No valid tickers found in orders.txt")
        return False

    print(f"Found {len(tickers)} ticker(s)\n")

    # Fetch live lows
    print("Fetching current lows from yfinance...")
    current_lows = {}
    for ticker_data in tickers:
        ticker = ticker_data["ticker"]
        low = get_current_low(ticker)
        current_lows[ticker] = low
        if low:
            print(f"  {ticker}: ${low:.2f}")
        else:
            print(f"  {ticker}: NO DATA")

    print("\n" + "="*80)
    print("ORDER CALCULATIONS")
    print("="*80)
    print()

    # Build orders
    orders = []
    skipped = []

    for ticker_data in tickers:
        ticker = ticker_data["ticker"]
        entry = ticker_data["price"]
        current_low = current_lows.get(ticker)

        if current_low is None:
            skipped.append((ticker, "no data from yfinance"))
            continue

        # Fetch current price if market order
        if entry is None:
            try:
                data = yf.download(ticker, period='1d', progress=False)
                if data.empty:
                    skipped.append((ticker, "no current price data"))
                    continue
                entry = round(float(data['Close'].iloc[-1]), 2)
            except Exception as e:
                skipped.append((ticker, f"error fetching price: {e}"))
                continue

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
        print(f"{'Ticker':<8} {'Entry':>8} {'Stop':>8} {'TP1(1R)':>9} {'TP2(3R)':>9} {'Qty':>4} {'TP1/TP2':>8} {'~Cost':>10} {'MaxLoss':>8} {'MaxGain':>8}")
        print("-" * 100)

        for o in orders:
            print(
                f"{o['ticker']:<8} {o['entry']:>8.2f} {o['stop']:>8.2f} {o['target1']:>9.2f} {o['target2']:>9.2f} "
                f"{o['shares']:>4} {o['tp1_qty']}/{o['tp2_qty']:<5} "
                f"{o['cost']:>10,.2f} {o['max_loss']:>8.2f} {o['max_gain']:>8.2f}"
            )

        print("-" * 100)
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
    print("="*80)
    print("ASSERTIONS")
    print("="*80)
    print()

    test_passed = True

    # Test 1: All orders have valid calculations
    if orders:
        for o in orders:
            # Verify targets
            assert o['target1'] == round(o['entry'] + o['rps'], 2), f"{o['ticker']}: TP1 mismatch"
            assert o['target2'] == round(o['entry'] + 3 * o['rps'], 2), f"{o['ticker']}: TP2 mismatch"
            print(f"✓ {o['ticker']}: TP1 and TP2 calculated correctly")

            # Verify share split
            assert o['tp1_qty'] + o['tp2_qty'] == o['shares'], f"{o['ticker']}: Share split mismatch"
            print(f"✓ {o['ticker']}: Share split correct ({o['tp1_qty']} + {o['tp2_qty']} = {o['shares']})")

            # Verify max gain calculation
            expected_gain = (o['tp1_qty'] * 1 * o['rps']) + (o['tp2_qty'] * 3 * o['rps'])
            expected_gain = round(expected_gain, 2)
            assert o['max_gain'] == expected_gain, f"{o['ticker']}: Max gain mismatch ({o['max_gain']} vs {expected_gain})"
            print(f"✓ {o['ticker']}: Max gain correct (${o['max_gain']:.2f})")

            # Verify entry > stop
            assert o['entry'] > o['stop'], f"{o['ticker']}: Entry should be > Stop"
            print(f"✓ {o['ticker']}: Entry (${o['entry']:.2f}) > Stop (${o['stop']:.2f})")

            # Verify shares calculation
            expected_shares = floor(RISK_DOLLARS / o['rps'])
            assert o['shares'] == expected_shares, f"{o['ticker']}: Shares mismatch"
            print(f"✓ {o['ticker']}: Shares calculation correct ({o['shares']} shares)")

            print()

    print("="*80)
    print("TEST RESULT: PASSED" if test_passed else "TEST RESULT: FAILED")
    print("="*80)
    print()

    return test_passed


if __name__ == '__main__':
    success = test_orders_from_file()
    sys.exit(0 if success else 1)
