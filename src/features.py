"""피처 엔지니어링 + 시간대 정렬.

핵심 아이디어
-------------
한국 정규장 마감(15:30 KST) 이후, 같은 날짜의 미국 SOX 세션이 밤사이 거래되고
그 결과가 다음날 한국 시초가의 '갭'으로 반영된다.

따라서 날짜 D 기준으로:
  - 타깃 y  : 한국주식 종가[D] -> 다음 거래일 시초가[D+1] 갭 수익률
  - 피처 X  : SOX 수익률[D], 환율 수익률[D], 종목 자체 모멘텀[D] 및 시차들
모두 D+1 시초가 시점에 알 수 있는 정보만 사용한다(미래 정보 누수 방지).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import DRIVERS, LAGS


def _pct_change(s: pd.Series) -> pd.Series:
    return s.pct_change(fill_method=None)


def build_feature_frame(data: pd.DataFrame, target_name: str) -> pd.DataFrame:
    """단일 종목에 대한 (피처 + 타깃) DataFrame 생성.

    Parameters
    ----------
    data : data_loader.fetch_history()의 출력
    target_name : "삼성전자" 또는 "SK하이닉스"
    """
    df = pd.DataFrame(index=data.index)

    # --- 드라이버 피처: SOX / 환율 일간 수익률 ---
    for drv in DRIVERS:  # "SOX", "USDKRW"
        ret = _pct_change(data[f"{drv}_Close"])
        df[f"{drv}_ret"] = ret
        for lag in LAGS:
            df[f"{drv}_ret_lag{lag}"] = ret.shift(lag)

    # --- 종목 자체 모멘텀(당일 종가 수익률 및 시차) ---
    stock_close = data[f"{target_name}_Close"]
    stock_ret = _pct_change(stock_close)
    df[f"{target_name}_ret"] = stock_ret
    for lag in LAGS:
        df[f"{target_name}_ret_lag{lag}"] = stock_ret.shift(lag)

    # --- 타깃: 종가[D] -> 다음날 시초가[D+1] 갭 수익률 ---
    next_open = data[f"{target_name}_Open"].shift(-1)
    df["target_gap"] = next_open / stock_close - 1.0

    return df


def feature_columns(df: pd.DataFrame) -> list[str]:
    """타깃을 제외한 피처 컬럼 목록."""
    return [c for c in df.columns if c != "target_gap"]


def make_xy(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """학습용 (X, y). 결측(맨 앞 시차/맨 뒤 타깃)을 제거한다."""
    cols = feature_columns(df)
    clean = df.dropna(subset=cols + ["target_gap"])
    return clean[cols], clean["target_gap"]


def latest_feature_row(
    data: pd.DataFrame,
    target_name: str,
    sox_live_ret: float | None = None,
    fx_live_ret: float | None = None,
) -> pd.DataFrame:
    """가장 최근 시점의 피처 1행을 반환(예측용).

    밤사이 실시간 추정을 위해 SOX/환율의 '현재' 수익률을 주입할 수 있다.
    값을 주면 해당 피처를 덮어써서 실시간 추정가를 계산할 수 있다.
    """
    df = build_feature_frame(data, target_name)
    cols = feature_columns(df)
    row = df[cols].dropna().iloc[[-1]].copy()

    if sox_live_ret is not None:
        row["SOX_ret"] = sox_live_ret
    if fx_live_ret is not None:
        row["USDKRW_ret"] = fx_live_ret

    return row
