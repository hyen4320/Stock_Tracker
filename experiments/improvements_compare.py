"""SPEC_IMPROVEMENTS 적용 실험 — 개선점을 반영한 뒤의 성능 비교.

기존 결론("엣지는 대부분 오버나잇 SOX 베타, 추가 피처의 한계 엣지 작다")을
docs/SPEC_IMPROVEMENTS.md 의 개선점을 실제 적용해 재검증한다.

적용한 개선점
  #4   타깃을 raw(미수정) OHLC 로 계산 — auto_adjust 의 미래 배당 소급 look-ahead 제거
       (분할은 비율 타깃에 중립, 배당락일 갭은 실제 체결가 기준이 됨)
  #8   rolling β·SOX 베이스라인 — 전 구간 고정 β(누수) 대신 과거 250일 point-in-time β
  #2   잔차 타깃 — y_resid = y − β̂_t·SOX. 모델은 "뻔한 오버나잇 베타 너머"만 학습,
       최종 예측 = β̂_t·SOX + resid_pred
  #9   외국인/기관 순매수(★) — 네이버 금융 일별 데이터(D-1 lag, 15:30 확정 < 08:59 컷오프)
  #11  sign(SOX) 방향 베이스라인 명시
  #5   단일 홀드아웃 → 4×126일 롤링 홀드아웃 분포 (expanding dev + embargo)
  #1   Diebold–Mariano 검정(Newey-West) + moving block bootstrap 으로
       rolling-β 베이스라인 대비 RMSE 차이의 유의성/신뢰구간
  #7   거래비용 반영 P&L (전일종가 진입→시가 청산 가정; 아래 캐비엇 참고)
  #13  자동 누수 프로브 — (a) 타깃 셔플 시 성능 붕괴 확인, (b) 미래 피처 주입 시
       하네스가 비현실적 점수를 검출하는지 확인

적용 불가/제외 (사유)
  #3   이미 완료 (experiments/model_compare.py — v2 모델링은 역효과, 최적 구성 채택)
  #6   인트라데이(08:59 야간선물 스냅샷) — yfinance 일봉으로 불가
  #10  풀링 시 타깃 표준화 — 본 실험은 종목별 모델(옵션 A)이라 해당 없음
  #12  분위수 calibration — 점추정 모델만 비교 (후속 과제)

P&L 캐비엇: 갭 캡처(전일종가 진입→시가 청산)는 예측 입력(美 세션 종가)이 한국
전일 종가 *이후* 확정되므로 현물로는 그대로 체결 불가능한 **상한 추정**이다.
실제 구현은 야간선물 헤지·시가 단일가 주문 등으로 근사해야 하며 공매도 제약도 있다.

모델: model_compare.py 에서 최적이었던 구성(v1 수준 정규화 + 단조제약). 측정은
v2 프로토콜(strict-backward 정렬, 학습 fold 내 winsorize, ES 셋 분리) 고정.

실행:  python -m experiments.improvements_compare
"""
from __future__ import annotations

import io
import sys
import time
import warnings

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import lightgbm as lgb
import numpy as np
import pandas as pd
import requests
import yfinance as yf
from scipy.stats import norm

from backend.series_store import load_frame, upsert_frame
from experiments.model_compare import ES_FRAC, ES_ROUNDS, mono_vector
from experiments.spec_compare import (
    EMBARGO, KR, RANDOM_STATE, START, US_COMMON, US_SPECIFIC, WINSOR, COND_THR,
    _flatten, assemble, metrics, self_features, us_overnight, winsorize_train,
)

warnings.simplefilter("ignore")

BETA_WIN = 250          # rolling β 추정 윈도우 (#8, #2)
BETA_MIN = 100
N_WINDOWS = 4           # 롤링 홀드아웃 개수 (#5)
WIN_LEN = 126           # 각 홀드아웃 길이 (≈6개월)
BOOT_B = 2000           # block bootstrap 반복 (#1)
BOOT_BLOCK = 20
DM_LAG = 10             # DM 검정 Newey-West 랙
COSTS_BP = [0, 10, 30]  # 왕복 거래비용 시나리오 (#7)

