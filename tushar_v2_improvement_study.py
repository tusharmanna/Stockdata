"""Tushar v2 improvement study — four candidate upgrades, one honest protocol.

Goal: better OUT-OF-SAMPLE risk-adjusted returns than current v2 (target_vol=0.45,
20d rolling vol, cap 1.5). Raising target_vol is out of scope — the walk-forward
already showed it buys return at the same Sharpe.

Experiments (each fitted on 2010-2018, judged on 2019-2026, after-cost, causal):
  1. Vol estimator: EWMA / downside semi-vol / 10d+60d blend vs 20d rolling std.
  2. CASH-regime defensive assets: TLT / GLD / 50-50 instead of T-bills.
  3. Graded regime: linear ramp from X% to Y% below the 189d high vs binary 15% cliff.
  4. VIX crash filter: cut exposure on VIX term-structure inversion / level spikes.

Adoption bar: OOS Sharpe > current v2 OOS Sharpe AND OOS max DD no more than 2pp
deeper. Individual winners are then combined and re-validated (step 5) — upgrades
that work alone can cancel out together.

Reuses v1 regime logic from tusharStrategyDev.py.
"""

import numpy as np
import pandas as pd

from tusharStrategyDev import (_load, compute_signal_v1, QQQ_TICKER, TQQQ_TICKER,
                               HIGH_PERIOD)

TRADING_DAYS = 252
LEV_CAP = 1.5
BASE_TARGET = 0.45
VOL_WINDOW = 20
IS_END = pd.Timestamp("2018-12-31")
TARGET_GRID = np.round(np.arange(0.20, 0.91, 0.05), 2)

RATE_SPLIT_YEARS = 12
TBILL_EARLY, TBILL_LATE = 0.015, 0.05
MARGIN_EARLY, MARGIN_LATE = 0.025, 0.06

DD_TOLERANCE = 0.02   # OOS max DD may be at most 2pp deeper than baseline v2


# -- shared plumbing -----------------------------------------------------------

def rate_arrays(dates):
    years = (dates - dates.iloc[0]).dt.days.values / 365.25
    tbill = np.where(years > RATE_SPLIT_YEARS, TBILL_LATE, TBILL_EARLY)
    margin = np.where(years > RATE_SPLIT_YEARS, MARGIN_LATE, MARGIN_EARLY)
    return tbill, margin


def strat_returns(expo, tqqq_ret, dates, idle_override=None):
    """After-cost causal returns. idle_override: Series of daily returns earned by
    idle cash instead of T-bills, applied only where it is not NaN."""
    e = expo.shift(1).fillna(0.0)
    tbill, margin = rate_arrays(dates)
    borrowed = (e - 1.0).clip(lower=0)
    idle = (1.0 - e).clip(lower=0, upper=1)
    idle_ret = pd.Series(tbill / TRADING_DAYS, index=e.index)
    if idle_override is not None:
        ov = idle_override.shift(0)  # already causal via holdings known at t-1 close
        idle_ret = idle_ret.where(ov.isna(), ov)
    return e * tqqq_ret - borrowed * margin / TRADING_DAYS + idle * idle_ret


def stats(ret, tbill_daily):
    """Sharpe on EXCESS returns (over T-bill) so cash carry can't masquerade as edge."""
    eq = (1.0 + ret).cumprod()
    n_yr = len(ret) / TRADING_DAYS
    ex = ret - tbill_daily
    return {
        "cagr": eq.iloc[-1] ** (1 / n_yr) - 1 if n_yr > 0 else np.nan,
        "sharpe": ex.mean() / ex.std() * np.sqrt(TRADING_DAYS) if ex.std() > 0 else np.nan,
        "max_dd": (eq / eq.cummax() - 1.0).min(),
    }


def is_oos(ret, idx, tbill_daily):
    is_m, oos_m = idx <= IS_END, idx > IS_END
    return (stats(ret[is_m], tbill_daily[is_m]),
            stats(ret[oos_m], tbill_daily[oos_m]))


