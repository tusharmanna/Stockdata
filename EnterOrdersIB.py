"""
EnterOrdersIB.py — Place Market + Stop Loss bracket orders on Interactive Brokers.

Reads tickers from orders.txt (one per line, # for comments).
Fetches delayed price (~15 min) and today's low from IB market data (type 3).
No real-time data subscription required.

  Entry  : Market order (fills at current market price)
  Stop   : Today's low (from IB delayed data)
  Target : Entry + 2 × risk/share (limit order, 1:2 reward/risk)
  Shares : floor($50 / (last_price - today_low))

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

def read_tickers(path: Path) -> list:
    tickers = []
    with open(path) as fh:
        for raw in fh:
            t = raw.strip().upper()
            if t and not t.startswith("#"):
                tickers.append(t)
    return tickers


def calc_shares(live: float, today_low: float, risk: float = RISK_DOLLARS) -> int:
    rps = live - today_low
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
                 qty: int, stop: float, take_profit: float):
    """Return (parent, stop_order, tp_order) for a Market + Stop + Take-Profit bracket.

    Stop and TP are linked via an OCA group so whichever fills first cancels the other.
    """
    oca_group = f"OCA_{parent_id}"

    parent = Order()
    parent.orderId        = parent_id
    parent.action         = "BUY"
    parent.orderType      = "MKT"
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
    # 1. Read tickers from orders.txt
    # ------------------------------------------------------------------
    if not ORDERS_FILE.exists():
        print(f"ERROR: {ORDERS_FILE} not found.\n"
              "Create orders.txt with one ticker per line (# = comment).")
        sys.exit(1)

    tickers = read_tickers(ORDERS_FILE)
    if not tickers:
        print("orders.txt is empty — nothing to do.")
        sys.exit(0)

    print(f"Tickers from orders.txt: {', '.join(tickers)}\n")

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

    # Use delayed market data (type 3) — no real-time subscription required.
    # Delayed data is ~15 min behind but includes today's live high/low/last.
    app.reqMarketDataType(3)
    time.sleep(0.5)  # give IB a moment to acknowledge the data type switch

    # ------------------------------------------------------------------
    # 3. Fetch delayed price and today's low from IB market data snapshots
    # ------------------------------------------------------------------
    print(f"Requesting delayed market data snapshots for {len(tickers)} ticker(s)...")

    req_base = 1000
    req_ids  = {ticker: req_base + i for i, ticker in enumerate(tickers)}

    for ticker, req_id in req_ids.items():
        app.request_snapshot(req_id, ticker)
        time.sleep(0.05)

    snapshots = {}
    for ticker, req_id in req_ids.items():
        snapshots[ticker] = app.get_snapshot_prices(req_id)

    print(f"  Done.\n")

    # ------------------------------------------------------------------
    # 4. Build order list
    #    Entry : Market order
    #    Stop  : Today's low from IB
    #    Shares: floor($50 / (live - today_low))
    # ------------------------------------------------------------------
    orders  = []
    skipped = []

    for ticker in tickers:
        snap = snapshots.get(ticker, {})
        live      = snap.get("last")
        today_low = snap.get("low")

        if not live:
            skipped.append((ticker, "no live price from IB"))
            continue
        if not today_low:
            skipped.append((ticker, "no today's low from IB"))
            continue

        rps = round(live - today_low, 4)
        if rps <= 0:
            skipped.append((ticker, f"live {live:.2f} <= today_low {today_low:.2f}"))
            continue

        shares = calc_shares(live, today_low)
        if shares == 0:
            skipped.append((ticker, f"risk/share ${rps:.2f} > ${RISK_DOLLARS:.0f} budget"))
            continue

        target = round(live + 2 * rps, 2)
        orders.append({
            "ticker":    ticker,
            "live":      live,
            "stop":      today_low,
            "target":    target,
            "rps":       rps,
            "shares":    shares,
            "cost":      round(shares * live, 2),
            "max_loss":  round(shares * rps, 2),
            "max_gain":  round(shares * 2 * rps, 2),
        })

    # ------------------------------------------------------------------
    # 5. Print full order summary
    # ------------------------------------------------------------------
    SEP = "=" * 88
    print(SEP)
    print("ORDER SUMMARY  (Market entry + Stop at today's low + TP at 2R, Risk = $50)")
    print(SEP)

    if orders:
        hdr = (f"{'Ticker':<8}  {'Live':>8}  {'Stop':>8}  {'Target(2R)':>10}  "
               f"{'Rk/Sh':>6}  {'Shares':>6}  {'~Cost':>10}  {'MaxLoss':>8}  {'MaxGain':>8}")
        print(hdr)
        print("-" * len(hdr))
        for o in orders:
            print(
                f"{o['ticker']:<8}  {o['live']:>8.2f}  {o['stop']:>8.2f}  {o['target']:>10.2f}  "
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
                qty=o["shares"], stop=o["stop"], take_profit=o["target"]
            )
            app.placeOrder(parent_id, contract, parent)
            app.placeOrder(stop_id,   contract, stop_order)
            app.placeOrder(tp_id,     contract, tp_order)
            print(f"  Submitted {o['ticker']:<6}  "
                  f"BUY {o['shares']} @ MKT  Stop: {o['stop']:.2f}  "
                  f"Target: {o['target']:.2f}  "
                  f"(orderId={parent_id}/{stop_id}/{tp_id})")
            placed += 1
            time.sleep(0.1)
    else:
        print(f"Stepping through {len(orders)} order(s). [y]=send  [n]=skip  [q]=quit\n")
        for i, o in enumerate(orders, 1):
            print(f"  [{i}/{len(orders)}]  {o['ticker']:<6}  "
                  f"BUY {o['shares']} @ MKT  |  Stop: {o['stop']:.2f}  |  "
                  f"Target: {o['target']:.2f}  |  "
                  f"Live: {o['live']:.2f}  |  Risk/share: ${o['rps']:.2f}  |  "
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
                qty=o["shares"], stop=o["stop"], take_profit=o["target"]
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
