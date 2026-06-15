"""개선된 성능 테스트 하니스 — SPEC_IMPROVEMENTS의 Tier-1 항목을 실제로 구현/측정.

spec_compare.py는 "v1 느슨 vs v2 엄격"의 *측정 정직성*을 보였다. 이 스크립트는 그
다음 질문 — **"v2 풀모델이 β·SOX를 진짜로 이기는가, 0.03%p는 신호인가 노이즈인가"** —
에 답하기 위해 SPEC_IMPROVEMENTS의 Tier-1 개선을 붙인다.

  #1 부트스트랩 CI   : (모델 RMSE − β·SOX RMSE) 차이의 95% CI + 방향적중 차이 CI
                       → 0을 포함하면 "동률"이 아니라 "구분 불가"가 정답
  #2 잔차 타깃        : y_resid = y − β̂_pit·ret_SOX 로 학습. 오버나잇 베타를 먼저 제거하고
                       "뻔한 것 너머" 엣지만 모델이 학습하게 함
  #8 point-in-time β  : 전 구간 고정 β(룩어헤드) 대신 매 시점 과거만으로 추정한 expanding β
  #11 sign(SOX) 베이스 : 밤사이 SOX 부호대로만 베팅하는 방향 베이스라인
  #3 모델링           : LightGBM 있으면 사용(없으면 sklearn HGB로 폴백)

데이터 범위는 spec_compare.py와 동일(yfinance 전용, 추가 설치 0개 가능).

실행:  python -m experiments.model_eval
"""
from __future__ import annotations

import sys
import warnings

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.ensemble import HistGradientBoostingRegressor

warnings.simplefilter("ignore")

try:
    import lightgbm as lgb
    HAVE_LGB = True
except ImportError:
    HAVE_LGB = False

# #9 외국인 순매수(★) — KRX 자격증명 있으면 피처로 추가, 없으면 자동 스킵
try:
    from experiments.krx_supply import has_credentials, load_supply
    USE_SUPPLY = has_credentials()
except Exception:
    USE_SUPPLY = False

START = "2017-01-01"
HOLDOUT_DAYS = 252
BETA_MIN_TRAIN = 252         # point-in-time β 추정 최소 학습 표본
COND_THR = 0.003
RANDOM_STATE = 42
N_BOOT = 2000                # 블록 부트스트랩 반복
BLOCK = 10                   # 블록 길이(자기상관 보존)
rng = np.random.default_rng(RANDOM_STATE)

KR = {"삼성전자": "005930.KS", "SK하이닉스": "000660.KS"}
US_COMMON = ["^SOX", "MU", "NVDA", "AVGO", "^IXIC", "^GSPC", "^VIX",
             "NQ=F", "ES=F", "DX-Y.NYB", "KRW=X"]
US_SPECIFIC = {"삼성전자": ["TSM", "QCOM"], "SK하이닉스": []}


# ----------------------------------------------------------------------------- 데이터
def _flatten(df):
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    return df


def fetch():
    us_list = sorted(set(US_COMMON + sum(US_SPECIFIC.values(), [])))
    us = yf.download(us_list, start=START, auto_adjust=True, progress=False)["Close"]
    us = us.dropna(how="all")
    kr = {}
    for name, tk in KR.items():
        d = _flatten(yf.download(tk, start=START, auto_adjust=True, progress=False))
        kr[name] = d[["Open", "High", "Low", "Close", "Volume"]].dropna(how="all")
    return us, kr


def us_overnight(us):
    lr = np.log(us / us.shift(1))
    lr.columns = [f"{c}_on" for c in lr.columns]
    return lr


def self_features(d, other_close):
    close, high, low, vol = d["Close"], d["High"], d["Low"], d["Volume"]
    ret = np.log(close / close.shift(1))
    gap = np.log(d["Open"] / close.shift(1))
    rng_ = (high - low) / close
    volz = (vol - vol.rolling(20).mean()) / vol.rolling(20).std()
    other_ret = np.log(other_close / other_close.shift(1)).reindex(close.index)
    return pd.DataFrame({
        "self_ret_prev": ret.shift(1),
        "self_gap_prev": gap.shift(1),
        "self_range_prev": rng_.shift(1),
        "self_volz_prev": volz.shift(1),
        "cross_ret_prev": other_ret.shift(1),
    })


