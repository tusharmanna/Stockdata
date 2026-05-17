"""
EnterOrdersIB.py — Place Limit + Stop Loss bracket orders on Interactive Brokers.

Reads tickers and prices from orders.txt (format: TICKER PRICE, one per line, # for comments).
Fetches yesterday's low from the database (stockdata.db).
No real-time data subscription required.

  Entry  : Limit order at specified price from orders.txt
  Stop   : Yesterday's low (from database)
  Target : Entry + 2 × risk/share (limit order, 1:2 reward/risk)
  Shares : floor($50 / (entry - yesterday_low))

Displays a full order summary and asks for per-order confirmation before sending.

Usage:
  python EnterOrdersIB.py                  # paper trading, TWS port 7497
  python EnterOrdersIB.py --live           # live trading,  TWS port 7496
  python EnterOrdersIB.py --port 4002      # override port (e.g. IB Gateway paper)
  python EnterOrdersIB.py --host 192.168.1.5  # remote TWS host
  python EnterOrdersIB.py --client-id 2   # override IB client ID (default 1)
  python EnterOrdersIB.py --all           # send all qualifying orders without confirmation

Requires: ibapi  (pip install ibapi)
TWS/Gateway must be running with API connections enabled.
"""

import argparse
import sys
import time
import threading
import sqlite3
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

def get_yesterday_low(ticker: str, db_path: str = "stockdata.db") -> float | None:
    """Fetch yesterday's low from the database (most recent row)."""
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.execute(
            "SELECT low FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1",
            (ticker,)
        )
        row = cur.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        print(f"  Error fetching low for {ticker}: {e}")
        return None


def read_ticker_prices(path: Path) -> list:
    """Read tickers and prices from orders.txt (format: TICKER PRICE)."""
    orders = []
    with open(path) as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                try:
                    ticker = parts[0].upper()
                    price = float(parts[1])
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


def make_bracket(parent_id: int, stop_id: int, tp_id: int,
                 qty: int, entry: float, stop: float, take_profit: float):
    """Return (parent, stop_order, tp_order) for a Limit + Stop + Take-Profit bracket.

    Stop and TP are linked via an OCA group so whichever fills first cancels the other.
    """
    oca_group = f"OCA_{parent_id}"

    parent = Order()
    parent.orderId        = parent_id
    parent.action         = "BUY"
    parent.orderType      = "LMT"
    parent.lmtPrice       = round(entry, 2)
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

    tp_order = Order()
    tp_order.orderId        = tp_id
    tp_order.parentId       = parent_id
    tp_order.action         = "SELL"
    tp_order.orderType      = "LMT"
    tp_order.lmtPrice       = round(take_profit, 2)
    tp_order.totalQuantity  = qty
    tp_order.ocaGroup       = oca_group
    tp_order.ocaType        = 1   # cancel remaining orders on fill
    tp_order.transmit       = True  # transmit all three at once
    tp_order.eTradeOnly     = False
    tp_order.firmQuoteOnly  = False

    return parent, stop_order, tp_order


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
    return ap.parse_args()


