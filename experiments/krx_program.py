"""KRX 프로그램매매(시장 단위, ○ 티어) 일별 수집 + 캐시.

KRX 통계 MDCSTAT026(프로그램매매 현황)은 조회 기간 *합산*만 반환한다 — 일별 변형
bld(02602~)는 존재하지 않음(2026-06-11 확인). 그래서 하루씩(strtDd=endDd) 조회해
일별 시계열을 만든다. 거래일 목록은 krx_supply 캐시(투자자별 순매수)의 날짜
인덱스를 재사용해 휴장일 호출을 피한다.

KRX는 시장 단위(KOSPI)만 제공 — 종목별 프로그램매매는 무료 공개 통계가 없다.
컬럼(순매수대금, 원): prog_arb_net(차익), prog_nonarb_net(비차익), prog_net(전체).
available_at: 장마감 후 확정 → 사용 측에서 +1 영업일 lag.

캐시: data/krx_program_STK.csv 누적. 재실행 시 빠진 날짜만 수집(중단 안전 —
250일마다 중간 저장). 로그인 필요(krx_supply.login_session 재사용, 1회 검증 규칙 동일).

단독 점검/백필:  python -m experiments.krx_program
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd

from experiments.krx_supply import _UA, KR_CODES, login_session

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DATA_DIR.mkdir(exist_ok=True)

GETJSON = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
HDR = {"User-Agent": _UA, "X-Requested-With": "XMLHttpRequest",
       "Referer": "https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd"}
ROW_KEY = {"차익": "prog_arb_net", "비차익": "prog_nonarb_net", "전체": "prog_net"}


def _trading_days(start: str, end: str) -> pd.DatetimeIndex:
    """krx_supply 캐시의 날짜 인덱스 = KRX 거래일 캘린더."""
    path = DATA_DIR / f"krx_supply_{KR_CODES['삼성전자']}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} 없음 — 먼저 `python -m experiments.krx_supply` 로 수급을 수집하세요.")
    idx = pd.read_csv(path, index_col=0, parse_dates=True).index
    return idx[(idx >= start) & (idx <= end)]


def _num(s: str | None) -> float:
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return float("nan")


def fetch_day(session, day: pd.Timestamp, mkt: str = "STK") -> dict | None:
    d = day.strftime("%Y%m%d")
    r = session.post(GETJSON, data={
        "bld": "dbms/MDC/STAT/standard/MDCSTAT02601", "locale": "ko_KR",
        "mktId": mkt, "strtDd": d, "endDd": d,
        "share": "1", "money": "1", "csvxls_isNo": "false"}, headers=HDR, timeout=30)
    try:
        rows = r.json().get("output", [])
    except ValueError:  # HTML(세션 만료 등)
        return None
    out = {}
    for row in rows:
        key = ROW_KEY.get(str(row.get("ITM_TP_NM", "")).strip())
        if key:
            out[key] = _num(row.get("NETBID_TRDVAL"))
    return out or None


def load_program(start: str, end: str, mkt: str = "STK") -> pd.DataFrame:
    """캐시 우선 로드. 빠진 거래일만 KRX에서 받아 누적 저장."""
    path = DATA_DIR / f"krx_program_{mkt}.csv"
    cached = pd.DataFrame()
    if path.exists():
        cached = pd.read_csv(path, index_col=0, parse_dates=True)
    days = _trading_days(start, end)
    missing = days.difference(cached.index)
    if len(missing) == 0:
        return cached.loc[days.min():days.max()]

    session = login_session()
    if session is None:
        return cached  # 로그인 불가 — 가진 캐시라도 반환

    print(f"프로그램매매 백필: 거래일 {len(days)}개 중 {len(missing)}개 수집…")
    got, t0 = {}, time.time()
    for i, day in enumerate(missing, 1):
        row = fetch_day(session, day, mkt)
        if row:
            got[day] = row
        time.sleep(0.05)
        if i % 250 == 0 or i == len(missing):
            cached = pd.concat([cached, pd.DataFrame.from_dict(got, orient="index")])
            cached = cached[~cached.index.duplicated(keep="last")].sort_index()
            cached.to_csv(path)
            got = {}
            rate = i / (time.time() - t0)
            print(f"  {i}/{len(missing)} ({rate:.1f}일/초, 누적 {len(cached)}일 저장)")
    return cached.loc[days.min():days.max()]


def main():
    df = load_program("2017-01-01", "2026-06-10")
    print(f"\n[프로그램매매 STK] rows={len(df)} cols={list(df.columns)}")
    if not df.empty:
        print(df.tail(3).to_string())
        # sanity: 전체 ≈ 차익 + 비차익
        gap = (df["prog_net"] - df["prog_arb_net"] - df["prog_nonarb_net"]).abs()
        print(f"  합산 검증(전체-차익-비차익): max|차이|={gap.max():,.0f}원")
        na = df.isna().any(axis=1).sum()
        print(f"  결측 거래일: {na}")


if __name__ == "__main__":
    main()
