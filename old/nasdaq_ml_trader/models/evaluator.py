import numpy as np
import pandas as pd
from sklearn.metrics import classification_report


def evaluate_fold(
    model,
    X_test: np.ndarray,
    y_test: np.ndarray,
    model_name: str,
) -> dict:
    """
    Evaluate a trained model on a test fold.
    Works with RF, XGB, and LSTM (all expose predict_proba or equivalent).
    """
    import torch

    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(X_test)
    else:
        # LSTM (nn.Module)
        model.eval()
        with torch.no_grad():
            logits = model(torch.FloatTensor(X_test))
            proba  = torch.softmax(logits, dim=1).numpy()

    preds = proba.argmax(axis=1)
    acc   = float((preds == y_test).mean())

    return {
        "model":    model_name,
        "n_test":   len(y_test),
        "accuracy": acc,
        "proba":    proba,
        "preds":    preds,
        "actuals":  y_test,
        "report":   classification_report(
            y_test, preds,
            labels=[0, 1, 2],
            target_names=["HOLD", "BUY", "SELL"],
            output_dict=True,
            zero_division=0,
        ),
    }


def compute_trading_metrics(
    returns: pd.Series,
    risk_free: float = 0.04,
) -> dict:
    """
    Full suite of backtest performance metrics from a daily returns series.
    """
    if returns.empty or len(returns) < 5:
        return {k: 0.0 for k in [
            "cagr", "sharpe", "sortino", "max_drawdown",
            "win_rate", "profit_factor", "avg_win", "avg_loss", "calmar",
        ]}

    total_ret = float((1 + returns).prod())
    n_years   = len(returns) / 252
    cagr      = total_ret ** (1 / n_years) - 1 if n_years > 0 else 0.0

    # Use annualised formulation so that HOLD days (return=0) don't inflate
    # the Sharpe denominator with near-zero variance when most days are flat.
    ann_vol = float(returns.std() * np.sqrt(252))
    sharpe  = float((cagr - risk_free) / ann_vol) if ann_vol > 1e-6 else 0.0

    neg_ret  = returns[returns < 0]
    downside = float(neg_ret.std() * np.sqrt(252)) if len(neg_ret) > 0 else 1e-9
    sortino  = float((cagr - risk_free) / downside)

    cum        = (1 + returns).cumprod()
    roll_max   = cum.cummax()
    drawdown   = (cum - roll_max) / roll_max
    max_dd     = float(drawdown.min())

    calmar = cagr / abs(max_dd) if max_dd != 0 else 0.0

    traded    = returns[returns != 0]
    wins      = traded[traded > 0]
    losses    = traded[traded < 0]
    win_rate  = len(wins) / len(traded) if len(traded) > 0 else 0.0
    avg_win   = float(wins.mean()) if len(wins) > 0 else 0.0
    avg_loss  = float(losses.mean()) if len(losses) > 0 else 0.0
    pf_denom  = abs(losses.sum())
    pf        = float(wins.sum() / pf_denom) if pf_denom > 0 else 0.0

    return {
        "cagr":          round(cagr, 4),
        "sharpe":        round(sharpe, 4),
        "sortino":       round(sortino, 4),
        "calmar":        round(calmar, 4),
        "max_drawdown":  round(max_dd, 4),
        "win_rate":      round(win_rate, 4),
        "profit_factor": round(pf, 4),
        "avg_win":       round(avg_win, 6),
        "avg_loss":      round(avg_loss, 6),
        "n_trades":      len(traded),
        "n_years":       round(n_years, 2),
    }