FLOW_COLS = ["frgn_ratio_prev", "frgn_5d_prev", "frgn_z20_prev", "inst_ratio_prev"]


# ──────────────────────────────── 데이터 ────────────────────────────────

def fetch_raw():
    """美는 수정주가(피처용), KR은 raw OHLC(타깃·자기시계열, #4)."""
    us_list = sorted(set(US_COMMON + sum(US_SPECIFIC.values(), [])))
    us = yf.download(us_list, start=START, auto_adjust=True, progress=False)["Close"]
    us = us.dropna(how="all")
    kr = {}
    for name, tk in KR.items():
        d = _flatten(yf.download(tk, start=START, auto_adjust=False, progress=False))
        kr[name] = d[["Open", "High", "Low", "Close", "Volume"]].dropna(how="all")
    return us, kr


def fetch_naver_flows(code: str) -> pd.DataFrame:
    """네이버 금융 일별 외국인/기관 순매매량 (#9). DB(daily_series)에 캐시."""
    cached = load_frame("naver_frgn", entity=code)
    if not cached.empty:
        print(f"  [{code}] 수급 캐시 사용(DB): {len(cached)}일")
        return cached

    sess = requests.Session()
    sess.headers["User-Agent"] = "Mozilla/5.0"
    start_ts = pd.Timestamp(START)
    frames, page = [], 1
    while page <= 250:
        url = f"https://finance.naver.com/item/frgn.naver?code={code}&page={page}"
        t = pd.read_html(io.StringIO(sess.get(url, timeout=10).text))[3]
        t.columns = ["date", "close", "chg", "pct", "volume",
                     "inst_net", "frgn_net", "frgn_held", "frgn_ratio"]
        t = t.dropna(subset=["date"]).copy()
        if t.empty:
            break
        t["date"] = pd.to_datetime(t["date"], format="%Y.%m.%d")
        frames.append(t[["date", "volume", "inst_net", "frgn_net"]])
        if t["date"].min() < start_ts:
            break
        page += 1
        time.sleep(0.15)

    df = (pd.concat(frames).drop_duplicates("date").set_index("date")
          .sort_index().loc[start_ts:])
    df = df.apply(pd.to_numeric, errors="coerce")
    upsert_frame("naver_frgn", df, entity=code)
    print(f"  [{code}] 네이버 수급 {len(df)}일 수집 ({page}페이지) → DB")
    return df


def flow_features(flows: pd.DataFrame) -> pd.DataFrame:
    """D-1 까지 확정된 수급 피처 (전부 shift(1) — 15:30 확정 < 08:59 컷오프)."""
    fr = flows["frgn_net"] / flows["volume"]          # 거래량 대비 외국인 순매수 강도
    ir = flows["inst_net"] / flows["volume"]
    z = ((flows["frgn_net"] - flows["frgn_net"].rolling(20).mean())
         / flows["frgn_net"].rolling(20).std())
    return pd.DataFrame({
        "frgn_ratio_prev": fr.shift(1),
        "frgn_5d_prev": fr.rolling(5).sum().shift(1),
        "frgn_z20_prev": z.shift(1),
        "inst_ratio_prev": ir.shift(1),
    })


# ──────────────────────────────── 통계 (#1) ────────────────────────────────

def dm_test(e_model: np.ndarray, e_base: np.ndarray, lag: int = DM_LAG):
    """Diebold–Mariano (제곱오차 손실, Newey-West 분산). 음수 stat = 모델 우위."""
    d = e_model ** 2 - e_base ** 2
    n = len(d)
    dbar = d.mean()
    dc = d - dbar
    s = float(np.mean(dc * dc))
    for k in range(1, lag + 1):
        gamma = float(np.mean(dc[k:] * dc[:-k]))
        s += 2.0 * (1.0 - k / (lag + 1.0)) * gamma
    if s <= 0:
        return np.nan, np.nan
    stat = dbar / np.sqrt(s / n)
    p = 2.0 * (1.0 - norm.cdf(abs(stat)))
    return float(stat), float(p)


