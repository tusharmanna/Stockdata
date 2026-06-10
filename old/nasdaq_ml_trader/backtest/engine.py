import numpy as np
import pandas as pd
import joblib
from sklearn.preprocessing import StandardScaler

from dateutil.relativedelta import relativedelta

from old.nasdaq_ml_trader.config import (
    DEFAULT_CAPITAL, MIN_CONFIDENCE, LSTM_WINDOW, MODEL_DIR, STEP_MONTHS,
)
from old.nasdaq_ml_trader.data.fetcher import get_ohlcv
from old.nasdaq_ml_trader.data.features import build_ml_dataset, build_lstm_sequences, compute_features
from old.nasdaq_ml_trader.models.trainer import generate_folds, train_rf, train_xgb, train_lstm
from old.nasdaq_ml_trader.models.evaluator import evaluate_fold, compute_trading_metrics
from old.nasdaq_ml_trader.models.ensemble import EnsembleModel
from old.nasdaq_ml_trader.sizing.position_sizer import fixed_fractional
from old.nasdaq_ml_trader.utils.logger import get_logger

log = get_logger("engine")

LABEL_MAP = {0: "HOLD", 1: "BUY", 2: "SELL"}


def run_walk_forward(
    ohlcv: pd.DataFrame,
    skip_lstm: bool = False,
    progress_callback=None,
    start_date: pd.Timestamp | None = None,
    initial_capital: float = DEFAULT_CAPITAL,
) -> dict:
    """
    Full walk-forward backtest.
    For each fold: train models → evaluate → simulate P&L → accumulate equity curve.

    start_date: if set, only run folds whose test period ends after this date.
                Training data still uses the full available history up to each fold's
                train_end — no data leakage. This just skips earlier test windows
                to speed up a recent-years-only run.
    """
    X, y       = build_ml_dataset(ohlcv)
    all_folds  = generate_folds(X.index)

    if start_date is not None:
        folds = [f for f in all_folds if f.test_end > start_date]
        log.info(f"Filtered to {len(folds)} folds with test_end > {start_date.date()}")
    else:
        folds = all_folds

    all_daily: list[dict]  = []
    val_results: list[dict] = []
    fold_metrics: list[dict] = []
    capital = float(initial_capital)

    total = len(folds)
    for fold_num, fold in enumerate(folds, 1):
        # ── Slice data ──────────────────────────────────────────────────────
        # Train on full training window (5 years).
        # Test only on the first STEP_MONTHS (6 months) of the test window so
        # adjacent folds don't overlap and each date appears exactly once.
        non_overlap_end = fold.test_start + relativedelta(months=STEP_MONTHS)

        X_tr = X[(X.index >= fold.train_start) & (X.index < fold.train_end)]
        y_tr = y.loc[X_tr.index]
        X_te = X[(X.index >= fold.test_start)  & (X.index < non_overlap_end)]
        y_te = y.loc[X_te.index]

        if len(X_tr) < 252 or len(X_te) < 20:
            log.warning(f"Fold {fold.fold_id}: skipping (train={len(X_tr)}, test={len(X_te)})")
            if progress_callback:
                progress_callback(fold_num, total)
            continue

        # ── Scale ───────────────────────────────────────────────────────────
        scaler  = StandardScaler()
        X_tr_sc = scaler.fit_transform(X_tr)
        X_te_sc = scaler.transform(X_te)

        # ── Train models ────────────────────────────────────────────────────
        rf  = train_rf(X_tr_sc, y_tr.values, fold.fold_id)
        xgb = train_xgb(X_tr_sc, y_tr.values, fold.fold_id)

        lstm_eval: dict | None = None
        if not skip_lstm:
            X_seq_tr, y_seq_tr = build_lstm_sequences(
                pd.DataFrame(X_tr_sc, columns=X.columns, index=X_tr.index), y_tr
            )
            X_seq_te, y_seq_te = build_lstm_sequences(
                pd.DataFrame(X_te_sc, columns=X.columns, index=X_te.index), y_te
            )
            if len(X_seq_tr) > 0 and len(X_seq_te) > 0:
                lstm = train_lstm(X_seq_tr, y_seq_tr, X.shape[1], fold.fold_id)
                lstm_eval = evaluate_fold(lstm, X_seq_te, y_seq_te.astype(np.int64), "lstm")

        # ── Evaluate ────────────────────────────────────────────────────────
        rf_eval  = evaluate_fold(rf,  X_te_sc, y_te.values, "rf")
        xgb_eval = evaluate_fold(xgb, X_te_sc, y_te.values, "xgb")

        # ── Ensemble proba for this test fold ────────────────────────────────
        # LSTM sequences start LSTM_WINDOW rows into the test period, so it
        # produces (N - LSTM_WINDOW) predictions vs N from RF/XGB.
        # Blend LSTM only for the rows where it has predictions; the leading
        # rows use RF+XGB average only.
        ens_proba = (rf_eval["proba"] + xgb_eval["proba"]) / 2
        if lstm_eval is not None:
            offset = len(ens_proba) - len(lstm_eval["proba"])
            ens_proba[offset:] = (ens_proba[offset:] * 2 + lstm_eval["proba"]) / 3

        # ── Simulate trading on test period ──────────────────────────────────
        ohlcv_te     = ohlcv.loc[X_te.index]
        fwd_rets     = ohlcv_te["close"].pct_change().shift(-1).fillna(0).values
        signals      = ens_proba.argmax(axis=1)
        confidences  = ens_proba.max(axis=1)

        for i, date in enumerate(X_te.index):
            sig   = int(signals[i])
            conf  = float(confidences[i])
            eff   = sig if conf >= MIN_CONFIDENCE else 0  # HOLD if below threshold
            fwd   = float(fwd_rets[i])

            size_info   = fixed_fractional(capital, conf)
            alloc_frac  = size_info["allocation"] / capital if capital > 0 else 0.0

            trade_ret = fwd if eff == 1 else (-fwd if eff == 2 else 0.0)
            capital   *= (1 + alloc_frac * trade_ret)

            all_daily.append({
                "date":       date,
                "signal":     LABEL_MAP[eff],
                "confidence": round(conf, 4),
                "close":      round(float(ohlcv_te["close"].iloc[i]), 2),
                "trade_ret":  round(trade_ret, 6),
                "portfolio":  round(capital, 2),
                "fold_id":    fold.fold_id,
            })

        # ── Val results for ensemble weight optimisation ──────────────────────
        # When LSTM is present, trim RF/XGB/rets to the aligned LSTM rows so
        # that all arrays in the dict are the same length (required by optimizer).
        fold_val: dict = {
            "fold_id":    fold.fold_id,
            "test_start": fold.test_start,
            "test_end":   fold.test_end,
        }
        if lstm_eval is not None:
            lstm_offset = len(rf_eval["proba"]) - len(lstm_eval["proba"])
            fold_val["rf_proba"]          = rf_eval["proba"][lstm_offset:]
            fold_val["xgb_proba"]         = xgb_eval["proba"][lstm_offset:]
            fold_val["lstm_proba"]        = lstm_eval["proba"]
            fold_val["actuals"]           = y_te.values[lstm_offset:]
            fold_val["next_day_returns"]  = fwd_rets[lstm_offset:]
        else:
            fold_val["rf_proba"]          = rf_eval["proba"]
            fold_val["xgb_proba"]         = xgb_eval["proba"]
            fold_val["actuals"]           = y_te.values
            fold_val["next_day_returns"]  = fwd_rets
        val_results.append(fold_val)

        fold_metrics.append({
            "fold_id":    fold.fold_id,
            "test_start": fold.test_start.strftime("%Y-%m"),
            "test_end":   fold.test_end.strftime("%Y-%m"),
            "rf_acc":     round(rf_eval["accuracy"],  4),
            "xgb_acc":    round(xgb_eval["accuracy"], 4),
            "lstm_acc":   round(lstm_eval["accuracy"], 4) if lstm_eval else None,
            "n_test":     len(X_te),
        })

        log.info(
            f"Fold {fold.fold_id:3d} [{fold.test_start.date()} – {fold.test_end.date()}]: "
            f"RF={rf_eval['accuracy']:.3f} XGB={xgb_eval['accuracy']:.3f}"
            + (f" LSTM={lstm_eval['accuracy']:.3f}" if lstm_eval else "")
        )

        if progress_callback:
            progress_callback(fold_num, total)

    if not all_daily:
        log.warning("No daily data accumulated -- no folds completed")
        return {"folds": [], "equity_curve": pd.Series(dtype=float),
                "metrics": {}, "fold_metrics": [], "val_results": []}

    equity = pd.Series(
        [d["portfolio"] for d in all_daily],
        index=[d["date"] for d in all_daily],
        name="portfolio",
    ).sort_index()
    # Defensive dedup — should not be needed after non-overlap fix, but guards edge cases
    equity = equity[~equity.index.duplicated(keep="last")]
    daily_rets = equity.pct_change().dropna()
    metrics    = compute_trading_metrics(daily_rets)

    log.info(
        f"Backtest complete: CAGR={metrics['cagr']:.2%} "
        f"Sharpe={metrics['sharpe']:.2f} MaxDD={metrics['max_drawdown']:.2%}"
    )

    return {
        "folds":        all_daily,
        "equity_curve": equity,
        "metrics":      metrics,
        "fold_metrics": fold_metrics,
        "val_results":  val_results,
    }


def benchmark_buyhold(
    ohlcv: pd.DataFrame,
    capital: float = DEFAULT_CAPITAL,
    start_date: pd.Timestamp | None = None,
) -> dict:
    """Buy-and-hold ^IXIC benchmark trimmed to the same window as the strategy."""
    if start_date is not None:
        ohlcv = ohlcv[ohlcv.index >= start_date]
    rets   = ohlcv["close"].pct_change().dropna()
    equity = (1 + rets).cumprod() * capital
    return {
        "equity":  equity,
        "metrics": compute_trading_metrics(rets),
    }
