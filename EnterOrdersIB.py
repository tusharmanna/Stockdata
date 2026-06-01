"""
EnterOrdersIB.py — Place Market/Limit + Stop Loss bracket orders on Interactive Brokers.

Reads tickers and optional prices from orders.txt (format: TICKER or TICKER PRICE).
Fetches current low from yfinance (live market data).

  Entry    : Market order (default) OR Limit if --limit flag + price specified
  Stop     : Current low (from yfinance)
  TP1      : Entry + 1R (sell 1/3, 1:1 reward/risk)
  TP2      : Entry + 3R (sell 2/3, 1:3 reward/risk)
  Shares   : floor($50 / (entry - current_low))

Displays a full order summary and asks for per-order confirmation before sending.

Usage:
  python EnterOrdersIB.py                  # paper trading, market orders, TWS port 7497
  python EnterOrdersIB.py --live           # live trading, market orders, TWS port 7496
  python EnterOrdersIB.py --limit          # use limit orders (requires TICKER PRICE)
  python EnterOrdersIB.py --port 4002      # override port (e.g. IB Gateway paper)
  python EnterOrdersIB.py --host 192.168.1.5  # remote TWS host
  python EnterOrdersIB.py --client-id 2   # override IB client ID (default 1)
  python EnterOrdersIB.py --all           # send all qualifying orders without confirmation

Requires: ibapi, yfinance  (pip install ibapi yfinance)
TWS/Gateway must be running with API connections enabled.
"""

import argparse
import sys
import time
import threading
from math import floor
from pathlib import Path

try:
    from ibapi.client import EClient
    from ibapi.wrapper import EWrapper
    from ibapi.contract import Contract
    from ibapi.order import Order
except ImportError:
    print("ERROR: ibapi not installed.  Run: pip install ibapi")
    sys.exit(1)

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance not installed.  Run: pip install yfinance")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ORDERS_FILE  = Path(__file__).parent / "orders.txt"
RISK_DOLLARS = 50.0

PAPER_TWS_PORT   = 7497
LIVE_TWS_PORT    = 7496
SNAPSHOT_TIMEOUT = 20   # seconds to wait for each snapshot (delayed data needs more time)

# IB tick types — delayed (type 3) sends 68/72/73; real-time sends 4/6/7
# We accept both so the code works whether or not a real-time subscription exists.
TICK_LAST         = 4   # real-time last
TICK_HIGH         = 6   # real-time day high
TICK_LOW          = 7   # real-time day low
TICK_DELAYED_LAST = 68  # delayed last  (~15 min)
TICK_DELAYED_HIGH = 72  # delayed day high
TICK_DELAYED_LOW  = 73  # delayed day low

# IB info-only error codes (not real errors)
_IB_INFO_CODES = {2104, 2106, 2107, 2108, 2119, 2158, 10167, 10197}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_current_low(ticker: str) -> float | None:
    """Fetch current low from yfinance (live market data)."""
    try:
        data = yf.download(ticker, period='1d', progress=False)
        if data.empty:
            return None
        low_value = data['Low'].iloc[-1]
        low = float(low_value) if isinstance(low_value, (int, float)) else float(low_value.item())
        return low if low > 0 else None
    except Exception as e:
        print(f"  Error fetching low for {ticker}: {e}")
        return None


def read_ticker_prices(path: Path) -> list:
    """Read tickers and optional prices from orders.txt (format: TICKER or TICKER PRICE).

    For market orders, price can be omitted. For limit orders, price is required.
    """
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


def calc_shares(entry: float, stop: float, risk: float = RISK_DOLLARS) -> int:
    rps = entry - stop
    if rps <= 0:
        return 0
    return floor(risk / rps)


# ---------------------------------------------------------------------------
# IB Application
# ---------------------------------------------------------------------------