def block_bootstrap_ci(e_model, e_base, B=BOOT_B, block=BOOT_BLOCK):
    """moving block bootstrap — RMSE(model) − RMSE(base) 차이의 95% CI."""
    rng = np.random.default_rng(RANDOM_STATE)
    n = len(e_model)
    n_blocks = int(np.ceil(n / block))
    diffs = np.empty(B)
    for b in range(B):
        starts = rng.integers(0, n - block + 1, size=n_blocks)
        idx = (starts[:, None] + np.arange(block)).ravel()[:n]
        diffs[b] = (np.sqrt(np.mean(e_model[idx] ** 2))
                    - np.sqrt(np.mean(e_base[idx] ** 2)))
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return float(lo), float(hi)


# ──────────────────────────────── 모델 ────────────────────────────────

def make_lgbm(mono):
    """model_compare.py ablation 최적 구성: v1 수준 정규화 + 단조제약."""
    return lgb.LGBMRegressor(
        objective="regression", n_estimators=2000, learning_rate=0.02,
        num_leaves=31, min_child_samples=30,
        subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
        reg_lambda=1.0, monotone_constraints=mono,
        random_state=RANDOM_STATE, verbosity=-1,
    )


def fit_lgbm(model, Xtr, ytr):
    k = max(int(len(Xtr) * ES_FRAC), 50)
    model.fit(Xtr[:-k], ytr[:-k], eval_set=[(Xtr[-k:], ytr[-k:])],
              callbacks=[lgb.early_stopping(ES_ROUNDS, verbose=False),
                         lgb.log_evaluation(0)])
    return model


# ──────────────────────────────── 실험 본체 ────────────────────────────────

def build_dataset(name, d, other_close, us_lr, flows):
    us_cols = [f"{t}_on" for t in US_COMMON + US_SPECIFIC[name]]
    ds = assemble(name, d, other_close, us_lr, us_cols, exact=False)
    ds = ds.join(flow_features(flows))
    base_cols = list(self_features(d, other_close).columns) + us_cols
    ds = ds.dropna(subset=base_cols)          # 수급 결측은 모델 토글로만 사용
    return ds, base_cols, us_cols


def rolling_beta(y: pd.Series, sox: pd.Series) -> pd.Series:
    """과거 250일 point-in-time β̂_t (당일 미포함 — shift(1))."""
    cov = y.rolling(BETA_WIN, min_periods=BETA_MIN).cov(sox)
    var = sox.rolling(BETA_WIN, min_periods=BETA_MIN).var()
    return (cov / var).shift(1)


def run_stock(name, ds, base_cols):
    y = ds["y"]
    sox = ds["^SOX_on"]
    beta = rolling_beta(y, sox)
    ok = beta.notna()
    ds, y, sox, beta = ds[ok], y[ok], sox[ok], beta[ok]
    n = len(ds)

    feat_flow = base_cols + FLOW_COLS
    has_flow = ds[FLOW_COLS].notna().all(axis=1)

    mono_base = mono_vector(base_cols)
    pred_roll = (beta * sox).to_numpy()       # rolling β·SOX 베이스라인 (#8)
    y_np = y.to_numpy()
    resid_np = (y - beta * sox).to_numpy()    # 잔차 타깃 (#2)

    oos_start = n - N_WINDOWS * WIN_LEN
    collected = {k: [] for k in
                 ["y", "zero", "fixedβ", "rollβ", "raw", "resid", "resid+frgn"]}
    perwin = {k: [] for k in ["fixedβ", "rollβ", "raw", "resid", "resid+frgn"]}

    for w in range(N_WINDOWS):
        t0 = oos_start + w * WIN_LEN
        t1 = t0 + WIN_LEN
        dev = slice(0, t0 - EMBARGO)
        te = slice(t0, t1)

        Xb = ds[base_cols].to_numpy()
        # 고정 β (dev 전 구간, 기존 spec_compare 방식 — 비교용)
        v = np.var(sox.to_numpy()[dev])
        fb = (np.cov(sox.to_numpy()[dev], y_np[dev])[0, 1] / v) if v > 0 else 0.0
        preds = {"zero": np.zeros(WIN_LEN),
                 "fixedβ": fb * sox.to_numpy()[te],
                 "rollβ": pred_roll[te]}

        # raw 타깃 모델 (단조제약 유지)
        m = fit_lgbm(make_lgbm(mono_base), Xb[dev], winsorize_train(y_np[dev], WINSOR))
        preds["raw"] = m.predict(Xb[te])

        # 잔차 타깃 모델 (#2 — SOX 선형효과 제거 후라 단조제약 미적용)
        m = fit_lgbm(make_lgbm(None), Xb[dev], winsorize_train(resid_np[dev], WINSOR))
        preds["resid"] = pred_roll[te] + m.predict(Xb[te])

        # 잔차 + 외국인/기관 수급 (#9). 수급 가용 행만 학습(결측은 LGBM NaN 처리)
        Xf = ds[feat_flow].to_numpy()
        m = fit_lgbm(make_lgbm(None), Xf[dev], winsorize_train(resid_np[dev], WINSOR))
        preds["resid+frgn"] = pred_roll[te] + m.predict(Xf[te])

        collected["y"].append(y_np[te])
        for k, p in preds.items():
            collected[k].append(p)
        for k in perwin:
            perwin[k].append(metrics(y_np[te], preds[k])["rmse"])

    out = {k: np.concatenate(v) for k, v in collected.items()}
    flow_cov = float(has_flow.iloc[oos_start:].mean())
    return out, perwin, flow_cov, n


