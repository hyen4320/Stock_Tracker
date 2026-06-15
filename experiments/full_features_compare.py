"""★-only vs 풀 피처(◆ 티어 확장) 성능 비교 — 스펙 §10 8단계 (★ 기록 → ◆ 추가 → 재평가).

improvements_compare.py 의 최적 설정(잔차 타깃 #2, rolling β 기준 #8, raw 타깃 #4,
4×126일 롤링 홀드아웃 #5, DM/bootstrap 검정 #1)을 고정하고 피처 셋만 토글한다.

  ★ 잔차          improvements_compare 의 "LGBM 잔차 타깃" (자기시계열 + 美 핵심)
  ★+수급 잔차      + 외국인/기관 순매수 (#9)
  풀 피처 잔차      + ◆ 티어 전체 (아래)
  풀+신용/프로그램   + ○ 티어: KRX 프로그램매매(시장, +1 lag), 금투협 신용잔고 증감·
                  미수금·반대매매(시장, +2 lag) — krx_program.py / kofia_credit.py

추가된 ◆ 피처
  美 개별주 확장    AMD, MRVL / 장비군(ASML·AMAT·LRCX·KLAC) 평균 인덱스 / SNDK(하이닉스
                  특화, 2025-02 상장이라 이전 구간 NaN — LGBM 네이티브 처리)
  상대강도         (MU − SOX) 밤사이 log return 차
  금리            美 10년물 DGS10 일변화 (FRED fredgraph CSV, 무인증)
  한국 시장        KOSPI(^KS11) 전일 수익률, 거래대금/20일MA 비율
  기술지표         MA5/20/60 괴리, RSI14, MACD(+히스토그램), 볼린저 %B, 실현변동성 20d
                  (전부 D-1 까지만 — shift(1))
  캘린더          요일, 월, 둘째 목요일(옵션만기), 네 마녀(분기 만기), 직전 거래일 간격

스펙에 있지만 여전히 미적용: KOSPI200 야간선물(무료 소스 없음), 실적발표 더미(무료
캘린더 없음), *종목별* 신용잔고·프로그램매매(시장 단위만 무료 공개), 키오시아 6600.T(○).

핵심 검정: 풀 피처가 ★+수급 대비, 풀+○ 가 풀 대비 *추가로* 유의한가
(pairwise DM + bootstrap CI).

실행:  python -m experiments.full_features_compare
"""
from __future__ import annotations

import io
import sys
import warnings

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from experiments.improvements_compare import (
    BETA_MIN, BETA_WIN, COSTS_BP, FLOW_COLS, N_WINDOWS, WIN_LEN,
    block_bootstrap_ci, dm_test, fetch_naver_flows, fit_lgbm, flow_features,
    make_lgbm, rolling_beta,
)
from experiments.spec_compare import (
    COND_THR, EMBARGO, KR, START, US_COMMON, US_SPECIFIC, WINSOR,
    _flatten, assemble, metrics, self_features, us_overnight, winsorize_train,
)
from experiments.kofia_credit import load_kofia
from experiments.krx_program import load_program

warnings.simplefilter("ignore")

US_EXTRA = ["AMD", "MRVL"]                      # ◆ 개별주
US_EQUIP = ["ASML", "AMAT", "LRCX", "KLAC"]     # ◆ 장비군 → 인덱스화
US_SPECIFIC_FULL = {"삼성전자": [], "SK하이닉스": ["SNDK"]}  # ◆ 특화 추가분
KOSPI_TK = "^KS11"

TECH_COLS = ["ma5_dev", "ma20_dev", "ma60_dev", "rsi14", "macd", "macd_hist",
             "boll_b", "rvol20", "value_ratio"]
CAL_COLS = ["dow", "month", "expiry_thu", "witching", "gap_days"]
MACRO_COLS = ["EQUIP_on", "rs_mu_sox", "DGS10_chg", "kospi_ret_prev"]
# ○ 티어: 시장 단위 신용/프로그램 (available_at — 프로그램 +1, 신용/증시자금 +2 영업일)
CREDIT_COLS = ["prog_net_prev", "prog_net_5d", "credit_chg_5d",
               "banda_ratio_prev", "misu_chg_5d"]


# ──────────────────────────────── 데이터 ────────────────────────────────

