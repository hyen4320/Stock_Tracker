"""v1 스펙 vs v2 스펙 성능 비교 하니스 (yfinance 전용, 추가 설치 0개).

두 스펙(docs/semiconductor_open_price_prediction_spec.md, _v2.md)은 *같은 알고리즘*
(그래디언트 부스팅)을 쓴다. 차이는 **누수 차단의 엄격함**이다. 따라서 이 스크립트는
모델·피처를 고정하고 v1(느슨)과 v2(엄격)의 규칙만 토글해, v1의 낙관적 CV 점수가
깨끗한 홀드아웃에서 얼마나 살아남는지를 측정한다.

토글되는 규칙
  정렬   v1: 같은 캘린더 날짜 join(allow_exact_matches=True) → 美 세션 D를 KR 개장 D에 붙임(룩어헤드)
         v2: available_at 기반 strict-backward(allow_exact_matches=False) → 직전 밤 美 세션(D-1)만 사용
  분할   v1: TimeSeriesSplit(gap=0), 홀드아웃 없음 → 전체 구간 CV 보고(낙관)
         v2: TimeSeriesSplit(gap=5)+ 최근 12개월 홀드아웃 격리(§6, §1-9)
  타깃   v1: raw
         v2: 학습 fold에서만 winsorize(1%/99%) (§5)
  평가   공통: y=0, beta*SOX 베이스라인과 비교(§7.1). 방향 적중률 + |예측|>임계 조건부 적중률(§8)

핵심 산출: v1 "CV 보고" vs v1 "홀드아웃 실제" vs v2 "홀드아웃" vs 베이스라인.

실행:  python -m experiments.spec_compare
"""
from __future__ import annotations

import sys
import warnings

try:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows cp949 콘솔에서 유니코드 출력
except Exception:
    pass

import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import TimeSeriesSplit

warnings.simplefilter("ignore")

START = "2017-01-01"
HOLDOUT_DAYS = 252           # 최근 ≈12개월 홀드아웃 (v2 §1-9)
EMBARGO = 5                  # 일 단위 embargo (v2 §6)
WINSOR = (0.01, 0.99)
COND_THR = 0.003             # 조건부 적중률 임계 |예측 갭| > 0.3%
RANDOM_STATE = 42

# 종목별 모델(옵션 A). 美 ★피처는 공통 + 종목 특화.
KR = {"삼성전자": "005930.KS", "SK하이닉스": "000660.KS"}
US_COMMON = ["^SOX", "MU", "NVDA", "AVGO", "^IXIC", "^GSPC", "^VIX",
             "NQ=F", "ES=F", "DX-Y.NYB", "KRW=X"]
US_SPECIFIC = {"삼성전자": ["TSM", "QCOM"], "SK하이닉스": []}  # TSM=삼성 파운드리 경쟁


def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    return df


def fetch():
    """KR OHLCV(종목별) + 美 종가 배치."""
    us_list = sorted(set(US_COMMON + sum(US_SPECIFIC.values(), [])))
    us = yf.download(us_list, start=START, auto_adjust=True, progress=False)["Close"]
    us = us.dropna(how="all")

    kr = {}
    for name, tk in KR.items():
        d = _flatten(yf.download(tk, start=START, auto_adjust=True, progress=False))
        kr[name] = d[["Open", "High", "Low", "Close", "Volume"]].dropna(how="all")
    return us, kr


def us_overnight(us: pd.DataFrame) -> pd.DataFrame:
    """美 종가 → 네이티브 캘린더에서 전일대비 log return(밤사이 수익률)."""
    lr = np.log(us / us.shift(1))
    lr.columns = [f"{c}_on" for c in lr.columns]
    return lr


def self_features(d: pd.DataFrame, other_close: pd.Series) -> pd.DataFrame:
    """KR 네이티브 캘린더에서 계산한 자기·교차 시계열 피처 (전부 D-1까지만)."""
    close, high, low, vol = d["Close"], d["High"], d["Low"], d["Volume"]
    ret = np.log(close / close.shift(1))
    gap = np.log(d["Open"] / close.shift(1))
    rng = (high - low) / close
    volz = (vol - vol.rolling(20).mean()) / vol.rolling(20).std()
    other_ret = np.log(other_close / other_close.shift(1)).reindex(close.index)

    f = pd.DataFrame({
        "self_ret_prev": ret.shift(1),
        "self_gap_prev": gap.shift(1),
        "self_range_prev": rng.shift(1),
        "self_volz_prev": volz.shift(1),
        "cross_ret_prev": other_ret.shift(1),
    })
    return f


