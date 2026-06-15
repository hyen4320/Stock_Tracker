"""금투협 freesis 신용공여 잔고·증시자금(미수/반대매매) 수집 + 캐시 (○ 티어).

KRX 정보데이터시스템에는 신용거래잔고 통계가 없다(통계 화면의 "신용"은 전부 채권
신용등급 — 2026-06-11 전 화면 스캔으로 확인). 스펙 데이터소스 표대로 금투협
freesis(freesis.kofia.or.kr)를 쓴다. 무인증 JSON 엔드포인트라 로그인이 필요 없다.

  STATSCU0100000070BO  신용공여 잔고 추이 (단위 억원)
    TMPV2 신용거래융자 전체 = TMPV3 유가 + TMPV4 코스닥 (합산 검증됨)
    TMPV5 신용거래대주 전체 = TMPV6 유가 + TMPV7 코스닥
    TMPV9 예탁증권담보융자
  STATSCU0100000060BO  증시자금 추이 (단위 억원)
    TMPV2 투자자예탁금, TMPV5 위탁매매 미수금, TMPV6 반대매매금액,
    TMPV7 미수금 대비 반대매매 비중(%)

종목별 신용잔고는 무료 소스가 없어 시장 단위만 수집한다 — 스펙 ○ 티어의
"신용잔고 증감률"(시장)과 "시장 전체 반대매매·미수 금액"(risk-off 대리)에 해당.
available_at: 공시 지연을 반영해 사용 측에서 +2 영업일 lag(스펙 §시점 규약).

단독 점검:  python -m experiments.kofia_credit
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd
import requests

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DATA_DIR.mkdir(exist_ok=True)

URL = "https://freesis.kofia.or.kr/meta/getMetaDataList.do"
HDR = {"User-Agent": "Mozilla/5.0", "Referer": "https://freesis.kofia.or.kr/"}

SERVICES = {
    "credit": ("STATSCU0100000070BO", {
        "TMPV2": "credit_loan", "TMPV3": "credit_loan_kospi",
        "TMPV4": "credit_loan_kosdaq", "TMPV5": "credit_short", "TMPV9": "pledge_loan"}),
    "funds": ("STATSCU0100000060BO", {
        "TMPV2": "deposit", "TMPV5": "misu", "TMPV6": "banda", "TMPV7": "banda_ratio"}),
}


def fetch_kofia(kind: str, start: str, end: str) -> pd.DataFrame:
    """freesis 일별 통계. start/end='YYYY-MM-DD'. index=날짜(오름차순)."""
    obj, colmap = SERVICES[kind]
    body = {"dmSearch": {"tmpV40": "1000000000", "tmpV41": "1", "tmpV1": "D",
                         "tmpV45": start.replace("-", ""),
                         "tmpV46": end.replace("-", ""), "OBJ_NM": obj}}
    rows = requests.post(URL, json=body, headers=HDR, timeout=60).json().get("ds1", [])
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    out = pd.DataFrame({"date": pd.to_datetime(df["TMPV1"], format="%Y%m%d")})
    for src, dst in colmap.items():
        if src in df.columns:
            out[dst] = pd.to_numeric(df[src], errors="coerce")
    return out.set_index("date").sort_index()


def load_kofia(kind: str, start: str, end: str, refresh: bool = False) -> pd.DataFrame:
    """캐시 우선 로드. 캐시가 요청 범위를 못 덮으면 freesis에서 받아 병합 저장."""
    path = DATA_DIR / f"kofia_{kind}.csv"
    cached = pd.DataFrame()
    if path.exists() and not refresh:
        cached = pd.read_csv(path, index_col=0, parse_dates=True)
        s, e = pd.Timestamp(start), pd.Timestamp(end)
        # 말일은 영업일 공백을 감안해 5일 여유로 판정
        if not cached.empty and cached.index.min() <= s and cached.index.max() >= e - pd.Timedelta(days=5):
            return cached.loc[s:e]
    fresh = fetch_kofia(kind, start, end)
    if fresh.empty:
        return cached
    merged = pd.concat([cached, fresh]) if not cached.empty else fresh
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    merged.to_csv(path)
    return merged.loc[pd.Timestamp(start):pd.Timestamp(end)]


def main():
    for kind in SERVICES:
        df = load_kofia(kind, "2017-01-01", "2026-06-10")
        print(f"\n[{kind}] rows={len(df)} cols={list(df.columns)}")
        if not df.empty:
            print(df.tail(3).to_string())
        # sanity: 합산 관계
        if kind == "credit" and not df.empty:
            gap = (df["credit_loan"] - df["credit_loan_kospi"] - df["credit_loan_kosdaq"]).abs()
            print(f"  합산 검증(전체-유가-코스닥): max|차이|={gap.max():.1f}억")


if __name__ == "__main__":
    main()
