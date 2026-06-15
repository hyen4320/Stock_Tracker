"""ORM 모델.

predictions: 매일 생성되는 예측 1행 + 다음날 채워지는 실제값/오차.
(target_date, target_name) 유니크 → 같은 날 같은 종목은 한 행으로 upsert.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Float, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint("target_date", "target_name", name="uq_pred_date_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    prediction_date: Mapped[date] = mapped_column(Date, index=True)  # 예측 생성일
    target_date: Mapped[date] = mapped_column(Date, index=True)      # 예측 대상 거래일
    target_name: Mapped[str] = mapped_column(String(40), index=True)

    last_close: Mapped[float] = mapped_column(Float)        # 직전 종가
    predicted_gap: Mapped[float] = mapped_column(Float)     # 예측 갭(소수)
    estimated_open: Mapped[float] = mapped_column(Float)    # 예상 시초가

    # 예측에 사용한 드라이버 값 (재현/디버깅용)
    sox_ret: Mapped[float | None] = mapped_column(Float, nullable=True)
    fx_ret: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 다음날 개장 후 채워짐
    actual_open: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=_utcnow
    )

    def to_dict(self) -> dict:
        return {
            "prediction_date": self.prediction_date.isoformat(),
            "target_date": self.target_date.isoformat(),
            "target": self.target_name,
            "last_close": self.last_close,
            "predicted_gap": self.predicted_gap,
            "estimated_open": self.estimated_open,
            "change": self.estimated_open - self.last_close,
            "sox_ret": self.sox_ret,
            "fx_ret": self.fx_ret,
            "actual_open": self.actual_open,
            "error_pct": self.error_pct,
        }
