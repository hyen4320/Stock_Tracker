"""시세 데이터 인메모리 TTL 캐시.

매 API 요청마다 yfinance를 다시 호출하지 않도록 일정 시간 캐싱한다.
(Streamlit의 @st.cache_data(ttl=...)를 대체)
"""
from __future__ import annotations

import time

import pandas as pd

from src.data_loader import fetch_history

_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}
_TTL_SECONDS = 900  # 15분


def get_history(force: bool = False) -> pd.DataFrame:
    """캐시된 시세를 반환. 만료(또는 force)면 새로 받아온다."""
    now = time.time()
    cached = _CACHE.get("history")
    if not force and cached is not None and now - cached[0] < _TTL_SECONDS:
        return cached[1]
    data = fetch_history()
    _CACHE["history"] = (now, data)
    return data


def clear() -> None:
    _CACHE.clear()