def leak_probes(name, ds, base_cols):
    """#13 — (a) 타깃 셔플 → 붕괴 확인, (b) 미래 피처 주입 → 검출 확인."""
    mono = mono_vector(base_cols)
    y = ds["y"].to_numpy()
    X = ds[base_cols].to_numpy()
    n = len(ds)
    t0 = n - N_WINDOWS * WIN_LEN
    dev, te = slice(0, t0 - EMBARGO), slice(t0, n)
    rng = np.random.default_rng(RANDOM_STATE)

    base_rmse = metrics(y[te], np.zeros(n - t0))["rmse"]

    ysh = y[dev].copy()
    rng.shuffle(ysh)
    m = fit_lgbm(make_lgbm(mono), X[dev], ysh)
    shuf_rmse = metrics(y[te], m.predict(X[te]))["rmse"]
    shuf_ok = shuf_rmse >= 0.95 * base_rmse   # y=0 수준으로 붕괴해야 정상

    Xleak = np.column_stack([X, y])            # 미래 정보(타깃 자체) 주입
    m = fit_lgbm(make_lgbm(mono + [0]), Xleak[dev], winsorize_train(y[dev], WINSOR))
    leak_rmse = metrics(y[te], m.predict(Xleak[te]))["rmse"]
    leak_ok = leak_rmse < 0.5 * base_rmse      # 비현실적 점수 → 프로브가 누수 검출

    print(f"\n  [{name}] 누수 프로브 (#13)  — 기준 y=0 RMSE {base_rmse*100:.3f}%")
    print(f"   (a) 타깃 셔플 학습 → RMSE {shuf_rmse*100:.3f}%  "
          f"{'통과(베이스라인으로 붕괴 — 피처 경로 누수 없음)' if shuf_ok else '⚠ 실패(셔플인데 성능 잔존 — 누수 의심)'}")
    print(f"   (b) 미래 피처 주입 → RMSE {leak_rmse*100:.3f}%  "
          f"{'통과(비현실적 점수 검출 — 하네스가 누수에 민감)' if leak_ok else '⚠ 실패(누수를 주입해도 점수 정상 — 하네스 둔감)'}")
    return shuf_ok and leak_ok


