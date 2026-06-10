import json
import numpy as np
import pandas as pd
import joblib
from datetime import datetime

from old.nasdaq_ml_trader.config import MIN_CONFIDENCE, LSTM_WINDOW, SIGNAL_LOG, MODEL_DIR, DEFAULT_CAPITAL
from old.nasdaq_ml_trader.data.fetcher import get_ohlcv
from old.nasdaq_ml_trader.data.features import compute_features
from old.nasdaq_ml_trader.models.ensemble import EnsembleModel
from old.nasdaq_ml_trader.sizing.position_sizer import size_all_methods
from old.nasdaq_ml_trader.utils.logger import get_logger

log = get_logger("generator")

LABEL_MAP = {0: "HOLD", 1: "BUY", 2: "SELL"}


def _prepare_inputs(
    X_full: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray | None]:
    """
    Scale the most recent row for RF/XGB and build the 60-day LSTM window.
    Loads scaler_final.joblib saved by train_final_models().
    """
    scaler_path = MODEL_DIR / "scaler_final.joblib"
    if not scaler_path.exists():
        raise RuntimeError("Scaler not found -- run: python main.py train")

    scaler  = joblib.load(scaler_path)
    X_last  = X_full.iloc[[-1]]
    X_flat  = scaler.transform(X_last)

    if len(X_full) >= LSTM_WINDOW:
        window        = X_full.iloc[-LSTM_WINDOW:]
        window_scaled = scaler.transform(window)
        X_seq         = window_scaled[np.newaxis, :, :]
    else:
        X_seq = None

    return X_flat, X_seq


def generate_signal(
    capital: float = DEFAULT_CAPITAL,
    win_rate: float = 0.55,
    avg_win: float  = 0.02,
    avg_loss: float = 0.015,
) -> dict:
    """
    Main daily signal generation entry point.
    Loads latest OHLCV, computes features, runs ensemble, sizes positions, logs result.
    """
    ohlcv = get_ohlcv()

    if len(ohlcv) < 252:
        raise RuntimeError(
            f"Insufficient data ({len(ohlcv)} bars). Need at least 252 trading days."
        )

    X_full = compute_features(ohlcv).dropna()
    ohlcv_aligned = ohlcv.loc[X_full.index]

    ensemble = EnsembleModel().load("final")

    X_flat, X_seq = _prepare_inputs(X_full)
    proba = ensemble.predict_proba(X_flat, X_seq)[0]  # shape (3,)

    pred_class  = int(proba.argmax())
    confidence  = float(proba.max())
    signal_raw  = LABEL_MAP[pred_class]
    filtered    = confidence < MIN_CONFIDENCE
    signal      = signal_raw if not filtered else "HOLD"

    last_bar = ohlcv_aligned.iloc[-1]
    atr_val  = float(X_full["atr_14"].iloc[-1]) if "atr_14" in X_full.columns else 0.0
    sizes    = size_all_methods(
        capital, atr_val, float(last_bar["close"]),
        confidence, win_rate, avg_win, avg_loss,
    )

    result = {
        "date":                ohlcv_aligned.index[-1].strftime("%Y-%m-%d"),
        "generated_at":        datetime.utcnow().isoformat(),
        "signal":              signal,
        "signal_raw":          signal_raw,
        "confidence_filtered": filtered,
        "p_hold":              round(float(proba[0]), 4),
        "p_buy":               round(float(proba[1]), 4),
        "p_sell":              round(float(proba[2]), 4),
        "confidence":          round(confidence, 4),
        "close":               round(float(last_bar["close"]), 2),
        "models_active":       ensemble._available,
        "weights": {
            "rf":   round(float(ensemble.weights[0]), 3),
            "xgb":  round(float(ensemble.weights[1]), 3),
            "lstm": round(float(ensemble.weights[2]), 3),
        },
        "sizing": sizes,
    }

    _log_signal(result)
    log.info(f"Signal: {signal} (raw={signal_raw}, conf={confidence:.3f}, "
             f"filtered={filtered})")
    return result


def _log_signal(signal: dict) -> None:
    SIGNAL_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(SIGNAL_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(signal) + "\n")


def get_signal_history(n: int = 30) -> list[dict]:
    if not SIGNAL_LOG.exists():
        return []
    lines = SIGNAL_LOG.read_text(encoding="utf-8").strip().split("\n")
    valid = [l for l in lines if l.strip()]
    return [json.loads(l) for l in valid[-n:]]
