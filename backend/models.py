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


class IntradayBar(Base):
    """인트라데이 시간봉 종가 캐시(개선점 #6). yfinance 730일 한계로 사라지는
    과거를 박제하는 durable 정본 — (ticker, ts) 복합 PK로 멱등 upsert.

    ts 는 봉 *종료* 시각(UTC). close 는 종가. 종목별 ~1.5만행 규모로 가볍다.
    """

    __tablename__ = "intraday_bars"

    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    close: Mapped[float] = mapped_column(Float)


class DailySeries(Base):
    """일별 다(多)지표 시계열의 범용 long-format 캐시.

    KRX 수급/프로그램매매, 금투협 신용/증시자금, 네이버 외국인 수급 등 소스마다
    컬럼이 다른 캐시를 테이블 하나로 담는다(컬럼 가변 → 테이블 4개·ALTER 회피).
    한 셀 = (source, entity, date, metric) → value. wide DataFrame은 읽을 때 pivot.

      source : 'krx_supply' | 'krx_program' | 'kofia' | 'naver_frgn' ...
      entity : 종목코드('005930')·시장('STK')·종류('credit') 등 (없으면 '')
      metric : 컬럼명('frgn_net' 등)
    """

    __tablename__ = "daily_series"

    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    entity: Mapped[str] = mapped_column(String(32), primary_key=True, default="")
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    metric: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[float] = mapped_column(Float)
