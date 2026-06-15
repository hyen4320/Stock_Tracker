"""yfinance 기반 시세 수집.

SOX, 환율, 삼성전자/SK하이닉스의 일봉(OHLC)을 받아 하나의 정렬된
DataFrame으로 반환한다. 컬럼은 (티커별 접두어, 필드) 형태로 평탄화한다.
"""
from __future__ import annotations

import pandas as pd
import yfinance as yf

from config import ALL_TICKERS, HISTORY_PERIOD


def fetch_history(period: str = HISTORY_PERIOD) -> pd.DataFrame:
    """모든 티커의 일봉을 받아 와이드 포맷 DataFrame으로 반환.

    반환 컬럼 예: ``SOX_Close``, ``USDKRW_Close``, ``삼성전자_Open`` ...
    인덱스는 거래일(Date, tz-naive).
    """
    frames: list[pd.DataFrame] = []
    for name, ticker in ALL_TICKERS.items():
        raw = yf.download(
            ticker,
            period=period,
            interval="1d",
            auto_adjust=False,
            progress=False,
        )
        if raw.empty:
            raise RuntimeError(f"'{name}'({ticker}) 데이터를 받지 못했습니다.")

        # yfinance가 MultiIndex 컬럼을 줄 수 있으므로 단일 레벨로 정리
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)

        df = raw[["Open", "High", "Low", "Close"]].copy()
        df.columns = [f"{name}_{col}" for col in df.columns]
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        frames.append(df)

    merged = pd.concat(frames, axis=1).sort_index()
    return merged


def fetch_latest_quote(ticker: str) -> dict | None:
    """단일 티커의 최신(지연 가능) 시세를 dict로 반환. 실패 시 None."""
    try:
        info = yf.Ticker(ticker).fast_info
        return {
            "last_price": float(info.last_price),
            "previous_close": float(info.previous_close),
        }
    except Exception:
        return None


if __name__ == "__main__":
    data = fetch_history("1y")
    print(data.tail())
    print(f"\nshape={data.shape}, 결측 행 {data.isna().any(axis=1).sum()}개")