def assemble(d, other_close, us_lr, us_cols):
    """v2 정렬(merge_asof backward, exact=False) 고정. 룩어헤드 없는 밤사이 정렬."""
    y = np.log(d["Open"] / d["Close"].shift(1)).rename("y")
    selfx = self_features(d, other_close)
    left = pd.concat([y, selfx], axis=1).reset_index()
    left.columns = ["date"] + list(left.columns[1:])
    right = us_lr[us_cols].reset_index()
    right.columns = ["date"] + us_cols
    merged = pd.merge_asof(left.sort_values("date"), right.sort_values("date"),
                           on="date", direction="backward", allow_exact_matches=False)
    return merged.set_index("date").dropna(subset=["y"])


# ----------------------------------------------------------------------------- 모델/β
def new_model():
    if HAVE_LGB:
        # v2 §7.2 구성에 가깝게 (num_leaves 15, min_child 50, Huber)
        return lgb.LGBMRegressor(
            n_estimators=800, learning_rate=0.03, num_leaves=15,
            min_child_samples=50, subsample=0.8, colsample_bytree=0.8,
            reg_lambda=1.0, objective="huber", random_state=RANDOM_STATE, verbose=-1,
        )
    return HistGradientBoostingRegressor(
        max_iter=300, learning_rate=0.05, max_depth=3,
        l2_regularization=1.0, random_state=RANDOM_STATE,
    )


def pit_beta_pred(sox, y, min_train):
    """point-in-time expanding β (#8). 각 i의 예측은 [0, i) 과거만으로 추정한 β·sox[i].
    반환: pred(길이 N, 앞 min_train개는 NaN), beta 시계열."""
    n = len(sox)
    pred = np.full(n, np.nan)
    betas = np.full(n, np.nan)
    # 누적 통계로 expanding cov/var (룩어헤드 없음: i 시점 β는 [0,i) 데이터만)
    for i in range(min_train, n):
        sx, yy = sox[:i], y[:i]
        v = np.var(sx)
        b = np.cov(sx, yy)[0, 1] / v if v > 0 else 0.0
        betas[i] = b
        pred[i] = b * sox[i]
    return pred, betas


# ----------------------------------------------------------------------------- 지표
def rmse(e):
    return float(np.sqrt(np.mean(e ** 2)))


def metrics(y_true, y_pred):
    y_true = np.asarray(y_true, float)
    y_pred = np.asarray(y_pred, float)
    err = y_pred - y_true
    nz = y_true != 0
    hit = float(np.mean(np.sign(y_pred[nz]) == np.sign(y_true[nz]))) if nz.any() else np.nan
    m = np.abs(y_pred) > COND_THR
    condhit = float(np.mean(np.sign(y_pred[m]) == np.sign(y_true[m]))) if m.any() else np.nan
    return dict(rmse=rmse(err), mae=float(np.mean(np.abs(err))),
                hit=hit, condhit=condhit, condn=int(m.sum()), n=len(y_true))


def block_boot_idx(n, block, size):
    """이동 블록 부트스트랩 인덱스 (자기상관 보존)."""
    n_blocks = int(np.ceil(size / block))
    starts = rng.integers(0, n - block + 1, size=n_blocks)
    idx = np.concatenate([np.arange(s, s + block) for s in starts])[:size]
    return idx


def boot_rmse_diff(y_true, pred_a, pred_b):
    """RMSE(a) − RMSE(b) 의 부트스트랩 분포. <0 이면 a가 더 우수(=베이스라인 이김)."""
    ea = (pred_a - y_true) ** 2
    eb = (pred_b - y_true) ** 2
    n = len(y_true)
    diffs = np.empty(N_BOOT)
    for k in range(N_BOOT):
        ix = block_boot_idx(n, BLOCK, n)
        diffs[k] = np.sqrt(ea[ix].mean()) - np.sqrt(eb[ix].mean())
    point = rmse(pred_a - y_true) - rmse(pred_b - y_true)
    lo, hi = np.quantile(diffs, [0.025, 0.975])
    p_worse = float(np.mean(diffs >= 0))  # a가 b보다 나쁘거나 같을 확률
    return point, lo, hi, p_worse