def main():
    args = parse_args()
    mode = "LIVE" if args.live else "PAPER"
    port = args.port if args.port else (LIVE_TWS_PORT if args.live else PAPER_TWS_PORT)

    print(f"=== EnterOrdersIB ===  mode={mode}  host={args.host}:{port}  clientId={args.client_id}\n")

    # ------------------------------------------------------------------
    # 1. Read tickers and prices from orders.txt
    # ------------------------------------------------------------------
    if not ORDERS_FILE.exists():
        print(f"ERROR: {ORDERS_FILE} not found.\n"
              "Create orders.txt with format: TICKER PRICE (one per line, # = comment).")
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
    # 3. Fetch yesterday's low from database for each ticker
    # ------------------------------------------------------------------
    print(f"Fetching yesterday's lows from database for {len(tickers)} ticker(s)...")

    db_path = Path(__file__).parent / "stockdata.db"
    yesterday_lows = {}
    for ticker_data in tickers:
        ticker = ticker_data["ticker"]
        low = get_yesterday_low(ticker, str(db_path))
        yesterday_lows[ticker] = low

    print(f"  Done.\n")

    # ------------------------------------------------------------------
    # 4. Build order list
    #    Entry : Limit order at price from orders.txt
    #    Stop  : Yesterday's low from database
    #    Shares: floor($50 / (entry - yesterday_low))
    # ------------------------------------------------------------------
    orders  = []
    skipped = []

    for ticker_data in tickers:
        ticker = ticker_data["ticker"]
        entry = ticker_data["price"]
        yesterday_low = yesterday_lows.get(ticker)

        if yesterday_low is None:
            skipped.append((ticker, "no data in database"))
            continue

        rps = round(entry - yesterday_low, 4)
        if rps <= 0:
            skipped.append((ticker, f"entry {entry:.2f} <= yesterday_low {yesterday_low:.2f}"))
            continue

        shares = calc_shares(entry, yesterday_low)
        if shares == 0:
            skipped.append((ticker, f"risk/share ${rps:.2f} > ${RISK_DOLLARS:.0f} budget"))
            continue

        target = round(entry + 2 * rps, 2)
        orders.append({
            "ticker":    ticker,
            "entry":     entry,
            "stop":      yesterday_low,
            "target":    target,
            "rps":       rps,
            "shares":    shares,
            "cost":      round(shares * entry, 2),
            "max_loss":  round(shares * rps, 2),
            "max_gain":  round(shares * 2 * rps, 2),
        })

    # ------------------------------------------------------------------
    # 5. Print full order summary
    # ------------------------------------------------------------------
    SEP = "=" * 88
    print(SEP)
    print("ORDER SUMMARY  (Limit entry + Stop at yesterday's low + TP at 2R, Risk = $50)")
    print(SEP)

    if orders:
        hdr = (f"{'Ticker':<8}  {'Entry':>8}  {'Stop':>8}  {'Target(2R)':>10}  "
               f"{'Rk/Sh':>6}  {'Shares':>6}  {'~Cost':>10}  {'MaxLoss':>8}  {'MaxGain':>8}")
        print(hdr)
        print("-" * len(hdr))
        for o in orders:
            print(
                f"{o['ticker']:<8}  {o['entry']:>8.2f}  {o['stop']:>8.2f}  {o['target']:>10.2f}  "
                f"{o['rps']:>6.2f}  {o['shares']:>6}  "
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
            tp_id     = app.next_order_id()
            parent, stop_order, tp_order = make_bracket(
                parent_id, stop_id, tp_id,
                qty=o["shares"], entry=o["entry"], stop=o["stop"], take_profit=o["target"]
            )
            app.placeOrder(parent_id, contract, parent)
            app.placeOrder(stop_id,   contract, stop_order)
            app.placeOrder(tp_id,     contract, tp_order)
            print(f"  Submitted {o['ticker']:<6}  "
                  f"BUY {o['shares']} @ LMT {o['entry']:.2f}  Stop: {o['stop']:.2f}  "
                  f"Target: {o['target']:.2f}  "
                  f"(orderId={parent_id}/{stop_id}/{tp_id})")
            placed += 1
            time.sleep(0.1)
    else:
        print(f"Stepping through {len(orders)} order(s). [y]=send  [n]=skip  [q]=quit\n")
        for i, o in enumerate(orders, 1):
            print(f"  [{i}/{len(orders)}]  {o['ticker']:<6}  "
                  f"BUY {o['shares']} @ LMT {o['entry']:.2f}  |  Stop: {o['stop']:.2f}  |  "
                  f"Target: {o['target']:.2f}  |  "
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
            tp_id     = app.next_order_id()
            parent, stop_order, tp_order = make_bracket(
                parent_id, stop_id, tp_id,
                qty=o["shares"], entry=o["entry"], stop=o["stop"], take_profit=o["target"]
            )
            app.placeOrder(parent_id, contract, parent)
            app.placeOrder(stop_id,   contract, stop_order)
            app.placeOrder(tp_id,     contract, tp_order)
            print(f"  Submitted (orderId={parent_id} entry / {stop_id} stop / {tp_id} target)\n")
            placed += 1
            time.sleep(0.1)

    time.sleep(2)
    app.disconnect()

    print(f"\nDone. {placed} submitted, {skipped_at_confirm} skipped at confirm.")


if __name__ == "__main__":
    main()
