"""읽기 전용 조회 함수 (API가 DB에서 데이터를 꺼낼 때 사용)."""
from __future__ import annotations

from sqlalchemy import func, select

from backend.db import SessionLocal
from backend.models import Prediction
from config import TARGETS


def latest_predictions() -> list[dict]:
    """가장 최근 target_date 의 예측들."""
    with SessionLocal() as s:
        latest_date = s.scalar(select(func.max(Prediction.target_date)))
        if latest_date is None:
            return []
        rows = s.scalars(
            select(Prediction)
            .where(Prediction.target_date == latest_date)
            .order_by(Prediction.target_name)
        ).all()
        return [r.to_dict() for r in rows]


def prediction_history(target: str | None = None, limit: int = 60) -> list[dict]:
    """과거 예측 이력(최신순). target 지정 시 해당 종목만."""
    with SessionLocal() as s:
        stmt = select(Prediction).order_by(Prediction.target_date.desc())
        if target:
            stmt = stmt.where(Prediction.target_name == target)
        rows = s.scalars(stmt.limit(limit)).all()
        return [r.to_dict() for r in rows]


def accuracy_stats() -> list[dict]:
    """종목별 적중 통계 (실제값이 기록된 예측 대상)."""
    out = []
    with SessionLocal() as s:
        for name in TARGETS:
            rows = s.scalars(
                select(Prediction).where(
                    Prediction.target_name == name,
                    Prediction.actual_open.is_not(None),
                )
            ).all()
            n = len(rows)
            if n == 0:
                out.append({"target": name, "n": 0})
                continue

            mae = sum(abs(r.error_pct) for r in rows) / n
            # 방향 적중: 예측 갭 부호 == 실제 갭 부호
            hits = 0
            for r in rows:
                actual_gap = r.actual_open / r.last_close - 1.0
                if (r.predicted_gap >= 0) == (actual_gap >= 0):
                    hits += 1
            out.append(
                {
                    "target": name,
                    "n": n,
                    "mae_pct": mae,
                    "direction_hit_rate": hits / n,
                }
            )
    return out