def fetch_all():
    us_list = sorted(set(US_COMMON + sum(US_SPECIFIC.values(), [])
                         + US_EXTRA + US_EQUIP + sum(US_SPECIFIC_FULL.values(), [])))
    us = yf.download(us_list, start=START, auto_adjust=True, progress=False)["Close"]
    us = us.dropna(how="all")
    kospi = _flatten(yf.download(KOSPI_TK, start=START, auto_adjust=True,
                                 progress=False))["Close"].dropna()
    kr = {}
    for name, tk in KR.items():
        d = _flatten(yf.download(tk, start=START, auto_adjust=False, progress=False))
        kr[name] = d[["Open", "High", "Low", "Close", "Volume"]].dropna(how="all")
    return us, kr, kospi


def fetch_dgs10() -> pd.Series:
    """美 10년물. FRED fredgraph CSV(무인증) 우선, 실패 시 yfinance ^TNX 폴백."""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10&cosd={START}"
    for _ in range(2):
        try:
            raw = requests.get(url, timeout=60).text
            df = pd.read_csv(io.StringIO(raw))
            df.columns = ["date", "DGS10"]
            df["date"] = pd.to_datetime(df["date"])
            s = pd.to_numeric(df.set_index("date")["DGS10"], errors="coerce")
            return s.dropna()
        except requests.RequestException:
            continue
    print("  FRED 접속 실패 → yfinance ^TNX 폴백 (동일 美 10년물 수익률)")
    tnx = _flatten(yf.download("^TNX", start=START, auto_adjust=False,
                               progress=False))["Close"].dropna()
    return tnx.rename("DGS10")


def extend_us_lr(us_lr: pd.DataFrame, dgs10: pd.Series) -> pd.DataFrame:
    """美 밤사이 수익률 프레임에 ◆ 매크로 파생 컬럼 추가."""
    out = us_lr.copy()
    out["EQUIP_on"] = out[[f"{t}_on" for t in US_EQUIP]].mean(axis=1)
    out["rs_mu_sox"] = out["MU_on"] - out["^SOX_on"]
    out = out.join(dgs10.diff().rename("DGS10_chg"))
    return out


def tech_features(d: pd.DataFrame) -> pd.DataFrame:
    """기술지표 ◆ — 전부 과거 윈도우만, shift(1) 로 D-1 까지 확정값."""
    c, v = d["Close"], d["Volume"]
    ret = np.log(c / c.shift(1))
    ma5, ma20, ma60 = c.rolling(5).mean(), c.rolling(20).mean(), c.rolling(60).mean()
    delta = c.diff()
    up = delta.clip(lower=0).rolling(14).mean()
    dn = (-delta.clip(upper=0)).rolling(14).mean()
    rsi = 100 * up / (up + dn)
    ema12, ema26 = c.ewm(span=12).mean(), c.ewm(span=26).mean()
    macd = (ema12 - ema26) / c
    hist = macd - macd.ewm(span=9).mean()
    boll = (c - ma20) / (2 * c.rolling(20).std())
    value = c * v
    f = pd.DataFrame({
        "ma5_dev": c / ma5 - 1, "ma20_dev": c / ma20 - 1, "ma60_dev": c / ma60 - 1,
        "rsi14": rsi, "macd": macd, "macd_hist": hist, "boll_b": boll,
        "rvol20": ret.rolling(20).std(),
        "value_ratio": value / value.rolling(20).mean(),
    })
    return f.shift(1)


def credit_program_features(idx: pd.DatetimeIndex) -> pd.DataFrame:
    """○ 티어 — 시장 단위 프로그램매매·신용잔고·미수/반대매매.

    lag: 프로그램매매는 장마감 후 확정 → shift(1). 신용잔고·증시자금은 공시 지연을
    반영해 shift(2) (스펙 §시점 규약 'T+2 보수'). 시계열 캘린더 차이는 reindex+ffill.
    """
    start, end = START, str(idx.max().date())
    prog = load_program(start, end)["prog_net"].reindex(idx)
    credit = load_kofia("credit", start, end)["credit_loan_kospi"].reindex(idx).ffill()
    funds = load_kofia("funds", start, end).reindex(idx).ffill()
    return pd.DataFrame({
        "prog_net_prev": prog.shift(1),
        "prog_net_5d": prog.rolling(5).sum().shift(1),
        "credit_chg_5d": np.log(credit / credit.shift(5)).shift(2),
        "banda_ratio_prev": funds["banda_ratio"].shift(2),
        "misu_chg_5d": (funds["misu"] / funds["misu"].shift(5) - 1).shift(2),
    }, index=idx)


