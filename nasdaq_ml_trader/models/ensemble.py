import numpy as np
import joblib
import torch
from scipy.optimize import minimize
from typing import Optional

from config import LSTM_WINDOW, MODEL_DIR
from models.trainer import LSTMClassifier, load_model
from utils.logger import get_logger

log = get_logger("ensemble")


class EnsembleModel:
    """
    Weighted ensemble of RF + XGB + LSTM.
    Gracefully degrades if any model file is missing:
      _rebalance_weights() zeroes missing models and renormalizes the rest.
    predict_proba() handles partial availability at call time.
    """

    def __init__(self) -> None:
        self.rf      = None
        self.xgb     = None
        self.lstm    = None
        self.scaler  = None
        self.weights = np.array([1/3, 1/3, 1/3])
        self.n_features: int = 0
        self._available: list[str] = []

    def load(self, fold_id="final") -> "EnsembleModel":
        """Load all model components. Missing models are handled via _rebalance_weights."""
        # Scaler
        scaler_path = MODEL_DIR / f"scaler_{fold_id}.joblib"
        if scaler_path.exists():
            self.scaler = joblib.load(scaler_path)
            self.n_features = self.scaler.n_features_in_

        # Optimized weights
        wt_path = MODEL_DIR / "ensemble_weights.joblib"
        if wt_path.exists():
            self.weights = joblib.load(wt_path)

        self.rf   = load_model("rf",   fold_id, self.n_features)
        self.xgb  = load_model("xgb",  fold_id, self.n_features)
        self.lstm = load_model("lstm", fold_id, self.n_features)

        self._available = []
        if self.rf   is not None: self._available.append("rf")
        if self.xgb  is not None: self._available.append("xgb")
        if self.lstm is not None: self._available.append("lstm")

        if not self._available:
            raise RuntimeError("No models loaded -- run: python main.py train")

        self._rebalance_weights()
        log.info(f"Ensemble loaded: {self._available} | weights={self.weights.round(3)}")
        return self

    def _rebalance_weights(self) -> None:
        """Zero-out missing models; renormalise remaining weights proportionally."""
        mask = np.array([
            1.0 if "rf"   in self._available else 0.0,
            1.0 if "xgb"  in self._available else 0.0,
            1.0 if "lstm" in self._available else 0.0,
        ])
        # Preserve optimized ratios where possible; zero missing models
        w = self.weights * mask
        total = w.sum()
        self.weights = w / total if total > 0 else mask / mask.sum()

    def optimize_weights(self, val_results: list[dict]) -> np.ndarray:
        """
        Find weights maximizing Sharpe ratio on walk-forward validation predictions.
        Uses SLSQP with non-negativity constraints and sum=1 equality constraint.
        Saves optimized weights to saved_models/ensemble_weights.joblib.
        """
        # Only include folds that have ALL of the models being optimized so that
        # every stack (rf, xgb, lstm, rets) has the same total number of rows.
        # engine.py guarantees that within a LSTM-bearing fold all arrays are
        # trimmed to the same length, so vstack is safe after this filter.
        want_lstm = "lstm" in self._available
        rf_list, xgb_list, lstm_list, ret_list = [], [], [], []
        for fold in val_results:
            if "rf_proba" not in fold or "next_day_returns" not in fold:
                continue
            if want_lstm and "lstm_proba" not in fold:
                continue  # skip folds where LSTM was unavailable
            rf_list.append(fold["rf_proba"])
            xgb_list.append(fold["xgb_proba"])
            ret_list.append(fold["next_day_returns"])
            if "lstm_proba" in fold:
                lstm_list.append(fold["lstm_proba"])

        if not ret_list:
            log.warning("No validation results -- keeping equal weights")
            return self.weights

        rets = np.concatenate(ret_list)
        available_stacks = []
        if rf_list:   available_stacks.append(np.vstack(rf_list))
        if xgb_list:  available_stacks.append(np.vstack(xgb_list))
        if lstm_list: available_stacks.append(np.vstack(lstm_list))

        if len(available_stacks) < 2:
            log.warning("Fewer than 2 models -- skipping weight optimisation")
            return self.weights

        n_avail = len(available_stacks)

        def neg_sharpe(w: np.ndarray) -> float:
            ens = sum(w[i] * available_stacks[i] for i in range(n_avail))
            signals = ens.argmax(axis=1)            # 0=HOLD, 1=BUY, 2=SELL
            trade_rets = np.where(signals == 1,  rets,
                         np.where(signals == 2, -rets, 0.0))
            std = trade_rets.std()
            return -(trade_rets.mean() / std * np.sqrt(252)) if std > 1e-8 else 0.0

        x0     = np.ones(n_avail) / n_avail
        bounds = [(0.0, 1.0)] * n_avail
        cons   = [{"type": "eq", "fun": lambda w: w.sum() - 1}]

        result = minimize(neg_sharpe, x0, method="SLSQP",
                          bounds=bounds, constraints=cons,
                          options={"maxiter": 300, "ftol": 1e-9})

        if result.success:
            opt = result.x
            # Map back to full [rf, xgb, lstm] array
            full = np.zeros(3)
            names = [n for n in ["rf", "xgb", "lstm"] if n in self._available]
            for i, name in enumerate(names):
                full[["rf", "xgb", "lstm"].index(name)] = opt[i]
            self.weights = full
            log.info(f"Optimized weights: rf={full[0]:.3f} xgb={full[1]:.3f} lstm={full[2]:.3f}")
        else:
            log.warning(f"Weight optimisation failed: {result.message}")

        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.weights, MODEL_DIR / "ensemble_weights.joblib")
        return self.weights

    def predict_proba(
        self,
        X_flat: np.ndarray,
        X_seq: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """
        Weighted average of available model probabilities.
        X_flat: (N, n_features) — for RF/XGB
        X_seq:  (N, LSTM_WINDOW, n_features) — for LSTM (None if not available)
        Returns: (N, 3) probability array [P(HOLD), P(BUY), P(SELL)]
        """
        parts: list[tuple[float, np.ndarray]] = []

        if self.rf is not None and self.weights[0] > 0:
            parts.append((self.weights[0], self.rf.predict_proba(X_flat)))

        if self.xgb is not None and self.weights[1] > 0:
            parts.append((self.weights[1], self.xgb.predict_proba(X_flat)))

        if self.lstm is not None and self.weights[2] > 0 and X_seq is not None:
            self.lstm.eval()
            with torch.no_grad():
                logits = self.lstm(torch.FloatTensor(X_seq))
                lstm_p = torch.softmax(logits, dim=1).numpy()
            parts.append((self.weights[2], lstm_p))

        if not parts:
            raise RuntimeError("No models available for prediction")

        total_w = sum(w for w, _ in parts)
        result  = sum(w / total_w * p for w, p in parts)
        return result

    def predict(
        self,
        X_flat: np.ndarray,
        X_seq: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        return self.predict_proba(X_flat, X_seq).argmax(axis=1)