def assemble(name, d, other_close, us_lr, us_cols, exact: bool):
    """타깃 + 피처 조립. exact=True → v1(룩어헤드 정렬), False → v2(밤사이 정렬)."""
    y = np.log(d["Open"] / d["Close"].shift(1)).rename("y")
    selfx = self_features(d, other_close)

    left = pd.concat([y, selfx], axis=1).reset_index()
    left.columns = ["date"] + list(left.columns[1:])
    right = us_lr[us_cols].reset_index()
    right.columns = ["date"] + us_cols
    left = left.sort_values("date")
    right = right.sort_values("date")

    merged = pd.merge_asof(left, right, on="date", direction="backward",
                           allow_exact_matches=exact)
    merged = merged.set_index("date").dropna(subset=["y"])
    return merged


def new_model():
    return HistGradientBoostingRegressor(
        max_iter=300, learning_rate=0.05, max_depth=3,
        l2_regularization=1.0, random_state=RANDOM_STATE,
    )


def metrics(y_true, y_pred):
    y_true = np.asarray(y_true, float)
    y_pred = np.asarray(y_pred, float)
    err = y_pred - y_true
    rmse = float(np.sqrt(np.mean(err ** 2)))
    mae = float(np.mean(np.abs(err)))
    nz = y_true != 0
    hit = float(np.mean(np.sign(y_pred[nz]) == np.sign(y_true[nz]))) if nz.any() else np.nan
    m = np.abs(y_pred) > COND_THR
    condhit = (float(np.mean(np.sign(y_pred[m]) == np.sign(y_true[m]))) if m.any() else np.nan)
    condn = int(m.sum())
    return dict(rmse=rmse, mae=mae, hit=hit, condhit=condhit, condn=condn, n=len(y_true))


def winsorize_train(y, lo_hi):
    lo, hi = np.quantile(y, lo_hi[0]), np.quantile(y, lo_hi[1])
    return np.clip(y, lo, hi)


def cv_score(X, y, gap, winsor):
    """TimeSeriesSplit 평균 홀드-폴드 지표."""
    tscv = TimeSeriesSplit(n_splits=5, gap=gap)
    preds, trues = [], []
    for tr, va in tscv.split(X):
        ytr = winsorize_train(y[tr], WINSOR) if winsor else y[tr]
        m = new_model().fit(X[tr], ytr)
        preds.append(m.predict(X[va]))
        trues.append(y[va])
    return metrics(np.concatenate(trues), np.concatenate(preds))


def fit_predict_holdout(Xdev, ydev, Xhold, winsor):
    ytr = winsorize_train(ydev, WINSOR) if winsor else ydev
    m = new_model().fit(Xdev, ytr)
    return m.predict(Xhold)


def beta_sox_baseline(sox_dev, ydev, sox_hold):
    v = np.var(sox_dev)
    beta = np.cov(sox_dev, ydev)[0, 1] / v if v > 0 else 0.0
    return beta * sox_hold


def run_stock(name, d, other_close, us_lr):
    us_cols = [f"{t}_on" for t in US_COMMON + US_SPECIFIC[name]]
    feat_cols = ["self_ret_prev", "self_gap_prev", "self_range_prev",
                 "self_volz_prev", "cross_ret_prev"] + us_cols

    # v1: 룩어헤드 정렬 / v2: 밤사이 정렬
    ds_v1 = assemble(name, d, other_close, us_lr, us_cols, exact=True).dropna(subset=feat_cols)
    ds_v2 = assemble(name, d, other_close, us_lr, us_cols, exact=False).dropna(subset=feat_cols)

    def split(ds):
        X = ds[feat_cols].to_numpy()
        y = ds["y"].to_numpy()
        Xdev, ydev = X[:-HOLDOUT_DAYS], y[:-HOLDOUT_DAYS]
        Xh, yh = X[-HOLDOUT_DAYS:], y[-HOLDOUT_DAYS:]
        sox = ds["^SOX_on"].to_numpy()
        return X, y, Xdev, ydev, Xh, yh, sox[:-HOLDOUT_DAYS], sox[-HOLDOUT_DAYS:]

    Xv1, yv1, Xdv1, ydv1, Xhv1, yhv1, soxd1, soxh1 = split(ds_v1)
    Xv2, yv2, Xdv2, ydv2, Xhv2, yhv2, soxd2, soxh2 = split(ds_v2)

    rows = []
    # 베이스라인 (v2 홀드아웃 기준)
    rows.append(("baseline y=0", metrics(yhv2, np.zeros_like(yhv2))))
    rows.append(("baseline β·SOX", metrics(yhv2, beta_sox_baseline(soxd2, ydv2, soxh2))))
    # v1: 전체구간 CV(gap=0, raw) — 낙관 보고치
    rows.append(("v1  CV(보고치)", cv_score(Xv1, yv1, gap=0, winsor=False)))
    # v1: 같은 모델을 깨끗한 홀드아웃에 — 실제 성능
    rows.append(("v1  홀드아웃(실제)",
                 metrics(yhv1, fit_predict_holdout(Xdv1, ydv1, Xhv1, winsor=False))))
    # v2: dev 구간 CV(gap=5, winsor) — 정직한 CV
    rows.append(("v2  CV(정직)", cv_score(Xdv2, ydv2, gap=EMBARGO, winsor=True)))
    # v2: 홀드아웃
    rows.append(("v2  홀드아웃",
                 metrics(yhv2, fit_predict_holdout(Xdv2, ydv2, Xhv2, winsor=True))))

    return rows, len(ds_v2), HOLDOUT_DAYS


