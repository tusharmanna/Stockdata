import numpy as np
import pandas as pd
import joblib
import torch
import torch.nn as nn
from pathlib import Path
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from dateutil.relativedelta import relativedelta
from typing import NamedTuple

from config import (
    TRAIN_YEARS, TEST_YEARS, STEP_MONTHS, FINAL_HOLDOUT_DAYS,
    RF_N_ESTIMATORS, RF_MAX_DEPTH, RF_MIN_SAMPLES,
    XGB_N_ESTIMATORS, XGB_MAX_DEPTH, XGB_LR,
    LSTM_HIDDEN, LSTM_LAYERS, LSTM_DROPOUT,
    LSTM_EPOCHS, LSTM_BATCH, LSTM_LR, LSTM_WINDOW,
    MODEL_DIR,
)
from utils.logger import get_logger

log = get_logger("trainer")


# ── LSTM Architecture ──────────────────────────────────────────────────────────

class LSTMClassifier(nn.Module):
    def __init__(
        self,
        n_features: int,
        hidden: int = LSTM_HIDDEN,
        n_layers: int = LSTM_LAYERS,
        dropout: float = LSTM_DROPOUT,
    ):
        super().__init__()
        self.lstm = nn.LSTM(
            n_features, hidden, n_layers,
            batch_first=True,
            dropout=dropout if n_layers > 1 else 0.0,
        )
        self.drop = nn.Dropout(dropout)
        self.fc   = nn.Linear(hidden, 3)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        return self.fc(self.drop(out[:, -1, :]))


# ── Walk-forward fold ──────────────────────────────────────────────────────────

class WFFold(NamedTuple):
    fold_id: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


def generate_folds(index: pd.DatetimeIndex) -> list[WFFold]:
    """
    Rolling 5yr train / 1yr test / 6mo step walk-forward folds.
    The anchor train_start is always index[0] shifted by fold * STEP_MONTHS.
    """
    folds = []
    base = index[0]
    fold_id = 0

    while True:
        train_start = base + relativedelta(months=fold_id * STEP_MONTHS)
        train_end   = train_start + relativedelta(years=TRAIN_YEARS)
        test_start  = train_end
        test_end    = test_start + relativedelta(years=TEST_YEARS)

        if test_end > index[-1]:
            break

        folds.append(WFFold(fold_id, train_start, train_end, test_start, test_end))
        fold_id += 1

    log.info(f"Generated {len(folds)} walk-forward folds")
    return folds


# ── RF ─────────────────────────────────────────────────────────────────────────

def _rf_path(fold_id) -> Path:
    return MODEL_DIR / ("rf_final.joblib" if fold_id == -1 else f"rf_fold{fold_id}.joblib")


def _xgb_path(fold_id) -> Path:
    return MODEL_DIR / ("xgb_final.ubj" if fold_id == -1 else f"xgb_fold{fold_id}.ubj")


def _lstm_path(fold_id) -> Path:
    return MODEL_DIR / ("lstm_final.pt" if fold_id == -1 else f"lstm_fold{fold_id}.pt")


def train_rf(
    X_train: np.ndarray,
    y_train: np.ndarray,
    fold_id: int,
) -> RandomForestClassifier:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    save_path = _rf_path(fold_id)
    if save_path.exists():
        log.info(f"RF fold {fold_id}: loading cached model")
        return joblib.load(save_path)

    log.info(f"RF fold {fold_id}: training on {len(X_train)} samples")
    clf = RandomForestClassifier(
        n_estimators=RF_N_ESTIMATORS,
        max_depth=RF_MAX_DEPTH,
        min_samples_leaf=RF_MIN_SAMPLES,
        class_weight="balanced",
        n_jobs=-1,
        random_state=42,
    )
    clf.fit(X_train, y_train)
    joblib.dump(clf, save_path)
    return clf


# ── XGBoost ────────────────────────────────────────────────────────────────────

def train_xgb(
    X_train: np.ndarray,
    y_train: np.ndarray,
    fold_id: int,
):
    import xgboost as xgb
    from sklearn.utils.class_weight import compute_sample_weight

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    save_path = _xgb_path(fold_id)
    if save_path.exists():
        log.info(f"XGB fold {fold_id}: loading cached model")
        m = xgb.XGBClassifier()
        m.load_model(str(save_path))
        return m

    log.info(f"XGB fold {fold_id}: training on {len(X_train)} samples")
    weights = compute_sample_weight("balanced", y_train)
    split   = int(len(X_train) * 0.8)

    model = xgb.XGBClassifier(
        n_estimators=XGB_N_ESTIMATORS,
        max_depth=XGB_MAX_DEPTH,
        learning_rate=XGB_LR,
        objective="multi:softprob",
        num_class=3,
        eval_metric="mlogloss",
        early_stopping_rounds=20,
        n_jobs=-1,
        random_state=42,
        verbosity=0,
    )
    model.fit(
        X_train[:split], y_train[:split],
        sample_weight=weights[:split],
        eval_set=[(X_train[split:], y_train[split:])],
        verbose=False,
    )
    model.save_model(str(save_path))
    return model


# ── LSTM ───────────────────────────────────────────────────────────────────────

