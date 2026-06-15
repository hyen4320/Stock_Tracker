"""예측 모델 학습/저장/로드.

초기 모델은 scikit-learn의 HistGradientBoostingRegressor를 사용한다.
(추가 의존성 없이 견고한 그래디언트 부스팅, 결측치 자체 처리)

시계열 데이터이므로 평가는 TimeSeriesSplit으로 한다.
"""
from __future__ import annotations

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import TimeSeriesSplit

from config import MODEL_DIR, RANDOM_STATE
from src.data_loader import fetch_history
from src.features import build_feature_frame, feature_columns, make_xy


def _new_model() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        max_iter=300,
        learning_rate=0.05,
        max_depth=3,
        l2_regularization=1.0,
        random_state=RANDOM_STATE,
    )


def model_path(target_name: str):
    return MODEL_DIR / f"{target_name}.joblib"


def train(target_name: str, data: pd.DataFrame | None = None) -> dict:
    """단일 종목 모델을 학습하고 저장. 평가지표 dict 반환."""
    if data is None:
        data = fetch_history()

    df = build_feature_frame(data, target_name)
    X, y = make_xy(df)

    # --- 시계열 교차검증으로 일반화 성능 추정 ---
    tscv = TimeSeriesSplit(n_splits=5)
    maes, baseline_maes = [], []
    for tr_idx, te_idx in tscv.split(X):
        m = _new_model()
        m.fit(X.iloc[tr_idx], y.iloc[tr_idx])
        pred = m.predict(X.iloc[te_idx])
        maes.append(mean_absolute_error(y.iloc[te_idx], pred))
        # 베이스라인: "갭 0%(변동 없음)" 예측
        baseline_maes.append(mean_absolute_error(y.iloc[te_idx], np.zeros(len(te_idx))))

    # --- 전체 데이터로 최종 학습 후 저장 ---
    final = _new_model()
    final.fit(X, y)
    joblib.dump({"model": final, "features": feature_columns(df)}, model_path(target_name))

    return {
        "target": target_name,
        "n_samples": int(len(X)),
        "cv_mae": float(np.mean(maes)),
        "baseline_mae": float(np.mean(baseline_maes)),
        "improvement_pct": float((1 - np.mean(maes) / np.mean(baseline_maes)) * 100),
    }


def load(target_name: str):
    """저장된 모델 번들(dict: model, features) 로드. 없으면 None."""
    path = model_path(target_name)
    if not path.exists():
        return None
    return joblib.load(path)


def predict_gap(target_name: str, feature_row: pd.DataFrame) -> float:
    """피처 1행으로 갭 수익률을 예측. 모델이 없으면 먼저 학습."""
    bundle = load(target_name)
    if bundle is None:
        train(target_name)
        bundle = load(target_name)
    model, feats = bundle["model"], bundle["features"]
    return float(model.predict(feature_row[feats])[0])


if __name__ == "__main__":
    shared = fetch_history()
    from config import TARGETS

    for name in TARGETS:
        metrics = train(name, shared)
        print(
            f"[{metrics['target']}] n={metrics['n_samples']} "
            f"CV-MAE={metrics['cv_mae']:.4%} "
            f"(베이스라인 {metrics['baseline_mae']:.4%}, "
            f"개선 {metrics['improvement_pct']:.1f}%)"
        )
