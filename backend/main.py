"""FastAPI 백엔드.

기존 src/ 모듈(data_loader, features, model, predict)을 그대로 재사용해
REST API로 노출한다. 프론트엔드(React+Vite)가 이 API를 호출한다.

실행: python -m uvicorn backend.main:app --reload --port 8000
"""
from __future__ import annotations

import sys
from pathlib import Path

# 프로젝트 루트를 import 경로에 추가 (config, src 를 찾기 위함)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from backend import cache, queries  # noqa: E402
from backend.db import init_db  # noqa: E402
from backend.jobs import record_actuals, run_daily_prediction  # noqa: E402
from backend.scheduler import start_scheduler, stop_scheduler  # noqa: E402
from config import DRIVERS, TARGETS  # noqa: E402
from src.data_loader import fetch_latest_quote  # noqa: E402
from src.model import load, train  # noqa: E402


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()              # 테이블 생성(최초 1회)
    start_scheduler()      # 평일 예측/실제값 배치 시작
    yield
    stop_scheduler()


app = FastAPI(title="반도체 애프터마켓 예측 API", version="1.0", lifespan=lifespan)

# 개발 환경: Vite 개발 서버(5173)에서의 호출 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- 응답 스키마 --------------------------------------------------------
class Prediction(BaseModel):
    target: str
    target_date: str
    prediction_date: str
    last_close: float
    predicted_gap: float
    estimated_open: float
    change: float
    actual_open: float | None = None
    error_pct: float | None = None


class LiveDrivers(BaseModel):
    sox_ret: float | None
    fx_ret: float | None


class ModelStatus(BaseModel):
    target: str
    trained: bool


# --- 엔드포인트 ---------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/targets")
def targets() -> list[str]:
    return list(TARGETS)


@app.get("/api/model-status", response_model=list[ModelStatus])
def model_status() -> list[ModelStatus]:
    return [ModelStatus(target=n, trained=load(n) is not None) for n in TARGETS]


@app.get("/api/live-drivers", response_model=LiveDrivers)
def live_drivers() -> LiveDrivers:
    """현재(밤중) SOX·환율의 전일 종가 대비 수익률."""

    def ret(ticker: str) -> float | None:
        q = fetch_latest_quote(ticker)
        if q and q["previous_close"]:
            return q["last_price"] / q["previous_close"] - 1.0
        return None

    return LiveDrivers(sox_ret=ret(DRIVERS["SOX"]), fx_ret=ret(DRIVERS["USDKRW"]))


@app.get("/api/predict", response_model=list[Prediction])
def predict() -> list[Prediction]:
    """오늘자(최신) 예측을 DB에서 반환.

    예측은 매일 배치(스케줄러)가 생성한다. 아직 없으면 즉시 1회 생성한다.
    """
    rows = queries.latest_predictions()
    if not rows:
        # 콜드 스타트: 배치가 아직 안 돈 경우 즉석 생성
        run_daily_prediction()
        rows = queries.latest_predictions()
    return [Prediction(**r) for r in rows]


@app.get("/api/predictions/history", response_model=list[Prediction])
def predictions_history(
    target: str | None = Query(None, description="종목명 필터 (예: 삼성전자)"),
    limit: int = Query(60, ge=1, le=500),
) -> list[Prediction]:
    """과거 예측 이력(최신순) — 실제값/오차 포함. 적중 기록 화면용."""
    if target and target not in TARGETS:
        raise HTTPException(status_code=404, detail=f"알 수 없는 종목: {target}")
    return [Prediction(**r) for r in queries.prediction_history(target, limit)]


@app.get("/api/accuracy")
def accuracy() -> list[dict]:
    """종목별 적중 통계(MAE, 방향 적중률)."""
    return queries.accuracy_stats()


@app.post("/api/run-prediction")
def run_prediction(force: bool = Query(False)) -> dict:
    """예측 배치를 수동 트리거(관리용)."""
    saved = run_daily_prediction(force=force)
    return {"saved": saved}


@app.post("/api/record-actuals")
def record_actuals_endpoint() -> dict:
    """실제 시초가 기록을 수동 트리거(관리용)."""
    return {"updated": record_actuals()}


@app.get("/api/history/{target}")
def history(
    target: str,
    window: int = Query(120, ge=20, le=1000),
) -> dict:
    """캔들 차트 + SOX 동조화용 시계열 데이터."""
    if target not in TARGETS:
        raise HTTPException(status_code=404, detail=f"알 수 없는 종목: {target}")

    data = cache.get_history().tail(window)
    idx = [d.strftime("%Y-%m-%d") for d in data.index]

    def col(name: str) -> list:
        return [None if v != v else float(v) for v in data[name]]  # NaN -> None

    # SOX 동조화: 종목/지수를 기준=100으로 정규화
    stock_close = data[f"{target}_Close"]
    sox_close = data["SOX_Close"]
    base_stock = stock_close.dropna().iloc[0]
    base_sox = sox_close.dropna().iloc[0]

    return {
        "dates": idx,
        "open": col(f"{target}_Open"),
        "high": col(f"{target}_High"),
        "low": col(f"{target}_Low"),
        "close": col(f"{target}_Close"),
        "norm_stock": [None if v != v else float(v / base_stock * 100) for v in stock_close],
        "norm_sox": [None if v != v else float(v / base_sox * 100) for v in sox_close],
    }


@app.post("/api/train")
def train_models() -> list[dict]:
    """두 종목 모델을 재학습하고 평가지표를 반환."""
    data = cache.get_history(force=True)
    return [train(n, data) for n in TARGETS]


@app.post("/api/refresh")
def refresh() -> dict:
    """시세 캐시를 비워 다음 요청에서 새로 받게 한다."""
    cache.clear()
    return {"status": "refreshed"}
