"""KRX 투자자별 순매수(외국인/기관) 수집 + 캐시.

pykrx 1.2.8부터 투자자별 매매 엔드포인트는 data.krx.co.kr 로그인 세션이 필요하다
(무로그인 호출은 400 "LOGOUT" 반환 — 2026-06-11 확인). 무료 회원가입 후 환경변수
KRX_ID / KRX_PW (또는 프로젝트 .env)에 넣으면 자동 로그인된다.

⚠️ KRX_PW는 data.krx.co.kr **웹사이트 로그인 비밀번호**다. Open API 인증키(40자리
16진수)가 아니다. 비밀번호가 틀린 채 반복 실행하면 KRX가 계정을 잠근다(CD007).
`import pykrx` 자체가 로그인을 시도하고 요청마다 실패를 재시도하므로, 이 모듈은
pykrx를 import하기 *전에* 로그인을 딱 1회 직접 검증하고 실패 시 즉시 중단한다.

  외국인 순매수(★, SPEC §3) = 전일 장마감 후 확정 → 익일 09:00 갭 예측에 lag로 사용 가능.

캐시: data/krx_supply_{code}.csv 에 누적 저장(KRX는 느리고 세션 제한이 있어 재수집 회피).

단독 점검:  python -m experiments.krx_supply
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd

from backend.series_store import load_frame, upsert_frame

# .env 로드 (config.py와 동일 동작 — 추가 의존 없이 best-effort)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except Exception:
    pass

SOURCE = "krx_supply"

# 종목코드(숫자) — yfinance 티커가 아니라 KRX 6자리
KR_CODES = {"삼성전자": "005930", "SK하이닉스": "000660"}


def has_credentials() -> bool:
    return bool(os.getenv("KRX_ID") and os.getenv("KRX_PW"))


# data.krx.co.kr 로그인 (pykrx auth.py와 동일 흐름 — pykrx import 부작용 없이 검증용)
_LOGIN_PAGE = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001.cmd"
_LOGIN_JSP = "https://data.krx.co.kr/contents/MDC/COMS/client/view/login.jsp?site=mdc"
_LOGIN_URL = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001D1.cmd"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

_login_ok: bool | None = None  # 프로세스당 1회만 검증
_session = None  # 로그인된 requests.Session (getJsonData 직접 호출용)


def login_session():
    """data.krx.co.kr 로그인된 requests.Session 반환 (실패 시 None).

    pykrx import *전에* 프로세스당 딱 1회만 로그인을 시도한다. 실패가 반복되면
    KRX가 계정을 잠그므로(CD007 — 실제 발생 사례), 실패 시 재시도 없이 원인별
    안내를 출력하고 이후 호출은 즉시 None을 반환한다.
    """
    global _login_ok, _session
    if _login_ok is not None:
        return _session
    import requests

    s = requests.Session()
    try:
        s.get(_LOGIN_PAGE, headers={"User-Agent": _UA}, timeout=15)
        s.get(_LOGIN_JSP, headers={"User-Agent": _UA, "Referer": _LOGIN_PAGE}, timeout=15)
        payload = {"mbrNm": "", "telNo": "", "di": "", "certType": "",
                   "mbrId": os.getenv("KRX_ID"), "pw": os.getenv("KRX_PW")}
        res = s.post(_LOGIN_URL, data=payload,
                     headers={"User-Agent": _UA, "Referer": _LOGIN_PAGE}, timeout=15).json()
        if res.get("_error_code") == "CD011":  # 중복 로그인 → skipDup 재전송
            payload["skipDup"] = "Y"
            res = s.post(_LOGIN_URL, data=payload,
                         headers={"User-Agent": _UA, "Referer": _LOGIN_PAGE}, timeout=15).json()
    except (requests.RequestException, ValueError) as e:
        print(f"KRX 로그인 검증 불가(네트워크/응답 오류): {e}")
        _login_ok = False
        return None

    code = res.get("_error_code", "")
    _login_ok = code == "CD001"
    if _login_ok:
        _session = s
    else:
        print(f"KRX 로그인 실패 [{code}] {res.get('_error_message', '')}")
        if code == "CD007":
            print("  → 비밀번호 오류 누적으로 계정이 잠겼습니다."
                  " data.krx.co.kr '비밀번호 찾기'로 재설정해 잠금을 해제하세요.")
        print("  → KRX_PW에는 data.krx.co.kr 웹사이트 로그인 비밀번호를 넣어야 합니다"
              " (Open API 인증키 아님). 수정 전까지 KRX 수급 피처는 스킵됩니다.")
    return _session


def verify_login() -> bool:
    return login_session() is not None


def _pick_col(df: pd.DataFrame, keyword: str) -> str | None:
    """'외국인'·'기관' 등 키워드를 포함하는 순매수 컬럼명을 찾는다(버전별 명칭 차이 대응)."""
    for c in df.columns:
        if keyword in str(c):
            return c
    return None


def fetch_supply(code: str, start: str, end: str) -> pd.DataFrame:
    """투자자별 순매수(원). 반환 index=날짜, columns=[frgn_net, inst_net].

    start/end: 'YYYYMMDD'. 자격증명 없으면 빈 DataFrame.
    """
    if not has_credentials() or not verify_login():
        return pd.DataFrame()
    from pykrx import stock  # 로그인은 첫 호출 시 자동(get_auth_session)

    df = stock.get_market_trading_value_by_date(start, end, code)
    if df is None or df.empty:
        return pd.DataFrame()
    out = pd.DataFrame(index=pd.to_datetime(df.index))
    fcol = _pick_col(df, "외국인")
    icol = _pick_col(df, "기관")
    if fcol:
        out["frgn_net"] = df[fcol].to_numpy()
    if icol:
        out["inst_net"] = df[icol].to_numpy()
    return out.sort_index()


def load_supply(name: str, start: str, end: str, refresh: bool = False) -> pd.DataFrame:
    """캐시 우선 로드. 없거나 refresh면 KRX에서 받아 DB에 저장."""
    code = KR_CODES[name]
    cached = load_frame(SOURCE, entity=code)
    if not refresh and not cached.empty:
        # 캐시가 요청 범위를 덮으면 그대로 사용
        s, e = pd.Timestamp(start), pd.Timestamp(end)
        if cached.index.min() <= s and cached.index.max() >= e:
            return cached.loc[s:e]
    fresh = fetch_supply(code, start.replace("-", ""), end.replace("-", ""))
    if fresh.empty:
        return cached  # 수집 실패 시 가진 캐시라도 반환
    upsert_frame(SOURCE, fresh, entity=code)
    merged = (pd.concat([cached, fresh]) if not cached.empty else fresh)
    return merged[~merged.index.duplicated(keep="last")].sort_index()


def main():
    print("KRX 자격증명:", "있음" if has_credentials() else "없음 (KRX_ID/KRX_PW 미설정)")
    if not has_credentials():
        print("→ data.krx.co.kr 무료 가입 후 .env 에 KRX_ID/KRX_PW 설정하세요.")
        return
    if not verify_login():
        return
    print("KRX 로그인 확인 — 수집 시작")
    for name in KR_CODES:
        df = load_supply(name, "2017-01-01", "2026-06-10", refresh=True)
        print(f"\n[{name}] rows={len(df)} cols={list(df.columns)}")
        if not df.empty:
            print(df.tail(3).to_string())


if __name__ == "__main__":
    main()