class IBApp(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)
        self._next_order_id: int | None = None
        self._connected     = threading.Event()

        # Market data state
        # _md[reqId] = {"high": float|None, "low": float|None, "last": float|None}
        self._md:      dict[int, dict]            = {}
        self._md_done: dict[int, threading.Event] = {}
        self._req_ticker: dict[int, str]          = {}
        self._lock = threading.Lock()

    def nextValidId(self, orderId: int):
        self._next_order_id = orderId
        self._connected.set()

    def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):
        if errorCode in _IB_INFO_CODES:
            return
        ticker = self._req_ticker.get(reqId, f"reqId={reqId}")
        print(f"  [IB] {ticker}  code={errorCode}: {errorString}")
        with self._lock:
            if reqId in self._md_done:
                self._md_done[reqId].set()

    def tickPrice(self, reqId, tickType, price, attrib):
        with self._lock:
            if reqId not in self._md or price <= 0:
                return
            if tickType in (TICK_HIGH, TICK_DELAYED_HIGH):
                self._md[reqId]["high"] = price
            elif tickType in (TICK_LOW, TICK_DELAYED_LOW):
                self._md[reqId]["low"] = price
            elif tickType in (TICK_LAST, TICK_DELAYED_LAST):
                self._md[reqId]["last"] = price

    def tickSnapshotEnd(self, reqId: int):
        with self._lock:
            if reqId in self._md_done:
                self._md_done[reqId].set()

    def orderStatus(self, orderId, status, filled, remaining, avgFillPrice,
                    permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice):
        print(f"  [IB] orderId={orderId}  status={status}  filled={filled}")

    def next_order_id(self) -> int:
        oid = self._next_order_id
        self._next_order_id += 1
        return oid

    def request_snapshot(self, req_id: int, ticker: str):
        contract = make_contract(ticker)
        with self._lock:
            self._md[req_id]         = {"high": None, "low": None, "last": None}
            self._md_done[req_id]    = threading.Event()
            self._req_ticker[req_id] = ticker
        self.reqMktData(req_id, contract, "", True, False, [])

    def get_snapshot_prices(self, req_id: int, timeout: float = SNAPSHOT_TIMEOUT) -> dict:
        self._md_done[req_id].wait(timeout=timeout)
        with self._lock:
            return dict(self._md.get(req_id, {}))


# ---------------------------------------------------------------------------
# Contract / order factories
# ---------------------------------------------------------------------------

def make_contract(symbol: str) -> Contract:
    c = Contract()
    c.symbol   = symbol
    c.secType  = "STK"
    c.exchange = "SMART"
    c.currency = "USD"
    return c


def make_bracket(parent_id: int, stop_id: int, tp1_id: int, tp2_id: int,
                 qty: int, tp1_qty: int, tp2_qty: int, entry: float | None, stop: float,
                 target1: float, target2: float, use_market: bool = True):
    """Return (parent, stop_order, tp1_order, tp2_order) for a Market/Limit + Stop + 2xTP bracket.

    If use_market=True, entry is a market order (entry price ignored).
    If use_market=False, entry is a limit order at specified price.
    TP1: sell tp1_qty at target1 (1:1 reward/risk)
    TP2: sell tp2_qty at target2 (1:3 reward/risk)
    Stop, TP1, and TP2 are linked via OCA group.
    """
    oca_group = f"OCA_{parent_id}"

    parent = Order()
    parent.orderId        = parent_id
    parent.action         = "BUY"
    parent.orderType      = "MKT" if use_market else "LMT"
    if not use_market and entry is not None:
        parent.lmtPrice   = round(entry, 2)
    parent.totalQuantity  = qty
    parent.transmit       = False
    parent.eTradeOnly     = False
    parent.firmQuoteOnly  = False

    stop_order = Order()
    stop_order.orderId        = stop_id
    stop_order.parentId       = parent_id
    stop_order.action         = "SELL"
    stop_order.orderType      = "STP"
    stop_order.auxPrice       = round(stop, 2)
    stop_order.totalQuantity  = qty
    stop_order.ocaGroup       = oca_group
    stop_order.ocaType        = 1   # cancel remaining orders on fill
    stop_order.transmit       = False
    stop_order.eTradeOnly     = False
    stop_order.firmQuoteOnly  = False

    tp1_order = Order()
    tp1_order.orderId        = tp1_id
    tp1_order.parentId       = parent_id
    tp1_order.action         = "SELL"
    tp1_order.orderType      = "LMT"
    tp1_order.lmtPrice       = round(target1, 2)
    tp1_order.totalQuantity  = tp1_qty
    tp1_order.ocaGroup       = oca_group
    tp1_order.ocaType        = 1   # cancel remaining orders on fill
    tp1_order.transmit       = False
    tp1_order.eTradeOnly     = False
    tp1_order.firmQuoteOnly  = False

    tp2_order = Order()
    tp2_order.orderId        = tp2_id
    tp2_order.parentId       = parent_id
    tp2_order.action         = "SELL"
    tp2_order.orderType      = "LMT"
    tp2_order.lmtPrice       = round(target2, 2)
    tp2_order.totalQuantity  = tp2_qty
    tp2_order.ocaGroup       = oca_group
    tp2_order.ocaType        = 1   # cancel remaining orders on fill
    tp2_order.transmit       = True  # transmit all orders at once
    tp2_order.eTradeOnly     = False
    tp2_order.firmQuoteOnly  = False

    return parent, stop_order, tp1_order, tp2_order


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    ap = argparse.ArgumentParser(description="Place IB bracket orders from orders.txt")
    ap.add_argument("--live",      action="store_true", help="Use live account (default: paper)")
    ap.add_argument("--host",      default="127.0.0.1", help="TWS/Gateway host (default: 127.0.0.1)")
    ap.add_argument("--port",      type=int, default=None, help="Override port")
    ap.add_argument("--client-id", type=int, default=1,   help="IB client ID (default: 1)")
    ap.add_argument("--all",       action="store_true",   help="Send all qualifying orders without per-order confirmation")
    ap.add_argument("--limit",     action="store_true",   help="Use limit orders (requires price in orders.txt, default: market)")
    return ap.parse_args()


