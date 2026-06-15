"""APScheduler 설정 (앱 내장 배치).

평일(월~금) KST 기준:
  - PREDICT_HOUR:PREDICT_MINUTE  → 개장 전 예측 생성
  - ACTUAL_HOUR:ACTUAL_MINUTE    → 개장 후 실제 시초가 기록
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.jobs import accrue_intraday_cache, record_actuals, run_daily_prediction
from config import (
    ACTUAL_HOUR,
    ACTUAL_MINUTE,
    INTRADAY_ACCRUE_HOUR,
    INTRADAY_ACCRUE_MINUTE,
    PREDICT_HOUR,
    PREDICT_MINUTE,
    TIMEZONE,
)

log = logging.getLogger("scheduler")
_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    sch = BackgroundScheduler(timezone=TIMEZONE)
    sch.add_job(
        run_daily_prediction,
        CronTrigger(
            day_of_week="mon-fri", hour=PREDICT_HOUR, minute=PREDICT_MINUTE
        ),
        id="daily_predict",
        replace_existing=True,
        misfire_grace_time=3600,  # 서버가 잠깐 죽었어도 1시간 내면 실행
    )
    sch.add_job(
        record_actuals,
        CronTrigger(
            day_of_week="mon-fri", hour=ACTUAL_HOUR, minute=ACTUAL_MINUTE
        ),
        id="record_actuals",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    sch.add_job(
        accrue_intraday_cache,
        CronTrigger(
            day_of_week="mon-fri",
            hour=INTRADAY_ACCRUE_HOUR,
            minute=INTRADAY_ACCRUE_MINUTE,
        ),
        id="accrue_intraday",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    sch.start()
    _scheduler = sch
    log.info(
        "스케줄러 시작: 예측 %02d:%02d, 실제값 %02d:%02d, 인트라데이 적립 %02d:%02d (%s)",
        PREDICT_HOUR,
        PREDICT_MINUTE,
        ACTUAL_HOUR,
        ACTUAL_MINUTE,
        INTRADAY_ACCRUE_HOUR,
        INTRADAY_ACCRUE_MINUTE,
        TIMEZONE,
    )
    return sch


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
