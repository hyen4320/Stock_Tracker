"""엔드투엔드 예측: 현재 SOX/환율 변동 -> 삼성/하이닉스 추정 시초가.

대시보드와 CLI가 공통으로 쓰는 고수준 함수를 제공한다.
"""
from __future__ import annotations

import pandas as pd

from config import TARGETS
from src.data_loader import fetch_history
from src.features import latest_feature_row
from src.model import predict_gap


def predict_open(
    data: pd.DataFrame,
    target_name: str,
    sox_live_ret: float | None = None,
    fx_live_ret: float | None = None,
) -> dict:
    """단일 종목의 다음 시초가 예측 결과를 dict로 반환.

    sox_live_ret / fx_live_ret 를 주면 밤사이 실시간 변동을 반영한다.
    (예: SOX가 현재 +2.0%면 sox_live_ret=0.02)
    """
    last_close = float(data[f"{target_name}_Close"].dropna().iloc[-1])
    row = latest_feature_row(data, target_name, sox_live_ret, fx_live_ret)
    gap = predict_gap(target_name, row)
    est_open = last_close * (1 + gap)
    return {
        "target": target_name,
        "last_close": last_close,
        "predicted_gap": gap,
        "estimated_open": est_open,
        "change": est_open - last_close,
    }


def predict_all(
    sox_live_ret: float | None = None,
    fx_live_ret: float | None = None,
    data: pd.DataFrame | None = None,
) -> list[dict]:
    """모든 대상 종목에 대한 예측 리스트."""
    if data is None:
        data = fetch_history()
    return [
        predict_open(data, name, sox_live_ret, fx_live_ret) for name in TARGETS
    ]


if __name__ == "__main__":
    for res in predict_all():
        print(
            f"[{res['target']}] 종가 {res['last_close']:,.0f} -> "
            f"예상 시초가 {res['estimated_open']:,.0f} "
            f"({res['predicted_gap']:+.2%})"
        )
