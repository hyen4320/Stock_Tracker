"""예측 배치 작업.

- run_daily_prediction: 개장 전, 오늘자 예측을 계산해 DB에 upsert
- record_actuals: 개장 후, 실제 시초가를 채우고 오차 계산

스케줄러(backend.scheduler)와 수동 스크립트(scripts/run_daily_prediction.py)가 공유한다.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select

from backend import cache
from backend.db import SessionLocal
from backend.models import Prediction
from config import DRIVERS, TARGETS, TIMEZONE
from src.data_loader import fetch_latest_quote
from src.model import load, train
from src.predict import predict_open

log = logging.getLogger("jobs")
KST = ZoneInfo(TIMEZONE)


def _today_kst() -> date:
    return datetime.now(KST).date()


def _live_ret(ticker: str) -> float | None:
    """드라이버의 전일 종가 대비 현재 수익률."""
    q = fetch_latest_quote(ticker)
    if q and q["previous_close"]:
        return q["last_price"] / q["previous_close"] - 1.0
    return None


def run_daily_prediction(force: bool = False) -> int:
    """오늘자 예측을 생성/갱신한다. 저장(또는 갱신)된 행 수를 반환."""
    # 모델이 없으면 먼저 학습 (콜드 스타트 보호)
    data = cache.get_history(force=force)
    for name in TARGETS:
        if load(name) is None:
            log.info("모델 없음 → 학습: %s", name)
            train(name, data)

    target_date = _today_kst()
    sox = _live_ret(DRIVERS["SOX"])
    fx = _live_ret(DRIVERS["USDKRW"])

    saved = 0
    with SessionLocal() as s:
        for name in TARGETS:
            existing = s.scalar(
                select(Prediction).where(
                    Prediction.target_date == target_date,
                    Prediction.target_name == name,
                )
            )
            if existing is not None and not force:
                continue  # 이미 오늘 예측 있음 → 멱등

            r = predict_open(data, name, sox, fx)
            obj = existing or Prediction(target_date=target_date, target_name=name)
            obj.prediction_date = target_date
            obj.last_close = r["last_close"]
            obj.predicted_gap = r["predicted_gap"]
            obj.estimated_open = r["estimated_open"]
            obj.sox_ret = sox
            obj.fx_ret = fx
            if existing is None:
                s.add(obj)
            saved += 1
        s.commit()

    log.info("예측 저장 완료: %d행 (target_date=%s)", saved, target_date)
    return saved


def record_actuals() -> int:
    """실제 시초가가 아직 안 채워진 예측에 실제값/오차를 기록. 갱신 행 수 반환."""
    data = cache.get_history(force=True)
    updated = 0
    with SessionLocal() as s:
        pending = s.scalars(
            select(Prediction).where(Prediction.actual_open.is_(None))
        ).all()
        for obj in pending:
            col = f"{obj.target_name}_Open"
            ts = pd.Timestamp(obj.target_date)
            if col not in data.columns or ts not in data.index:
                continue
            val = data.loc[ts, col]
            if val != val:  # NaN (휴장 등)
                continue
            obj.actual_open = float(val)
            obj.error_pct = (obj.estimated_open - obj.actual_open) / obj.actual_open
            updated += 1
        s.commit()

    log.info("실제값 기록 완료: %d행", updated)
    return updated


def accrue_intraday_cache() -> dict[str, int]:
    """인트라데이 시간봉 캐시를 1회 적립한다(개선점 #6 — 커버리지 누적).

    yfinance 시간봉 730일 한계로 과거가 지워지므로 매일 DB(intraday_bars)에
    박제해야 학습 커버리지가 오른다. 멱등이라 중복 실행은 무해하다.
    """
    from experiments.intraday_snapshot import accrue

    return accrue()