def passes(oos, base_oos):
    return (oos["sharpe"] > base_oos["sharpe"]
            and oos["max_dd"] >= base_oos["max_dd"] - DD_TOLERANCE)


def row(name, s_is, s_oos, mark=""):
    print(f"{name:<28}{s_is['sharpe']:>7.2f}{s_is['cagr']:>9.1%}{s_is['max_dd']:>9.1%}"
          f"{s_oos['sharpe']:>10.2f}{s_oos['cagr']:>9.1%}{s_oos['max_dd']:>9.1%}  {mark}")


def header(title):
    print("\n" + "=" * 92)
    print(title)
    print("=" * 92)
    print(f"{'variant':<28}{'IS Shp':>7}{'IS CAGR':>9}{'IS DD':>9}"
          f"{'OOS Shp':>10}{'OOS CAGR':>9}{'OOS DD':>9}")
    print("-" * 92)


# -- vol estimators --------------------------------------------------------------

def vol_roll(ret, window=VOL_WINDOW):
    return (ret.rolling(window).std() * np.sqrt(TRADING_DAYS)).bfill()


def vol_ewma(ret, alpha=0.06):
    return (ret.ewm(alpha=alpha).std() * np.sqrt(TRADING_DAYS)).bfill()


def vol_semi(ret, window=VOL_WINDOW):
    downside = ret.clip(upper=0.0)
    return (downside.pow(2).rolling(window).mean().pow(0.5)
            * np.sqrt(TRADING_DAYS)).bfill()


def vol_blend(ret):
    return (0.5 * (vol_roll(ret, 10) + vol_roll(ret, 60))).bfill()


def best_target_on_is(regime_w, rv, tqqq_ret, dates, idx, tbill_daily):
    """Grid target_vol on IS Sharpe only; return (target, exposure, IS OOS sharpes)."""
    best = None
    oos_sharpes = []
    for tv in TARGET_GRID:
        expo = (regime_w * (tv / rv)).clip(0, LEV_CAP)
        r = strat_returns(expo, tqqq_ret, dates)
        s_is, s_oos = is_oos(r, idx, tbill_daily)
        oos_sharpes.append(s_oos["sharpe"])
        if best is None or s_is["sharpe"] > best[1]["sharpe"]:
            best = (tv, s_is, s_oos, expo)
    spread = max(oos_sharpes) - min(oos_sharpes)
    return best, spread