def boot_hit_diff(y_true, pred_a, pred_b):
    """방향적중(a) − 방향적중(b) 부트스트랩. >0 이면 a가 방향 더 잘 맞춤."""
    nz = y_true != 0
    yt, pa, pb = y_true[nz], pred_a[nz], pred_b[nz]
    ha = (np.sign(pa) == np.sign(yt)).astype(float)
    hb = (np.sign(pb) == np.sign(yt)).astype(float)
    n = len(yt)
    diffs = np.empty(N_BOOT)
    for k in range(N_BOOT):
        ix = block_boot_idx(n, BLOCK, n)
        diffs[k] = ha[ix].mean() - hb[ix].mean()
    point = ha.mean() - hb.mean()
    lo, hi = np.quantile(diffs, [0.025, 0.975])
    return point, lo, hi


# ----------------------------------------------------------------------------- 종목 실행
def attach_supply(ds, name):
    """#9 외국인/기관 순매수를 D-1 lag 피처로 부착. 트리는 스케일 불변 → raw 값 사용,
    shift(1)로 '전일 장마감 후 확정값'만 써서 룩어헤드 차단. 추가된 컬럼명 리스트 반환."""
    sup = load_supply(name, START, "2026-12-31")
    if sup is None or sup.empty:
        return ds, []
    sup = sup.reindex(ds.index)        # KR 거래일 인덱스에 정렬
    cols = []
    for c in ["frgn_net", "inst_net"]:
        if c in sup.columns:
            ds[c + "_prev"] = sup[c].shift(1).to_numpy()
            cols.append(c + "_prev")
    return ds, cols


def run_stock(name, d, other_close, us_lr):
    us_cols = [f"{t}_on" for t in US_COMMON + US_SPECIFIC[name]]
    feat_cols = ["self_ret_prev", "self_gap_prev", "self_range_prev",
                 "self_volz_prev", "cross_ret_prev"] + us_cols
    ds = assemble(d, other_close, us_lr, us_cols)
    if USE_SUPPLY:
        ds, sup_cols = attach_supply(ds, name)
        feat_cols = feat_cols + sup_cols
    ds = ds.dropna(subset=feat_cols)

    X = ds[feat_cols].to_numpy()
    y = ds["y"].to_numpy()
    sox = ds["^SOX_on"].to_numpy()
    n = len(y)
    h0 = n - HOLDOUT_DAYS  # 홀드아웃 시작 인덱스

    Xdev, ydev = X[:h0], y[:h0]
    Xh, yh = X[h0:], y[h0:]
    soxh = sox[h0:]

    # --- 베이스라인 ---------------------------------------------------------
    # (a) 고정 β (전 dev 구간, spec_compare와 동일)
    v = np.var(sox[:h0])
    beta_fixed = np.cov(sox[:h0], y[:h0])[0, 1] / v if v > 0 else 0.0
    pred_beta_fixed = beta_fixed * soxh
    # (b) point-in-time expanding β (#8) — 홀드아웃 구간만 추출
    pit_pred_all, _ = pit_beta_pred(sox, y, BETA_MIN_TRAIN)
    pred_beta_pit = pit_pred_all[h0:]
    # (c) sign(SOX) 방향 베이스라인 (#11) — 크기는 dev 평균 |gap| 로
    scale = np.mean(np.abs(ydev))
    pred_sign = np.sign(soxh) * scale
    # (d) y=0
    pred_zero = np.zeros_like(yh)

    # --- v2 풀모델: 직접 타깃 ------------------------------------------------
    m_direct = new_model().fit(Xdev, ydev)
    pred_direct = m_direct.predict(Xh)

    # --- v2 풀모델: 잔차 타깃 (#2) ------------------------------------------
    # 잔차는 point-in-time β로 계산(룩어헤드 차단). dev/holdout 모두 동일 β 시계열 사용.
    resid_all = y - np.nan_to_num(pit_pred_all)   # 앞 min_train구간은 β=0 취급
    # min_train 이후만 학습에 사용
    valid = np.arange(n) >= BETA_MIN_TRAIN
    dev_mask = valid.copy(); dev_mask[h0:] = False
    m_resid = new_model().fit(X[dev_mask], resid_all[dev_mask])
    pred_resid_only = m_resid.predict(Xh)          # 잔차 예측분
    pred_resid_full = pred_resid_only + pred_beta_pit  # β복원 → 최종 갭 예측

    rows = [
        ("baseline y=0", metrics(yh, pred_zero), pred_zero),
        ("baseline sign(SOX)", metrics(yh, pred_sign), pred_sign),
        ("baseline β·SOX (고정)", metrics(yh, pred_beta_fixed), pred_beta_fixed),
        ("baseline β·SOX (PIT #8)", metrics(yh, pred_beta_pit), pred_beta_pit),
        ("v2 풀모델 (직접)", metrics(yh, pred_direct), pred_direct),
        ("v2 풀모델 (잔차 #2)", metrics(yh, pred_resid_full), pred_resid_full),
    ]
    preds = {label: p for label, _, p in rows}
    return name, rows, preds, yh, n


