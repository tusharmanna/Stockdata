import math
from config import DEFAULT_CAPITAL, ATR_RISK_DOLLARS, KELLY_MAX_FRAC


def fixed_fractional(
    capital: float,
    confidence: float,
    fraction: float = 0.02,
) -> dict:
    """
    Allocate capital × fraction, scaled down linearly by confidence.
    confidence_scalar maps [0.5, 1.0] → [0, 1] so min-threshold signals get near-zero size.
    Adapted from compute_dual_position() stage-band logic in whitelight_strategy.py.
    """
    scalar = min(1.0, max(0.0, (confidence - 0.5) / 0.5))
    allocation = capital * fraction * scalar
    return {
        "method": "fixed_fractional",
        "fraction": round(fraction, 4),
        "confidence_scalar": round(scalar, 3),
        "allocation": round(allocation, 2),
        "pct_of_capital": round(allocation / capital if capital > 0 else 0, 4),
    }


def atr_position_size(
    capital: float,
    atr: float,
    price: float,
    risk_dollars: float = ATR_RISK_DOLLARS,
) -> dict:
    """
    Classic ATR sizing: shares = floor(risk_dollars / atr).
    Capped at 20% of capital to prevent over-concentration.
    Adapted directly from _unit_shares() in turtle_strategy.py.
    """
    if atr <= 0 or price <= 0:
        return {"method": "atr_based", "shares": 0, "allocation": 0.0,
                "atr": atr, "risk_dollars": risk_dollars}
    shares = math.floor(risk_dollars / atr)
    allocation = shares * price
    max_alloc = capital * 0.20
    if allocation > max_alloc:
        shares = math.floor(max_alloc / price)
        allocation = shares * price
    return {
        "method": "atr_based",
        "shares": shares,
        "allocation": round(allocation, 2),
        "atr": round(atr, 4),
        "risk_dollars": risk_dollars,
        "pct_of_capital": round(allocation / capital if capital > 0 else 0, 4),
    }


def kelly_position_size(
    capital: float,
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    max_fraction: float = KELLY_MAX_FRAC,
) -> dict:
    """
    Half-Kelly criterion: f* = win_rate - (1 - win_rate) / (avg_win / avg_loss).
    Halved for safety; capped at max_fraction.
    Falls back to 0 allocation if edge is negative or inputs are invalid.
    """
    if avg_loss <= 0 or win_rate <= 0 or avg_win <= 0 or win_rate >= 1:
        return {"method": "kelly", "kelly_f": 0.0, "effective_f": 0.0,
                "allocation": 0.0, "note": "invalid inputs — no position"}
    odds = avg_win / avg_loss
    kelly_f = win_rate - (1 - win_rate) / odds
    kelly_f = max(0.0, kelly_f)
    half_kelly = kelly_f / 2.0
    eff_f = min(half_kelly, max_fraction)
    allocation = capital * eff_f
    return {
        "method": "kelly",
        "kelly_f": round(kelly_f, 4),
        "half_kelly_f": round(half_kelly, 4),
        "effective_f": round(eff_f, 4),
        "allocation": round(allocation, 2),
        "pct_of_capital": round(eff_f, 4),
        "win_rate": round(win_rate, 4),
        "avg_win": round(avg_win, 6),
        "avg_loss": round(avg_loss, 6),
    }


def size_all_methods(
    capital: float,
    atr: float,
    price: float,
    confidence: float,
    win_rate: float = 0.55,
    avg_win: float = 0.02,
    avg_loss: float = 0.015,
) -> dict:
    """Compute all three sizing methods and return combined dict."""
    return {
        "fixed_fractional": fixed_fractional(capital, confidence),
        "atr_based": atr_position_size(capital, atr, price),
        "kelly": kelly_position_size(capital, win_rate, avg_win, avg_loss),
    }