def calendar_features(idx: pd.DatetimeIndex) -> pd.DataFrame:
    """캘린더 ◆ — 예측일 D 의 사전 확정 속성 (shift 불필요)."""
    dow = idx.dayofweek
    second_thu = (dow == 3) & (idx.day >= 8) & (idx.day <= 14)
    return pd.DataFrame({
        "dow": dow, "month": idx.month,
        "expiry_thu": second_thu.astype(int),
        "witching": (second_thu & idx.month.isin([3, 6, 9, 12])).astype(int),
        "gap_days": idx.to_series().diff().dt.days.fillna(1).to_numpy(),
    }, index=idx)


def build_dataset(name, d, other_close, us_lr_ext, flows, kospi):
    star_us = [f"{t}_on" for t in US_COMMON + US_SPECIFIC[name]]
    extra_us = ([f"{t}_on" for t in US_EXTRA + US_SPECIFIC_FULL[name]]
                + ["EQUIP_on", "rs_mu_sox", "DGS10_chg"])
    ds = assemble(name, d, other_close, us_lr_ext, star_us + extra_us, exact=False)
    ds = ds.join(flow_features(flows))
    ds = ds.join(tech_features(d))
    ds = ds.join(np.log(kospi / kospi.shift(1)).shift(1).rename("kospi_ret_prev"))
    ds = ds.join(calendar_features(ds.index))
    ds = ds.join(credit_program_features(ds.index))

    star_cols = list(self_features(d, other_close).columns) + star_us
    full_cols = star_cols + FLOW_COLS + extra_us[:-1] + ["DGS10_chg",
                                                         "kospi_ret_prev"] + TECH_COLS + CAL_COLS
    # 중복 제거(순서 유지)
    full_cols = list(dict.fromkeys(full_cols))
    ds = ds.dropna(subset=star_cols)   # ★만 필수 — ◆ 결측(SNDK 등)은 LGBM 네이티브 처리
    return ds, star_cols, full_cols


# ──────────────────────────────── 실험 ────────────────────────────────

def run_stock(name, ds, star_cols, full_cols):
    y, sox = ds["y"], ds["^SOX_on"]
    beta = rolling_beta(y, sox)
    ok = beta.notna()
    ds, y, sox, beta = ds[ok], y[ok], sox[ok], beta[ok]
    n = len(ds)
    y_np = y.to_numpy()
    pred_roll = (beta * sox).to_numpy()
    resid_np = y_np - pred_roll

    sets = {
        "★ 잔차": star_cols,
        "★+수급 잔차": star_cols + FLOW_COLS,
        "풀 피처 잔차": full_cols,
        "풀+신용/프로그램": full_cols + CREDIT_COLS,
    }
    oos_start = n - N_WINDOWS * WIN_LEN
    collected = {"y": [], "rollβ": []}
    perwin = {k: [] for k in sets}
    last_model = None

    for w in range(N_WINDOWS):
        t0 = oos_start + w * WIN_LEN
        t1 = t0 + WIN_LEN
        dev, te = slice(0, t0 - EMBARGO), slice(t0, t1)
        collected["y"].append(y_np[te])
        collected["rollβ"].append(pred_roll[te])
        for k, cols in sets.items():
            X = ds[cols].to_numpy(dtype=float)
            m = fit_lgbm(make_lgbm(None), X[dev],
                         winsorize_train(resid_np[dev], WINSOR))
            p = pred_roll[te] + m.predict(X[te])
            collected.setdefault(k, []).append(p)
            perwin[k].append(metrics(y_np[te], p)["rmse"])
            if k == "풀+신용/프로그램" and w == N_WINDOWS - 1:
                last_model = (m, sets[k])

    out = {k: np.concatenate(v) for k, v in collected.items()}
    return out, perwin, last_model