def pnl_table(name, out):
    """#7 — |예측|>0.3% 일 때 갭 방향 베팅. 왕복 비용 차감 (상한 추정, 캐비엇 참고)."""
    y = out["y"]
    print(f"\n  [{name}] 경제적 가치 (#7) — OOS {len(y)}일, |예측|>{COND_THR*100:.1f}% 진입, 롱+숏")
    print(f"   {'구성':<14}{'거래':>6}{'적중':>8}" + "".join(f"{f'순수익@{c}bp':>14}" for c in COSTS_BP))
    for k in ["rollβ", "raw", "resid", "resid+frgn"]:
        p = out[k]
        m = np.abs(p) > COND_THR
        nt = int(m.sum())
        if nt == 0:
            print(f"   {k:<14}{0:>6}")
            continue
        gross = np.sign(p[m]) * y[m]
        hit = float(np.mean(gross > 0))
        cells = []
        for c in COSTS_BP:
            net = gross - c / 1e4
            cells.append(f"{net.sum()*100:+9.1f}%p")
        print(f"   {k:<14}{nt:>6}{hit*100:>7.1f}%" + "".join(f"{c:>14}" for c in cells))
    print("   * 순수익 = OOS 2년 누적 로그수익 합(%p). 전일종가 진입 가정의 상한 추정 — 모듈 docstring 캐비엇 참고.")


def report(name, out, perwin, flow_cov):
    y = out["y"]
    labels = [("y=0", "zero"), ("고정 β·SOX(기존)", "fixedβ"),
              ("rolling β·SOX (#8)", "rollβ"), ("LGBM raw 타깃", "raw"),
              ("LGBM 잔차 타깃 (#2)", "resid"), ("잔차+외국인수급 (#9)", "resid+frgn")]
    e_base = out["rollβ"] - y

    print(f"\n{'='*96}\n  {name} — 롤링 홀드아웃 {N_WINDOWS}×{WIN_LEN}일 합산 "
          f"(raw 타깃 #4, OOS 수급 커버리지 {flow_cov*100:.0f}%)\n{'='*96}")
    print(f"  {'구성':<22}{'RMSE':>9}{'MAE':>9}{'방향':>8}{'조건부':>12}"
          f"{'DM p':>8}{'ΔRMSE 95% CI':>22}{'윈도RMSE(4개)':>20}")
    print("  " + "-" * 92)
    for lab, k in labels:
        m = metrics(y, out[k])
        hit = f"{m['hit']*100:5.1f}%" if m["hit"] == m["hit"] else "    —"
        cond = f"{m['condhit']*100:5.1f}%({m['condn']})" if m["condhit"] == m["condhit"] else "      —"
        if k in ("zero", "fixedβ", "rollβ"):
            dm, ci, pw = "—", "—", ""
            if k in perwin:
                pw = "/".join(f"{r*100:.2f}" for r in perwin[k])
        else:
            e = out[k] - y
            _, p = dm_test(e, e_base)
            lo, hi = block_bootstrap_ci(e, e_base)
            dm = f"{p:.3f}"
            ci = f"[{lo*100:+.3f}, {hi*100:+.3f}]"
            pw = "/".join(f"{r*100:.2f}" for r in perwin[k])
        print(f"  {lab:<22}{m['rmse']*100:8.4f}%{m['mae']*100:8.4f}%{hit:>8}{cond:>12}"
              f"{dm:>8}{ci:>22}{pw:>20}")
    # sign(SOX) 방향 베이스라인 (#11): β>0 이므로 rollβ 와 부호 동일 → 방향 수치는 rollβ 행과 같음
    print("  " + "-" * 92)
    print("  * sign(SOX) 방향 베이스라인(#11) = rolling β·SOX 행의 방향/조건부 수치(β>0이라 부호 동일).")
    print("  * DM p / ΔRMSE CI 는 rolling β·SOX 베이스라인 대비 (음수 Δ = 모델 우위).")


def main():
    print("데이터 수집 중(yfinance + 네이버 수급)…")
    us, kr = fetch_raw()
    us_lr = us_overnight(us)
    names = list(KR)
    closes = {nm: kr[nm]["Close"] for nm in names}
    flows = {nm: fetch_naver_flows(KR[nm].split(".")[0]) for nm in names}

    for i, name in enumerate(names):
        ds, base_cols, _ = build_dataset(name, kr[name], closes[names[1 - i]],
                                         us_lr, flows[name])
        out, perwin, flow_cov, n = run_stock(name, ds, base_cols)
        report(name, out, perwin, flow_cov)
        pnl_table(name, out)
        leak_probes(name, ds, base_cols)

    print("\n⚠️ 통계 모델 비교 실험이며 투자 권유가 아님. 백테스트 성과는 실거래를 보장하지 않음.")


if __name__ == "__main__":
    main()