def train_lstm(
    X_seq: np.ndarray,
    y_seq: np.ndarray,
    n_features: int,
    fold_id: int,
) -> LSTMClassifier:
    """
    Train LSTM with fold-level disk caching (key optimisation for CPU-only Windows).
    num_workers=0 required on Windows (fork-based multiprocessing fails with PyTorch).
    shuffle=False mandatory for time-series data.
    """
    from torch.utils.data import DataLoader, TensorDataset

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    save_path = _lstm_path(fold_id)

    # Fold cache: skip retraining if already done
    if save_path.exists():
        log.info(f"LSTM fold {fold_id}: loading cached model")
        m = LSTMClassifier(n_features)
        m.load_state_dict(torch.load(save_path, map_location="cpu", weights_only=True))
        m.eval()
        return m

    epochs = LSTM_EPOCHS if fold_id == -1 else max(30, LSTM_EPOCHS - 20)
    log.info(f"LSTM fold {fold_id}: training {len(X_seq)} sequences, {epochs} epochs")

    X_t = torch.FloatTensor(X_seq)
    y_t = torch.LongTensor(y_seq)

    split    = int(len(X_t) * 0.85)
    ds_train = TensorDataset(X_t[:split], y_t[:split])
    ds_val   = TensorDataset(X_t[split:], y_t[split:])

    train_loader = DataLoader(ds_train, batch_size=LSTM_BATCH, shuffle=False,
                              num_workers=0, pin_memory=False)
    val_loader   = DataLoader(ds_val,   batch_size=256, shuffle=False,
                              num_workers=0, pin_memory=False)

    model     = LSTMClassifier(n_features)
    optimizer = torch.optim.Adam(model.parameters(), lr=LSTM_LR)
    criterion = nn.CrossEntropyLoss()
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=3, factor=0.5)

    best_val = float("inf")
    patience  = 0

    for epoch in range(epochs):
        model.train()
        for xb, yb in train_loader:
            optimizer.zero_grad()
            loss = criterion(model(xb), yb)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for xb, yb in val_loader:
                val_loss += criterion(model(xb), yb).item()
        val_loss /= max(1, len(val_loader))
        scheduler.step(val_loss)

        if val_loss < best_val:
            best_val = val_loss
            torch.save(model.state_dict(), save_path)
            patience = 0
        else:
            patience += 1
            if patience >= 5:
                log.info(f"LSTM fold {fold_id}: early stop at epoch {epoch + 1}")
                break

    model.load_state_dict(torch.load(save_path, map_location="cpu", weights_only=True))
    model.eval()
    return model


# ── Final models ───────────────────────────────────────────────────────────────

def train_final_models(X: pd.DataFrame, y: pd.Series) -> dict:
    """
    Retrain all models on full history up to FINAL_HOLDOUT_DAYS before end.
    fold_id=-1 is the sentinel for final models; files renamed to *_final.*.
    """
    from data.features import build_lstm_sequences

    cutoff   = len(X) - FINAL_HOLDOUT_DAYS
    X_train  = X.iloc[:cutoff]
    y_train  = y.iloc[:cutoff]

    scaler   = StandardScaler()
    X_scaled = scaler.fit_transform(X_train)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(scaler, MODEL_DIR / "scaler_final.joblib")

    # fold_id=-1 triggers _rf_path(-1) → rf_final.joblib (direct save, no rename needed)
    rf   = train_rf(X_scaled,  y_train.values, fold_id=-1)
    xgb_ = train_xgb(X_scaled, y_train.values, fold_id=-1)

    X_seq, y_seq = build_lstm_sequences(
        pd.DataFrame(X_scaled, columns=X.columns, index=X_train.index),
        y_train,
    )
    lstm = train_lstm(X_seq, y_seq, X.shape[1], fold_id=-1)

    log.info("Final models saved to saved_models/")
    return {"rf": rf, "xgb": xgb_, "lstm": lstm, "scaler": scaler}


# ── Load helper ────────────────────────────────────────────────────────────────

def load_model(model_type: str, fold_id, n_features: int = 0):
    """
    Returns None (not raises) if the model file is missing.
    fold_id="final" → rf_final.joblib / xgb_final.ubj / lstm_final.pt
    fold_id=N       → rf_foldN.joblib  / xgb_foldN.ubj  / lstm_foldN.pt
    """
    if str(fold_id) == "final":
        stem = f"{model_type}_final"
    else:
        stem = f"{model_type}_fold{fold_id}"

    try:
        if model_type == "rf":
            p = MODEL_DIR / f"{stem}.joblib"
            return joblib.load(p) if p.exists() else None
        elif model_type == "xgb":
            import xgboost as xgb
            p = MODEL_DIR / f"{stem}.ubj"
            if not p.exists():
                return None
            m = xgb.XGBClassifier()
            m.load_model(str(p))
            return m
        elif model_type == "lstm":
            p = MODEL_DIR / f"{stem}.pt"
            if not p.exists():
                return None
            m = LSTMClassifier(n_features)
            m.load_state_dict(torch.load(p, map_location="cpu", weights_only=True))
            m.eval()
            return m
    except Exception as e:
        log.warning(f"Could not load {model_type} ({stem}): {e}")
        return None