def print_table(name, rows, n_total, n_hold):
    print(f"\n{'='*78}\n  {name}   (표본 {n_total}일, 홀드아웃 {n_hold}일)\n{'='*78}")
    print(f"  {'프로토콜':<18}{'RMSE':>10}{'MAE':>10}{'방향적중':>10}{'조건부적중':>12}{'표본':>8}")
    print("  " + "-" * 74)
    base_rmse = rows[0][1]["rmse"]
    for label, m in rows:
        cond = f"{m['condhit']*100:5.1f}%({m['condn']})" if m["condhit"] == m["condhit"] else "   —"
        hit = f"{m['hit']*100:5.1f}%" if m["hit"] == m["hit"] else "  —"
        vs = (base_rmse - m["rmse"]) / base_rmse * 100  # +면 베이스라인보다 우수
        print(f"  {label:<18}{m['rmse']*100:9.4f}%{m['mae']*100:9.4f}%{hit:>10}{cond:>12}{m['n']:>8}")
    print("  " + "-" * 74)
    print(f"  * RMSE/MAE 단위: %p(갭). vs베이스라인(y=0 RMSE={base_rmse*100:.4f}%) 대비 개선은 아래 요약 참고.")


def main():
    print("데이터 수집 중(yfinance)…")
    us, kr = fetch()
    us_lr = us_overnight(us)
    names = list(KR)
    closes = {n: kr[n]["Close"] for n in names}

    summary = []
    for i, name in enumerate(names):
        other = names[1 - i]
        rows, n_total, n_hold = run_stock(name, kr[name], closes[other], us_lr)
        print_table(name, rows, n_total, n_hold)
        summary.append((name, rows))

    # 요약: v1 CV가 홀드아웃에서 얼마나 무너지는가
    print(f"\n{'='*78}\n  요약 — v1의 낙관 CV vs 실제, v2의 정직한 측정\n{'='*78}")
    for name, rows in summary:
        d = dict(rows)
        v1cv = d["v1  CV(보고치)"]["rmse"]
        v1ho = d["v1  홀드아웃(실제)"]["rmse"]
        v2ho = d["v2  홀드아웃"]["rmse"]
        b = d["baseline y=0"]["rmse"]
        infl = (v1ho - v1cv) / v1cv * 100
        print(f"\n  [{name}]")
        print(f"   v1 CV 보고 RMSE      {v1cv*100:.4f}%  ← 발표하고 싶은 숫자")
        print(f"   v1 홀드아웃 실제 RMSE {v1ho*100:.4f}%  ({infl:+.1f}% 악화 = CV 낙관 편향)")
        print(f"   v2 홀드아웃 RMSE      {v2ho*100:.4f}%")
        print(f"   베이스라인 y=0 RMSE   {b*100:.4f}%")
        edge_v2 = (b - v2ho) / b * 100
        edge_v1 = (b - v1ho) / b * 100
        verdict = ("베이스라인 우위(엣지 있음)" if edge_v2 > 0 else "베이스라인 못 이김(엣지 없음 — 유효한 결론)")
        print(f"   → v2 정직 측정: 베이스라인 대비 {edge_v2:+.1f}%  ⇒ {verdict}")
        print(f"   → v1 실제(홀드아웃): 베이스라인 대비 {edge_v1:+.1f}%")

    print("\n⚠️ 통계 모델 비교 실험이며 투자 권유가 아님. 백테스트 성과는 실거래를 보장하지 않음.")


if __name__ == "__main__":
    main()
