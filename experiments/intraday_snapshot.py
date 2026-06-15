"""인트라데이 08:00 KST 스냅샷 피처 — 개선점 #6 (β·SOX 너머의 유일한 큰 엣지 후보).

기존 일봉 피처는 전부 "美 정규장 마감(16:00 ET)까지"의 정보다. 진짜 추가 엣지가
있을 곳은 **美 마감 이후 ~ 한국 개장(09:00 KST) 직전 사이의 오버나잇 드리프트**
(야간선물·아시아 아침 반응)이고, 이 모듈이 그 구간을 yfinance 시간봉으로 잡는다.

  drift = ln( P[08:00 KST, 완결봉] / P[직전 美 영업일 16:00 ET, 완결봉] )
  대상: NQ=F(나스닥 선물), ES=F(S&P 선물), KRW=X(달러원)

시점 규약 (누수 차단):
- 스냅샷은 "그 시각까지 *완결*된 시간봉의 종가"만 쓴다. 시간봉은 봉 시작 시각으로
  라벨되므로, ts 시점 가격 = 종료시각(시작+1h) ≤ ts 인 마지막 봉의 종가.
  08:00 KST(=23:00 UTC) 스냅샷이 쓰는 마지막 봉은 22:00~23:00 UTC 봉 — 09:00 KST
  개장 정보가 섞일 수 없다. (08:59까지 쓰려면 분봉 필요 — 무료 소스는 60일 한계)
- 신선도 가드: 완결봉이 스냅샷보다 3시간 이상 오래되면 NaN. 월요일 아침은 선물이
  일요일 18:00 ET(=08:00 KST)에야 재개장하므로 자동으로 NaN — 주말 동안 새 정보가
  실제로 없으니 정직한 처리다(금요일 마감까지는 일봉 피처가 이미 안다).

캐시: data/intraday_{slug}.parquet 누적(UTC). yfinance는 시간봉을 730일까지만
보관하므로 **주기적으로 실행해 캐시를 늘려야 과거가 보존된다** (현재 시작점:
NQ/ES 2024-01-19, KRW 2023-08-25).

단독 점검:  python -m experiments.intraday_snapshot
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd
import yfinance as yf

log = logging.getLogger("intraday")

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DATA_DIR.mkdir(exist_ok=True)

TICKERS = {"NQ=F": "nq", "ES=F": "es", "KRW=X": "krw"}
INTRA_COLS = [f"{slug}_drift_0800" for slug in TICKERS.values()]
SNAP_KST_HOUR = 8          # 08:00 KST 스냅샷
US_CLOSE_ET_HOUR = 16      # 기준점: 美 현물 마감
STALE_LIMIT = pd.Timedelta(hours=3)


def load_hourly(tk: str) -> pd.Series:
    """시간봉 종가(UTC, 봉 *종료* 시각 인덱스). 캐시 + 신규분 병합."""
    path = DATA_DIR / f"intraday_{TICKERS[tk]}.parquet"
    cached = (pd.read_parquet(path).iloc[:, 0] if path.exists()
              else pd.Series(dtype=float))
    fresh = yf.download(tk, interval="1h", period="730d",
                        progress=False, auto_adjust=False)
    if not fresh.empty:
        close = fresh["Close"]
        if isinstance(close, pd.DataFrame):  # MultiIndex 컬럼
            close = close.iloc[:, 0]
        # 봉 시작 → 종료 시각으로 변환해 "완결 시점" 인덱스로 저장
        s = close.copy()
        s.index = s.index.tz_convert("UTC") + pd.Timedelta(hours=1)
        s = s.rename("close").dropna()
        cached = pd.concat([cached, s]) if not cached.empty else s
        cached = cached[~cached.index.duplicated(keep="last")].sort_index().rename("close")
        cached.to_frame().to_parquet(path)
    return cached


def _price_asof(close: pd.Series, ts: pd.Timestamp) -> float:
    """ts까지 완결된 마지막 봉의 종가. 신선도 가드 위반 시 NaN."""
    i = close.index.searchsorted(ts, side="right") - 1
    if i < 0 or ts - close.index[i] > STALE_LIMIT:
        return np.nan
    return float(close.iloc[i])


def _us_close_before(ts_utc: pd.Timestamp) -> pd.Timestamp:
    """ts 직전의 美 영업일 16:00 ET (UTC 반환). 주말은 금요일로 회귀."""
    et = ts_utc.tz_convert("America/New_York")
    cand = et.normalize() + pd.Timedelta(hours=US_CLOSE_ET_HOUR)
    if cand >= et:
        cand -= pd.Timedelta(days=1)
    while cand.weekday() >= 5:
        cand -= pd.Timedelta(days=1)
    return cand.tz_convert("UTC")


def intraday_features(kr_days: pd.DatetimeIndex) -> pd.DataFrame:
    """한국 거래일 D별 08:00 KST 드리프트. 커버리지 밖(시간봉 이전)은 NaN."""
    hourly = {slug: load_hourly(tk) for tk, slug in TICKERS.items()}
    out = pd.DataFrame(index=kr_days, columns=INTRA_COLS, dtype=float)
    for d in kr_days:
        t_snap = (d.tz_localize("Asia/Seoul")
                  + pd.Timedelta(hours=SNAP_KST_HOUR)).tz_convert("UTC")
        t_base = _us_close_before(t_snap)
        for slug, close in hourly.items():
            if close.empty or t_snap < close.index[0]:
                continue
            p1 = _price_asof(close, t_snap)
            # 기준점은 마감 직후 봉까지 허용(17:00 ET 봉 — 정산 직후), 가드는 동일
            p0 = _price_asof(close, t_base + pd.Timedelta(hours=1))
            if np.isfinite(p0) and np.isfinite(p1) and p0 > 0:
                out.at[d, f"{slug}_drift_0800"] = np.log(p1 / p0)
    return out


def accrue() -> dict[str, int]:
    """모든 티커의 시간봉 캐시를 1회 적립한다. 종목별 누적 봉 수를 반환(로깅용).

    yfinance 시간봉은 730일만 보관되므로 주기 호출로 과거를 parquet에 박제한다.
    적립은 멱등(dedup keep-last)이라 중복 실행은 무해하다. 한 티커가 실패해도
    나머지는 계속 진행한다(네트워크 일시 장애가 전체를 막지 않도록).
    """
    counts: dict[str, int] = {}
    for tk, slug in TICKERS.items():
        try:
            counts[slug] = len(load_hourly(tk))
        except Exception:
            log.exception("intraday 캐시 적립 실패: %s", tk)
    if counts:
        log.info("intraday 캐시 적립 완료: %s", counts)
    return counts


def main():
    days = pd.bdate_range("2023-09-01", pd.Timestamp.today()).normalize()
    f = intraday_features(days)
    print(f"영업일 {len(f)}일 기준 커버리지:")
    for c in INTRA_COLS:
        s = f[c].dropna()
        print(f"  {c}: {len(s)}일 ({s.index.min().date()} ~ {s.index.max().date()}),"
              f" std={s.std()*100:.3f}%, |drift|>0.3% 비율={np.mean(np.abs(s) > 0.003)*100:.1f}%")
    dow = f.notna().all(axis=1).groupby(days.dayofweek).mean()
    print("요일별 가용률(월~금):", [f"{v*100:.0f}%" for v in dow])
    print("\n최근 5일:")
    print((f.tail(5) * 100).round(3).to_string())


if __name__ == "__main__":
    main()
