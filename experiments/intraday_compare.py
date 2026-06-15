"""풀 피처 vs 풀+인트라데이(08:00 KST 스냅샷) 비교 — 개선점 #6 적용.

full_features_compare 의 최적 설정(잔차 타깃·rolling β 기준·4×126일 롤링 홀드아웃)을
고정하고, intraday_snapshot 의 드리프트 피처 3개(NQ·ES 야간선물, USD/KRW — 美 마감
16:00 ET → 08:00 KST)를 추가했을 때의 한계 기여를 검정한다.

주의: 시간봉 커버리지가 2024-01(NQ/ES)부터라 학습 fold 의 초기 구간과 월요일은
NaN 이다(LGBM 네이티브 처리). 윈도별 train/test 커버리지를 함께 보고한다.

실행:  python -m experiments.intraday_compare
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

from experiments.improvements_compare import (
    COSTS_BP, N_WINDOWS, WIN_LEN, block_bootstrap_ci, dm_test, fetch_naver_flows,
    fit_lgbm, make_lgbm, rolling_beta,
)
from experiments.spec_compare import COND_THR, EMBARGO, KR, WINSOR, metrics, winsorize_train
from experiments.full_features_compare import (
    build_dataset, extend_us_lr, fetch_all, fetch_dgs10, us_overnight,
)
from experiments.intraday_snapshot import INTRA_COLS, intraday_features

warnings.simplefilter("ignore")


def run_stock(name, ds, full_cols):
    y, sox = ds["y"], ds["^SOX_on"]
    beta = rolling_beta(y, sox)
    ok = beta.notna()
    ds, y, sox, beta = ds[ok], y[ok], sox[ok], beta[ok]
    n = len(ds)
    y_np = y.to_numpy()
    pred_roll = (beta * sox).to_numpy()
    resid_np = y_np - pred_roll

    sets = {"풀 피처": full_cols, "풀+인트라": full_cols + INTRA_COLS}
    oos_start = n - N_WINDOWS * WIN_LEN
    collected = {"y": [], "rollβ": []}
    cover = []
    has_intra = ds[INTRA_COLS].notna().any(axis=1).to_numpy()
    es = ds["es_drift_0800"].to_numpy(dtype=float)  # 상관 최대·유동성 최고 → γ 오버레이용
    last_model = None

    for w in range(N_WINDOWS):
        t0 = oos_start + w * WIN_LEN
        t1 = t0 + WIN_LEN
        dev, te = slice(0, t0 - EMBARGO), slice(t0, t1)
        collected["y"].append(y_np[te])
        collected["rollβ"].append(pred_roll[te])
        cover.append((has_intra[dev].mean(), has_intra[te].mean()))
        for k, cols in sets.items():
            X = ds[cols].to_numpy(dtype=float)
            m = fit_lgbm(make_lgbm(None), X[dev],
                         winsorize_train(resid_np[dev], WINSOR))
            p = pred_roll[te] + m.predict(X[te])
            collected.setdefault(k, []).append(p)
            if k == "풀+인트라" and w == N_WINDOWS - 1:
                last_model = (m, cols)
        # γ 오버레이: 드리프트는 美 마감 *후* 구간이라 일봉 피처와 시간적으로 직교
        # → 풀 피처(인트라 미포함) 예측에 선형 1계수 보정. point-in-time(dev만) 추정이라
        # 학습 커버리지가 얇아도(수십 일) 추정 가능 — LGBM이 못 쓰는 신호의 하한 측정.
        msk = np.isfinite(es[dev])
        if msk.sum() >= 30:
            x = es[dev][msk]
            gamma = float(np.dot(x, resid_np[dev][msk]) / np.dot(x, x))
        else:
            gamma = 0.0
        adj = np.where(np.isfinite(es[te]), gamma * es[te], 0.0)
        collected.setdefault("풀+인트라γ", []).append(collected["풀 피처"][-1] + adj)
        collected.setdefault("γ", []).append(np.full(WIN_LEN, gamma))

    out = {k: np.concatenate(v) for k, v in collected.items()}
    # OOS 구간의 인트라-잔차 직접 상관 (신호 자체의 세기 진단)
    te_all = slice(oos_start, n)
    diag = {}
    resid_te = (y_np - pred_roll)[te_all]
    intra_te = ds[INTRA_COLS].iloc[te_all]
    for c in INTRA_COLS:
        v = intra_te[c].to_numpy()
        msk = np.isfinite(v)
        diag[c] = (np.corrcoef(v[msk], resid_te[msk])[0, 1], int(msk.sum()))
    return out, cover, diag, last_model


def report(name, out, cover, diag, last_model):
    y = out["y"]
    e_roll = out["rollβ"] - y
    print(f"\n{'='*100}\n  {name} — 풀 피처 vs 풀+인트라(08:00 KST 드리프트 3개)"
          f" | 잔차 타깃, 롤링 홀드아웃 {N_WINDOWS}×{WIN_LEN}일\n{'='*100}")
    print("  인트라 커버리지(train/test): "
          + ", ".join(f"w{i+1} {tr*100:.0f}%/{te*100:.0f}%" for i, (tr, te) in enumerate(cover)))
    print(f"\n  {'구성':<12}{'RMSE':>9}{'MAE':>9}{'방향':>8}{'조건부':>12}"
          f"{'DM p(vs β)':>11}{'ΔRMSE 95% CI':>22}")
    print("  " + "-" * 78)
    m = metrics(y, out["rollβ"])
    print(f"  {'rolling β·SOX':<12}{m['rmse']*100:8.4f}%{m['mae']*100:8.4f}%"
          f"{m['hit']*100:7.1f}%{m['condhit']*100:6.1f}%({m['condn']}){'—':>11}{'—':>22}")
    for k in ["풀 피처", "풀+인트라", "풀+인트라γ"]:
        mm = metrics(y, out[k])
        e = out[k] - y
        _, p = dm_test(e, e_roll)
        lo, hi = block_bootstrap_ci(e, e_roll)
        print(f"  {k:<12}{mm['rmse']*100:8.4f}%{mm['mae']*100:8.4f}%{mm['hit']*100:7.1f}%"
              f"{mm['condhit']*100:6.1f}%({mm['condn']}){p:>11.3f}"
              f"{f'[{lo*100:+.3f}, {hi*100:+.3f}]':>22}")
    print("  " + "-" * 78)

    for k_new in ["풀+인트라", "풀+인트라γ"]:
        e_new, e_base = out[k_new] - y, out["풀 피처"] - y
        _, p = dm_test(e_new, e_base)
        lo, hi = block_bootstrap_ci(e_new, e_base)
        verdict = "유의한 개선" if (p == p and p < 0.05 and hi < 0) else \
                  ("유의한 악화" if (p == p and p < 0.05 and lo > 0) else "구분 불가(0 포함)")
        print(f"  인트라 한계 기여 검정 ({k_new} − 풀):  DM p={p:.3f},"
              f" ΔRMSE 95% CI [{lo*100:+.3f}, {hi*100:+.3f}] %p → {verdict}")
    gammas = out["γ"][::WIN_LEN]
    print(f"  γ̂ (ES 드리프트 계수, point-in-time, 윈도별): "
          + ", ".join(f"{g:+.2f}" for g in gammas))

    print("\n  신호 진단 — OOS 잔차(y − rollβ·SOX)와의 상관:")
    for c, (r, nn) in diag.items():
        print(f"    {c}: corr={r:+.3f} (n={nn})")

    print(f"\n  경제적 가치 — |예측|>{COND_THR*100:.1f}% 진입, 롱+숏 (상한 추정)")
    print(f"   {'구성':<12}{'거래':>6}{'적중':>8}" + "".join(f"{f'순수익@{c}bp':>14}" for c in COSTS_BP))
    for k in ["rollβ", "풀 피처", "풀+인트라", "풀+인트라γ"]:
        pr = out[k]
        msk = np.abs(pr) > COND_THR
        gross = np.sign(pr[msk]) * y[msk]
        cells = "".join(f"{(gross - c/1e4).sum()*100:+9.1f}%p     " for c in COSTS_BP)
        print(f"   {k:<12}{int(msk.sum()):>6}{np.mean(gross>0)*100:>7.1f}%{cells}")

    m, cols = last_model
    imp = pd.Series(m.booster_.feature_importance("gain"), index=cols)
    tot = imp.sum()
    top = imp.sort_values(ascending=False).head(12)
    print("\n  피처 중요도 top12 (gain, 마지막 윈도): "
          + ", ".join(f"{c}({v/tot*100:.0f}%)" for c, v in top.items()))
    intra_imp = imp[INTRA_COLS] / tot * 100
    print("  인트라 피처 중요도: " + ", ".join(f"{c} {v:.1f}%" for c, v in intra_imp.items()))


def main():
    print("데이터 수집 중(yfinance 일봉+시간봉 + FRED + 수급)…")
    us, kr, kospi = fetch_all()
    us_lr_ext = extend_us_lr(us_overnight(us), fetch_dgs10())
    names = list(KR)
    closes = {nm: kr[nm]["Close"] for nm in names}
    flows = {nm: fetch_naver_flows(KR[nm].split(".")[0]) for nm in names}

    for i, name in enumerate(names):
        ds, star_cols, full_cols = build_dataset(
            name, kr[name], closes[names[1 - i]], us_lr_ext, flows[name], kospi)
        ds = ds.join(intraday_features(ds.index))
        out, cover, diag, last_model = run_stock(name, ds, full_cols)
        report(name, out, cover, diag, last_model)

    print("\n⚠️ 통계 모델 비교 실험이며 투자 권유가 아님. 백테스트 성과는 실거래를 보장하지 않음.")


if __name__ == "__main__":
    main()