def main():
    args = parse_args()
    mode = "LIVE" if args.live else "PAPER"
    port = args.port if args.port else (LIVE_TWS_PORT if args.live else PAPER_TWS_PORT)

    print(f"=== EnterOrdersIB ===  mode={mode}  host={args.host}:{port}  clientId={args.client_id}\n")

    # ------------------------------------------------------------------
    # 1. Read tickers and optional prices from orders.txt
    # ------------------------------------------------------------------
    if not ORDERS_FILE.exists():
        print(f"ERROR: {ORDERS_FILE} not found.\n"
              "Create orders.txt with format: TICKER or TICKER PRICE (one per line, # = comment).\n"
              "  Market orders (default): TICKER only\n"
              "  Limit orders (--limit):  TICKER PRICE (requires price)")
        sys.exit(1)

    tickers = read_ticker_prices(ORDERS_FILE)
    if not tickers:
        print("orders.txt is empty — nothing to do.")
        sys.exit(0)

    ticker_list = [t["ticker"] for t in tickers]
    print(f"Tickers from orders.txt: {', '.join(ticker_list)}\n")

    # ------------------------------------------------------------------
    # 2. Connect to IB
    # ------------------------------------------------------------------
    print(f"Connecting to IB on {args.host}:{port} (clientId={args.client_id}) ...")
    app = IBApp()
    app.connect(args.host, port, args.client_id)

    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()

    if not app._connected.wait(timeout=10):
        print("ERROR: Timed out waiting for IB connection.\n"
              "Check that TWS or IB Gateway is running with API connections enabled.")
        app.disconnect()
        sys.exit(1)

    print(f"Connected. Next order ID: {app._next_order_id}\n")

    # ------------------------------------------------------------------
    # 3. Fetch current low from yfinance for each ticker
    # ------------------------------------------------------------------
    print(f"Fetching current lows from yfinance for {len(tickers)} ticker(s)...")

    current_lows = {}
    for ticker_data in tickers:
        ticker = ticker_data["ticker"]
        low = get_current_low(ticker)
        current_lows[ticker] = low

    print(f"  Done.\n")

    # ------------------------------------------------------------------
    # 4. Build order list
    #    Entry : Market order (default) OR Limit if --limit + price
    #    Stop  : Current low from yfinance
    #    TP1   : Entry + 1R (sell 1/3)
    #    TP2   : Entry + 3R (sell 2/3)
    # ------------------------------------------------------------------
    orders  = []
    skipped = []
    use_market = not args.limit

    for ticker_data in tickers:
        ticker = ticker_data["ticker"]
        entry = ticker_data["price"]
        current_low = current_lows.get(ticker)

        if current_low is None:
            skipped.append((ticker, "no data from yfinance"))
            continue

        # For market orders, entry price is not required
        # For limit orders, entry price is required
        if use_market:
            if entry is None:
                # Fetch current price from yfinance for market orders
                try:
                    import yfinance as yf
                    data = yf.download(ticker, period='1d', progress=False)
                    if data.empty:
                        skipped.append((ticker, "no current price data"))
                        continue
                    close_value = data['Close'].iloc[-1]
                    close_price = float(close_value) if isinstance(close_value, (int, float)) else float(close_value.item())
                    entry = round(close_price, 2)
                except Exception as e:
                    skipped.append((ticker, f"error fetching price: {e}"))
                    continue
        else:
            if entry is None:
                skipped.append((ticker, "no price specified (required for limit orders)"))
                continue

        rps = round(entry - current_low, 4)
        if rps <= 0:
            skipped.append((ticker, f"entry {entry:.2f} <= current_low {current_low:.2f}"))
            continue

        shares = calc_shares(entry, current_low)
        if shares == 0:
            skipped.append((ticker, f"risk/share ${rps:.2f} > ${RISK_DOLLARS:.0f} budget"))
            continue

        target1 = round(entry + 1 * rps, 2)
        target2 = round(entry + 3 * rps, 2)
        tp1_qty = max(1, shares // 3)
        tp2_qty = shares - tp1_qty

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
            "cost":      round(shares * entry, 2),
            "max_loss":  round(shares * rps, 2),
            "max_gain":  round((tp1_qty * 1 * rps) + (tp2_qty * 3 * rps), 2),
            "use_market": use_market,
        })

    # ------------------------------------------------------------------
    # 5. Print full order summary
    # ------------------------------------------------------------------
    SEP = "=" * 100
    print(SEP)
    entry_type = "Market" if use_market else "Limit"
    print(f"ORDER SUMMARY  ({entry_type} entry + Stop at current low + TP1 at 1R (1/3) + TP2 at 3R (2/3), Risk = $50)")
    print(SEP)

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
        print("  No valid orders.")

    if skipped:
        print(f"\nSkipped ({len(skipped)}):")
        for ticker, reason in skipped:
            print(f"  {ticker:<8}  {reason}")

    print()

    if not orders:
        app.disconnect()
        sys.exit(0)

    # ------------------------------------------------------------------
    # 6. Send orders — all at once (--all) or one-by-one with confirmation
    # ------------------------------------------------------------------
    placed             = 0
    skipped_at_confirm = 0

    if args.all:
        print(f"Sending all {len(orders)} order(s) to IB now...\n")
        for o in orders:
            contract  = make_contract(o["ticker"])
            parent_id = app.next_order_id()
            stop_id   = app.next_order_id()
            tp1_id    = app.next_order_id()
            tp2_id    = app.next_order_id()
            parent, stop_order, tp1_order, tp2_order = make_bracket(
                parent_id, stop_id, tp1_id, tp2_id,
                qty=o["shares"], tp1_qty=o["tp1_qty"], tp2_qty=o["tp2_qty"],
                entry=o["entry"], stop=o["stop"], target1=o["target1"], target2=o["target2"],
                use_market=o["use_market"]
            )
            app.placeOrder(parent_id, contract, parent)
            app.placeOrder(stop_id,   contract, stop_order)
            app.placeOrder(tp1_id,    contract, tp1_order)
            app.placeOrder(tp2_id,    contract, tp2_order)
            order_type = "MKT" if o["use_market"] else "LMT"
            print(f"  Submitted {o['ticker']:<6}  "
                  f"BUY {o['shares']} @ {order_type} {o['entry']:.2f}  Stop: {o['stop']:.2f}  "
                  f"TP1: {o['target1']:.2f} ({o['tp1_qty']} sh)  TP2: {o['target2']:.2f} ({o['tp2_qty']} sh)  "
                  f"(orderId={parent_id}/{stop_id}/{tp1_id}/{tp2_id})")
            placed += 1
            time.sleep(0.1)
    else:
        print(f"Stepping through {len(orders)} order(s). [y]=send  [n]=skip  [q]=quit\n")
        for i, o in enumerate(orders, 1):
            order_type = "MKT" if o["use_market"] else "LMT"
            print(f"  [{i}/{len(orders)}]  {o['ticker']:<6}  "
                  f"BUY {o['shares']} @ {order_type} {o['entry']:.2f}  |  Stop: {o['stop']:.2f}  |  "
                  f"TP1: {o['target1']:.2f} ({o['tp1_qty']} sh)  |  TP2: {o['target2']:.2f} ({o['tp2_qty']} sh)  |  "
                  f"Risk/share: ${o['rps']:.2f}  |  "
                  f"Max loss: ${o['max_loss']:.2f}  |  Max gain: ${o['max_gain']:.2f}")

            answer = input("        Send to IB? [y/n/q]: ").strip().lower()

            if answer == "q":
                print("  Quit — no further orders sent.")
                break
            elif answer != "y":
                print("  Skipped.")
                skipped_at_confirm += 1
                continue

            contract  = make_contract(o["ticker"])
            parent_id = app.next_order_id()
            stop_id   = app.next_order_id()
            tp1_id    = app.next_order_id()
            tp2_id    = app.next_order_id()
            parent, stop_order, tp1_order, tp2_order = make_bracket(
                parent_id, stop_id, tp1_id, tp2_id,
                qty=o["shares"], tp1_qty=o["tp1_qty"], tp2_qty=o["tp2_qty"],
                entry=o["entry"], stop=o["stop"], target1=o["target1"], target2=o["target2"],
                use_market=o["use_market"]
            )
            app.placeOrder(parent_id, contract, parent)
            app.placeOrder(stop_id,   contract, stop_order)
            app.placeOrder(tp1_id,    contract, tp1_order)
            app.placeOrder(tp2_id,    contract, tp2_order)
            print(f"  Submitted (orderId={parent_id} entry / {stop_id} stop / {tp1_id} tp1 / {tp2_id} tp2)\n")
            placed += 1
            time.sleep(0.1)

    time.sleep(2)
    app.disconnect()

    print(f"\nDone. {placed} submitted, {skipped_at_confirm} skipped at confirm.")


if __name__ == "__main__":
    main()