# ----------------------------------------------------------------------------- 출력
def print_table(name, rows, n_total):
    algo = "LightGBM(v2구성)" if HAVE_LGB else "sklearn HGB"
    print(f"\n{'='*82}\n  {name}   (표본 {n_total}일, 홀드아웃 {HOLDOUT_DAYS}일, 모델={algo})\n{'='*82}")
    print(f"  {'프로토콜':<24}{'RMSE':>9}{'MAE':>9}{'방향적중':>9}{'조건부적중':>13}")
    print("  " + "-" * 78)
    for label, m, _ in rows:
        cond = f"{m['condhit']*100:5.1f}%({m['condn']})" if m["condhit"] == m["condhit"] else "   —"
        hit = f"{m['hit']*100:5.1f}%" if m["hit"] == m["hit"] else "  —"
        print(f"  {label:<24}{m['rmse']*100:8.4f}%{m['mae']*100:8.4f}%{hit:>9}{cond:>13}")


def print_inference(name, preds, yh):
    """#1 유의성 검정: 모델 vs β·SOX(PIT) 차이에 부트스트랩 CI."""
    base = preds["baseline β·SOX (PIT #8)"]
    print(f"\n  ── [{name}] #1 유의성 검정 (vs β·SOX PIT 베이스라인, 블록 부트스트랩 95% CI) ──")
    for label in ["v2 풀모델 (직접)", "v2 풀모델 (잔차 #2)"]:
        a = preds[label]
        dpt, dlo, dhi, pw = boot_rmse_diff(yh, a, base)
        hpt, hlo, hhi = boot_hit_diff(yh, a, base)
        sig = "유의(이김)" if dhi < 0 else ("유의(짐)" if dlo > 0 else "구분 불가")
        print(f"   {label}")
        print(f"     ΔRMSE = {dpt*100:+.4f}%p  CI[{dlo*100:+.4f}, {dhi*100:+.4f}]  "
              f"P(모델≥베이스)={pw:.2f}  → {sig}")
        print(f"     Δ방향적중 = {hpt*100:+.2f}%p  CI[{hlo*100:+.2f}, {hhi*100:+.2f}]")


def main():
    print("데이터 수집 중(yfinance)…  LightGBM:", "사용" if HAVE_LGB else "미설치→HGB 폴백",
          "| 외국인순매수(#9):", "사용(KRX)" if USE_SUPPLY else "스킵(자격증명 없음)")
    us, kr = fetch()
    us_lr = us_overnight(us)
    names = list(KR)
    closes = {n: kr[n]["Close"] for n in names}

    results = []
    for i, name in enumerate(names):
        other = names[1 - i]
        res = run_stock(name, kr[name], closes[other], us_lr)
        results.append(res)
        print_table(res[0], res[1], res[4])

    print(f"\n{'='*82}\n  유의성 검정 — 0.03%p는 신호인가 노이즈인가 (#1)\n{'='*82}")
    for name, rows, preds, yh, n in results:
        print_inference(name, preds, yh)

    print(f"\n{'='*82}\n  해석 가이드\n{'='*82}")
    print("  • ΔRMSE CI가 0을 포함 → '베이스라인을 이긴다' 주장 불가, '구분 불가'가 정답")
    print("  • 잔차 타깃(#2)이 직접 타깃보다 나으면 → 오버나잇 베타 제거가 학습에 도움")
    print("  • sign(SOX) 적중률 ≈ 풀모델 적중률 → 방향성은 SOX 부호가 다 설명")
    print("\n⚠️ 통계 모델 비교 실험이며 투자 권유가 아님. 백테스트가 실거래를 보장하지 않음.")


if __name__ == "__main__":
    main()
