"""인트라데이 시간봉 캐시의 DB 정본 접근 (개선점 #6).

기존엔 data/intraday_*.parquet 가 정본이었으나, 로컬 파일이라 머신 손실 시
복구 불가한 과거(yfinance 730일 한계)가 함께 사라진다. 관리형 Postgres에
저장해 durability를 확보한다. 같은 SQLAlchemy 코드로 SQLite 폴백도 동작.

experiments(연구 코드)도 이 모듈을 통해 캐시를 읽으므로, 단독 실행에서도
테이블이 보장되도록 최초 접근 시 init_db()를 1회 호출한다.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import select

from backend.db import SessionLocal, engine, init_db
from backend.models import IntradayBar

_CHUNK = 1000
_initialized = False


def _ensure_db() -> None:
    """테이블 보장(최초 1회). create_all 은 존재 시 no-op이라 반복 호출 안전."""
    global _initialized
    if not _initialized:
        init_db()
        _initialized = True


def _upsert_stmt():
    """방언별 ON CONFLICT upsert. PG/SQLite 모두 (ticker, ts) 충돌 시 close 갱신."""
    if engine.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    ins = insert(IntradayBar)
    return ins.on_conflict_do_update(
        index_elements=["ticker", "ts"],
        set_={"close": ins.excluded.close},
    )


def load_bars(ticker: str) -> pd.Series:
    """티커의 전체 시간봉 종가를 UTC 인덱스 Series로 반환(없으면 빈 Series)."""
    _ensure_db()
    with SessionLocal() as s:
        rows = s.execute(
            select(IntradayBar.ts, IntradayBar.close)
            .where(IntradayBar.ticker == ticker)
            .order_by(IntradayBar.ts)
        ).all()
    if not rows:
        return pd.Series(dtype=float, name="close")
    idx = pd.DatetimeIndex([r[0] for r in rows])
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    return pd.Series([r[1] for r in rows], index=idx, name="close")


def upsert_bars(ticker: str, series: pd.Series) -> int:
    """시간봉 종가 Series를 멱등 upsert한다. 처리한 봉 수를 반환.

    series 인덱스는 봉 종료 시각(tz-aware 권장). 충돌 시 close 를 keep-last 갱신.
    """
    _ensure_db()
    series = series.dropna()
    if series.empty:
        return 0
    idx = series.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    rows = [
        {"ticker": ticker, "ts": ts.to_pydatetime(), "close": float(c)}
        for ts, c in zip(idx, series.to_numpy())
    ]
    stmt = _upsert_stmt()
    with SessionLocal() as s:
        for i in range(0, len(rows), _CHUNK):
            s.execute(stmt, rows[i : i + _CHUNK])
        s.commit()
    return len(rows)