def main():
    print("Loading QQQ, TQQQ, TLT, GLD, ^VIX, ^VIX3M (live)...")
    qqq_df = _load(QQQ_TICKER)
    tqqq_df = _load(TQQQ_TICKER)
    tlt_df = _load("TLT")
    gld_df = _load("GLD")
    try:
        vix = _load("^VIX")["close"]
        vix3m = _load("^VIX3M")["close"]
    except Exception:
        vix, vix3m = None, None

    sig = compute_signal_v1(qqq_df)
    regime_pos = (sig["regime"] == "BUY_TQQQ").astype(float)
    dist = (sig["pcthi"] / 100.0)          # fraction below 189d high

    idx = qqq_df.index.intersection(tqqq_df.index)
    regime_pos = regime_pos.loc[idx]
    dist = dist.loc[idx]
    tqqq_ret = tqqq_df.loc[idx, "close"].pct_change().fillna(0.0)
    dates = pd.Series(idx, index=idx)

    tlt_ret = tlt_df["close"].pct_change().reindex(idx).fillna(0.0)
    gld_ret = gld_df["close"].pct_change().reindex(idx).fillna(0.0)

    tbill_arr, _ = rate_arrays(dates)
    tbill_daily = pd.Series(tbill_arr / TRADING_DAYS, index=idx)

    rv20 = vol_roll(tqqq_ret)
    base_expo = (regime_pos * (BASE_TARGET / rv20)).clip(0, LEV_CAP)
    base_ret = strat_returns(base_expo, tqqq_ret, dates)
    base_is, base_oos = is_oos(base_ret, idx, tbill_daily)

    v1_ret = strat_returns(regime_pos, tqqq_ret, dates)
    v1_is, v1_oos = is_oos(v1_ret, idx, tbill_daily)

    print(f"\nRange: {idx[0].date()} .. {idx[-1].date()}   "
          f"IS: ..{IS_END.date()}   OOS: 2019-01-01..")
    print(f"Adoption bar: OOS Sharpe > {base_oos['sharpe']:.2f} (current v2) "
          f"and OOS DD >= {base_oos['max_dd'] - DD_TOLERANCE:.1%}")

    header("BASELINES")
    row("v1 (regime only)", v1_is, v1_oos)
    row("v2 current (roll20, 0.45)", base_is, base_oos, "<- bar")

    winners = {}

    # ---- Experiment 1: vol estimators ------------------------------------------
    header("EXPERIMENT 1: VOL ESTIMATOR (target gridded on IS per estimator)")
    estimators = {
        "roll20 (baseline)": rv20,
        "ewma (a=0.06)": vol_ewma(tqqq_ret),
        "semi-vol 20d": vol_semi(tqqq_ret),
        "blend 10d/60d": vol_blend(tqqq_ret),
    }
    for name, rv in estimators.items():
        (tv, s_is, s_oos, expo), spread = best_target_on_is(
            regime_pos, rv, tqqq_ret, dates, idx, tbill_daily)
        ok = passes(s_oos, base_oos) and "baseline" not in name
        mark = f"tv={tv:.2f} oos-spread={spread:.2f}" + ("  PASS" if ok else "")
        row(name, s_is, s_oos, mark)
        if ok:
            winners.setdefault("estimator", []).append((name, s_oos["sharpe"], rv, tv))

    # ---- Experiment 2: CASH-regime defensive assets -----------------------------
    header("EXPERIMENT 2: CASH-REGIME DEFENSIVE ASSET (instead of T-bills)")
    prev_cash = (regime_pos.shift(1).fillna(0.0) == 0.0)
    defensives = {
        "TLT": tlt_ret,
        "GLD": gld_ret,
        "50/50 TLT+GLD": 0.5 * (tlt_ret + gld_ret),
    }
    for name, dref in defensives.items():
        override = dref.where(prev_cash)           # NaN on bull days -> tbill
        r = strat_returns(base_expo, tqqq_ret, dates, idle_override=override)
        s_is, s_oos = is_oos(r, idx, tbill_daily)
        ok = passes(s_oos, base_oos)
        row(f"cash -> {name}", s_is, s_oos, "PASS" if ok else "")
        if ok:
            winners.setdefault("defensive", []).append((name, s_oos["sharpe"], dref))

    # ---- Experiment 3: graded regime ramp ---------------------------------------
    header("EXPERIMENT 3: GRADED REGIME (w=1 within X%, w=0 at Y%; X/Y fit on IS)")
    best_g = None
    for x in (0.05, 0.08, 0.10, 0.12):
        for y in (0.15, 0.18, 0.20, 0.25):
            w = ((y - dist) / (y - x)).clip(0.0, 1.0)
            expo = (w * (BASE_TARGET / rv20)).clip(0, LEV_CAP)
            r = strat_returns(expo, tqqq_ret, dates)
            s_is, s_oos = is_oos(r, idx, tbill_daily)
            if best_g is None or s_is["sharpe"] > best_g[2]["sharpe"]:
                best_g = (x, y, s_is, s_oos, expo)
    x, y, s_is, s_oos, graded_expo = best_g
    ok = passes(s_oos, base_oos)
    row(f"ramp X={x:.0%} Y={y:.0%} (IS best)", s_is, s_oos, "PASS" if ok else "")
    if ok:
        winners["graded"] = (x, y, s_oos["sharpe"])

    # ---- Experiment 4: VIX crash filter ------------------------------------------
    vix_scale_best = None
    if vix is not None and vix3m is not None and len(vix3m) > 0:
        header("EXPERIMENT 4: VIX CRASH FILTER (scale applied on top of current v2)")
        vix_a = vix.reindex(idx).ffill()
        vix3m_a = vix3m.reindex(idx).ffill()
        inverted = (vix_a > vix3m_a)
        variants = {
            "inverted -> 0.0": inverted.map({True: 0.0, False: 1.0}),
            "inverted -> 0.5": inverted.map({True: 0.5, False: 1.0}),
            "VIX>30 -> 0.0": (vix_a > 30).map({True: 0.0, False: 1.0}),
            "VIX>30 -> 0.5": (vix_a > 30).map({True: 0.5, False: 1.0}),
            "VIX>25 -> 0.5": (vix_a > 25).map({True: 0.5, False: 1.0}),
            "inv & VIX>25 -> 0": (inverted & (vix_a > 25)).map({True: 0.0, False: 1.0}),
        }
        for name, scale in variants.items():
            expo = (base_expo * scale).clip(0, LEV_CAP)
            r = strat_returns(expo, tqqq_ret, dates)
            s_is, s_oos = is_oos(r, idx, tbill_daily)
            ok = passes(s_oos, base_oos)
            row(name, s_is, s_oos, "PASS" if ok else "")
            if ok and (vix_scale_best is None or s_is["sharpe"] > vix_scale_best[2]["sharpe"]):
                vix_scale_best = (name, scale, s_is, s_oos)
        if vix_scale_best:
            winners["vix"] = vix_scale_best[:2] + (vix_scale_best[3]["sharpe"],)
    else:
        print("\nEXPERIMENT 4 SKIPPED: ^VIX / ^VIX3M data unavailable from yfinance.")

    # ---- Step 5: combine individual winners --------------------------------------
    header("STEP 5: COMBINATION OF INDIVIDUAL WINNERS")
    if not winners:
        print("No candidate cleared the adoption bar. Current v2 stands.")
    else:
        rv_c, tv_c = rv20, BASE_TARGET
        parts = []
        if "estimator" in winners:
            name, _, rv_c, tv_c = max(winners["estimator"], key=lambda t: t[1])
            parts.append(f"estimator={name} (tv={tv_c:.2f})")
        if "graded" in winners:
            gx, gy, _ = winners["graded"]
            w = ((gy - dist) / (gy - gx)).clip(0.0, 1.0)
            parts.append(f"graded X={gx:.0%} Y={gy:.0%}")
        else:
            w = regime_pos
        expo = (w * (tv_c / rv_c)).clip(0, LEV_CAP)
        if "vix" in winners:
            vname, scale, _ = winners["vix"]
            expo = (expo * scale).clip(0, LEV_CAP)
            parts.append(f"vix={vname}")
        override = None
        if "defensive" in winners:
            dname, _, dref = max(winners["defensive"], key=lambda t: t[1])
            override = dref.where(prev_cash)
            parts.append(f"cash->{dname}")
        r = strat_returns(expo, tqqq_ret, dates, idle_override=override)
        s_is, s_oos = is_oos(r, idx, tbill_daily)
        print("Combining: " + "; ".join(parts))
        print("-" * 92)
        row("COMBINED", s_is, s_oos, "PASS" if passes(s_oos, base_oos) else "FAIL")
        row("v2 current (bar)", base_is, base_oos)

    print("\n" + "=" * 92)
    print("VERDICT")
    print("=" * 92)
    if winners:
        labels = {
            "estimator": lambda v: ", ".join(f"{t[0]} (tv={t[3]:.2f})" for t in v),
            "defensive": lambda v: ", ".join(t[0] for t in v),
            "graded": lambda v: f"X={v[0]:.0%} Y={v[1]:.0%}",
            "vix": lambda v: v[0],
        }
        for k, v in winners.items():
            print(f"- {k}: {labels[k](v)}")
        print("Adopt only what survives the COMBINED row; changes go to "
              "tushar_v2_signal.py after review.")
    else:
        print("- Nothing beat current v2 out of sample. The honest conclusion stands:")
        print("  vol-targeting + regime gate is already at this system's risk-adjusted")
        print("  frontier; more return requires accepting more drawdown (raise TARGET_VOL).")


if __name__ == "__main__":
    main()