def report(name, out, perwin, last_model, n_feats):
    y = out["y"]
    e_roll = out["rollβ"] - y
    print(f"\n{'='*100}\n  {name} — ★({n_feats['★ 잔차']}개) vs 풀({n_feats['풀 피처 잔차']}개)"
          f" vs 풀+○({n_feats['풀+신용/프로그램']}개)"
          f" | 잔차 타깃, 롤링 홀드아웃 {N_WINDOWS}×{WIN_LEN}일\n{'='*100}")
    print(f"  {'구성':<16}{'RMSE':>9}{'MAE':>9}{'방향':>8}{'조건부':>12}"
          f"{'DM p(vs β)':>11}{'ΔRMSE 95% CI':>22}{'윈도RMSE':>22}")
    print("  " + "-" * 96)
    m = metrics(y, out["rollβ"])
    print(f"  {'rolling β·SOX':<16}{m['rmse']*100:8.4f}%{m['mae']*100:8.4f}%"
          f"{m['hit']*100:7.1f}%{m['condhit']*100:6.1f}%({m['condn']}){'—':>11}{'—':>22}{'—':>22}")
    for k in ["★ 잔차", "★+수급 잔차", "풀 피처 잔차", "풀+신용/프로그램"]:
        mm = metrics(y, out[k])
        e = out[k] - y
        _, p = dm_test(e, e_roll)
        lo, hi = block_bootstrap_ci(e, e_roll)
        pw = "/".join(f"{r*100:.2f}" for r in perwin[k])
        print(f"  {k:<16}{mm['rmse']*100:8.4f}%{mm['mae']*100:8.4f}%{mm['hit']*100:7.1f}%"
              f"{mm['condhit']*100:6.1f}%({mm['condn']}){p:>11.3f}"
              f"{f'[{lo*100:+.3f}, {hi*100:+.3f}]':>22}{pw:>22}")
    print("  " + "-" * 96)

    # 핵심 검정: ◆/○ 의 한계 기여 (pairwise)
    def marginal(tag, k_new, k_base):
        e_new, e_base = out[k_new] - y, out[k_base] - y
        _, p = dm_test(e_new, e_base)
        lo, hi = block_bootstrap_ci(e_new, e_base)
        verdict = "유의한 개선" if (p == p and p < 0.05 and hi < 0) else \
                  ("유의한 악화" if (p == p and p < 0.05 and lo > 0) else "구분 불가(0 포함)")
        print(f"  {tag} 한계 기여 검정 ({k_new} − {k_base}):  DM p={p:.3f},"
              f" ΔRMSE 95% CI [{lo*100:+.3f}, {hi*100:+.3f}] %p → {verdict}")

    marginal("◆", "풀 피처 잔차", "★+수급 잔차")
    marginal("○", "풀+신용/프로그램", "풀 피처 잔차")

    # P&L (#7 상한 추정)
    print(f"\n  경제적 가치 — |예측|>{COND_THR*100:.1f}% 진입, 롱+숏 (상한 추정)")
    print(f"   {'구성':<16}{'거래':>6}{'적중':>8}" + "".join(f"{f'순수익@{c}bp':>14}" for c in COSTS_BP))
    for k in ["rollβ", "★ 잔차", "★+수급 잔차", "풀 피처 잔차", "풀+신용/프로그램"]:
        pr = out[k]
        msk = np.abs(pr) > COND_THR
        gross = np.sign(pr[msk]) * y[msk]
        cells = "".join(f"{(gross - c/1e4).sum()*100:+9.1f}%p     " for c in COSTS_BP)
        print(f"   {k:<16}{int(msk.sum()):>6}{np.mean(gross>0)*100:>7.1f}%{cells}")

    # 풀 모델 피처 중요도 (마지막 윈도, gain)
    m, cols = last_model
    imp = pd.Series(m.booster_.feature_importance("gain"), index=cols)
    imp = imp.sort_values(ascending=False).head(12)
    tot = m.booster_.feature_importance("gain").sum()
    print(f"\n  풀 모델 피처 중요도 top12 (gain, 마지막 윈도): "
          + ", ".join(f"{c}({v/tot*100:.0f}%)" for c, v in imp.items()))


def main():
    print("데이터 수집 중(yfinance + FRED + 네이버 수급)…")
    us, kr, kospi = fetch_all()
    us_lr_ext = extend_us_lr(us_overnight(us), fetch_dgs10())
    names = list(KR)
    closes = {nm: kr[nm]["Close"] for nm in names}
    flows = {nm: fetch_naver_flows(KR[nm].split(".")[0]) for nm in names}

    for i, name in enumerate(names):
        ds, star_cols, full_cols = build_dataset(
            name, kr[name], closes[names[1 - i]], us_lr_ext, flows[name], kospi)
        out, perwin, last_model = run_stock(name, ds, star_cols, full_cols)
        n_feats = {"★ 잔차": len(star_cols), "풀 피처 잔차": len(full_cols),
                   "풀+신용/프로그램": len(full_cols) + len(CREDIT_COLS)}
        report(name, out, perwin, last_model, n_feats)

    print("\n⚠️ 통계 모델 비교 실험이며 투자 권유가 아님. 백테스트 성과는 실거래를 보장하지 않음.")


if __name__ == "__main__":
    main()
