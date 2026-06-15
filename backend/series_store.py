"""일별 다지표 시계열 캐시(DailySeries)의 DB 정본 접근.

KRX 수급/프로그램매매, 금투협 신용/증시자금, 네이버 외국인 수급 캐시를
로컬 CSV 대신 DB에 둔다(durability·단일 백업 지점). long-format으로 저장하고
읽을 때 wide DataFrame(date 인덱스 × metric 컬럼)으로 pivot한다.

experiments(연구 코드)도 이 모듈로 캐시를 읽으므로 최초 접근 시 init_db() 1회.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import select

from backend.db import SessionLocal, engine, init_db
from backend.models import DailySeries

_CHUNK = 1000
_initialized = False


def _ensure_db() -> None:
    global _initialized
    if not _initialized:
        init_db()
        _initialized = True


def _upsert_stmt():
    if engine.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    ins = insert(DailySeries)
    return ins.on_conflict_do_update(
        index_elements=["source", "entity", "date", "metric"],
        set_={"value": ins.excluded.value},
    )


def load_frame(source: str, entity: str = "") -> pd.DataFrame:
    """(source, entity)의 전체 시계열을 wide DataFrame으로 반환(없으면 빈 DF).

    index=DatetimeIndex(date), columns=metric. 셀 부재는 NaN(pivot 결과 그대로).
    """
    _ensure_db()
    with SessionLocal() as s:
        rows = s.execute(
            select(DailySeries.date, DailySeries.metric, DailySeries.value)
            .where(DailySeries.source == source, DailySeries.entity == entity)
        ).all()
    if not rows:
        return pd.DataFrame()
    long = pd.DataFrame(rows, columns=["date", "metric", "value"])
    wide = long.pivot(index="date", columns="metric", values="value").sort_index()
    wide.index = pd.DatetimeIndex(wide.index)
    wide.columns.name = None
    return wide


def upsert_frame(source: str, df: pd.DataFrame, entity: str = "") -> int:
    """wide DataFrame을 long으로 풀어 멱등 upsert한다. 처리한 셀 수를 반환.

    df index=날짜, columns=metric. NaN 셀은 저장하지 않는다(부재=NaN로 복원됨).
    """
    _ensure_db()
    if df is None or df.empty:
        return 0
    idx = pd.DatetimeIndex(df.index)
    rows: list[dict] = []
    for metric in df.columns:
        col = pd.to_numeric(df[metric], errors="coerce")
        for ts, v in zip(idx, col.to_numpy()):
            if pd.notna(v):
                rows.append({
                    "source": source, "entity": entity,
                    "date": ts.date(), "metric": str(metric), "value": float(v),
                })
    if not rows:
        return 0
    stmt = _upsert_stmt()
    with SessionLocal() as s:
        for i in range(0, len(rows), _CHUNK):
            s.execute(stmt, rows[i : i + _CHUNK])
        s.commit()
    return len(rows)
