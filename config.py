"""프로젝트 전역 설정.

티커, 경로, 모델 하이퍼파라미터 등 한 곳에서 관리한다.
"""
from __future__ import annotations

import os
from pathlib import Path

# --- 경로 ---------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
MODEL_DIR = ROOT / "models"
DATA_DIR.mkdir(exist_ok=True)
MODEL_DIR.mkdir(exist_ok=True)

# .env 가 있으면 환경변수로 로드 (없으면 무시)
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

# --- 데이터베이스 -------------------------------------------------------
# prod: PostgreSQL 연결 문자열을 환경변수로 주입
#   예) postgresql+psycopg://user:pass@host:5432/dbname
# 미설정 시 로컬 개발용 SQLite 파일로 폴백 → 별도 설치 없이 바로 실행 가능
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'app.db'}")

# --- 스케줄러 (예측 배치) ----------------------------------------------
TIMEZONE = os.getenv("TZ", "Asia/Seoul")
# 개장 전 예측 생성 시각 (KST)
PREDICT_HOUR = int(os.getenv("PREDICT_HOUR", "8"))
PREDICT_MINUTE = int(os.getenv("PREDICT_MINUTE", "0"))
# 개장 후 실제 시초가 기록 시각 (KST)
ACTUAL_HOUR = int(os.getenv("ACTUAL_HOUR", "9"))
ACTUAL_MINUTE = int(os.getenv("ACTUAL_MINUTE", "10"))
# 인트라데이 시간봉 캐시 적립 시각 (KST) — 08:00 스냅샷 봉 게시 직후
INTRADAY_ACCRUE_HOUR = int(os.getenv("INTRADAY_ACCRUE_HOUR", "8"))
INTRADAY_ACCRUE_MINUTE = int(os.getenv("INTRADAY_ACCRUE_MINUTE", "10"))

# --- 티커 ---------------------------------------------------------------
# 예측 대상: 한국 반도체 대형주
TARGETS: dict[str, str] = {
    "삼성전자": "005930.KS",
    "SK하이닉스": "000660.KS",
}

# 설명 변수(드라이버): 미국 반도체지수 + 원/달러 환율
DRIVERS: dict[str, str] = {
    "SOX": "^SOX",     # 필라델피아 반도체지수
    "USDKRW": "KRW=X",  # 원/달러 환율
}

ALL_TICKERS: dict[str, str] = {**DRIVERS, **TARGETS}

# --- 학습 설정 ----------------------------------------------------------
HISTORY_PERIOD = "5y"      # 학습에 사용할 과거 데이터 기간
LAGS = [1, 2]              # 사용할 과거 시차(일)
RANDOM_STATE = 42
