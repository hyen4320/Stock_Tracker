"""v1 스펙 vs v2 스펙 — *모델 파라미터* 효과 비교 (SPEC_IMPROVEMENTS #3).

기존 spec_compare.py 는 측정 프로토콜(정렬/분할/홀드아웃)만 토글했고 모델은
sklearn HGB 하나로 고정했다. 따라서 "추가 피처의 한계 엣지 작다"는 결론은
v2 스펙의 *모델링* 개선(§7.2 huber·단조제약·num_leaves 31→15·min_child 30→50)
을 적용하지 않은 상태의 주장이었다.

이 스크립트는 반대로 **측정 프로토콜을 v2(정직)로 고정**하고 모델만 토글한다:

  HGB(참조)      spec_compare.py 의 모델 — 기존 실험과의 연결 고리
  LGBM v1 파라미터  v1 §7.2: l2, num_leaves=31, min_child=30, reg_lambda=1.0
  LGBM v2 파라미터  v2 §7.2: huber, num_leaves=15, min_child=50,
                  reg_lambda=5.0, reg_alpha=1.0, monotone_constraints

공통 측정 규칙 (전 모델 동일 — v2 §4, §5, §6, §1-9)
  정렬     available_at 기반 strict-backward (직전 밤 美 세션만)
  분할     dev / 최근 252일 홀드아웃 격리, CV는 TimeSeriesSplit(gap=5)
  타깃     학습 fold에서만 winsorize(1%/99%)
  조기종료 성능 측정 셋과 분리 — 학습 구간 꼬리 15%를 ES 전용으로 떼어 사용 (v2 §7.2)

단조 제약은 "명백한 방향만"(v2 §7.2): 美 주식/지수/선물 수익률 ↑ → 갭 ↑ (+1),
VIX ↑ → 갭 ↓ (-1), 나머지(자기시계열·FX·DXY)는 무제약(0).

주의: 스펙 코드의 subsample=0.8 은 LightGBM에서 subsample_freq 없이는 비활성이라
두 LGBM 구성 모두 subsample_freq=1 을 부여했다(동일 적용이므로 비교 공정).

실행:  python -m experiments.model_compare
"""
from __future__ import annotations

import sys
import warnings

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import lightgbm as lgb
import numpy as np
from sklearn.model_selection import TimeSeriesSplit

from experiments.spec_compare import (
    EMBARGO, HOLDOUT_DAYS, KR, RANDOM_STATE, US_COMMON, US_SPECIFIC, WINSOR,
    assemble, beta_sox_baseline, fetch, metrics, new_model as hgb_model,
    us_overnight, winsorize_train,
)

warnings.simplefilter("ignore")

ES_FRAC = 0.15        # 학습 구간 꼬리 → early-stopping 전용 (측정 셋과 분리, v2 §6)
ES_ROUNDS = 100

SELF_COLS = ["self_ret_prev", "self_gap_prev", "self_range_prev",
             "self_volz_prev", "cross_ret_prev"]

# 단조 제약 방향 (피처 베이스 티커 → 제약). 명백한 것만.
MONO_DIR = {
    "^SOX": +1, "MU": +1, "NVDA": +1, "AVGO": +1, "^IXIC": +1, "^GSPC": +1,
    "NQ=F": +1, "ES=F": +1, "TSM": +1, "QCOM": +1,
    "^VIX": -1,
    # KRW=X, DX-Y.NYB: 방향이 국면 의존 → 무제약
}


def lgbm_v1():
    """v1 스펙 §7.2 그대로."""
    return lgb.LGBMRegressor(
        n_estimators=2000, learning_rate=0.02, num_leaves=31,
        subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
        reg_lambda=1.0, min_child_samples=30,
        random_state=RANDOM_STATE, verbosity=-1,
    )


def lgbm_v2(mono: list[int], objective="huber", leaves=15, min_child=50,
            reg_lambda=5.0, reg_alpha=1.0):
    """v2 스펙 §7.2 그대로 (huber + 단조제약 + 강화 정규화). 키워드로 ablation."""
    return lgb.LGBMRegressor(
        objective=objective,
        n_estimators=3000, learning_rate=0.02,
        num_leaves=leaves, min_child_samples=min_child,
        subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
        reg_lambda=reg_lambda, reg_alpha=reg_alpha,
        monotone_constraints=mono,
        random_state=RANDOM_STATE, verbosity=-1,
    )


def mono_vector(feat_cols: list[str]) -> list[int]:
    out = []
    for c in feat_cols:
        base = c[:-3] if c.endswith("_on") else c
        out.append(MONO_DIR.get(base, 0))
    return out


def fit_lgbm(model, Xtr, ytr):
    """학습 구간 꼬리를 ES 셋으로 분리해 적합 (측정 셋 미접촉)."""
    k = max(int(len(Xtr) * ES_FRAC), 50)
    model.fit(
        Xtr[:-k], ytr[:-k],
        eval_set=[(Xtr[-k:], ytr[-k:])],
        callbacks=[lgb.early_stopping(ES_ROUNDS, verbose=False),
                   lgb.log_evaluation(0)],
    )
    return model


def cv_score(make_model, X, y, is_lgbm: bool):
    """v2 정직 CV: gap=embargo, 학습 fold에서만 winsorize."""
    tscv = TimeSeriesSplit(n_splits=5, gap=EMBARGO)
    preds, trues = [], []
    for tr, va in tscv.split(X):
        ytr = winsorize_train(y[tr], WINSOR)
        m = make_model()
        if is_lgbm:
            fit_lgbm(m, X[tr], ytr)
        else:
            m.fit(X[tr], ytr)
        preds.append(m.predict(X[va]))
        trues.append(y[va])
    return metrics(np.concatenate(trues), np.concatenate(preds))


def holdout_score(make_model, Xdev, ydev, Xh, yh, is_lgbm: bool):
    ytr = winsorize_train(ydev, WINSOR)
    m = make_model()
    if is_lgbm:
        fit_lgbm(m, Xdev, ytr)
    else:
        m.fit(Xdev, ytr)
    return metrics(yh, m.predict(Xh)), m


def run_stock(name, d, other_close, us_lr):
    us_cols = [f"{t}_on" for t in US_COMMON + US_SPECIFIC[name]]
    feat_cols = SELF_COLS + us_cols
    mono = mono_vector(feat_cols)

    # 측정 프로토콜은 v2 고정: strict-backward 정렬만 사용
    ds = assemble(name, d, other_close, us_lr, us_cols, exact=False).dropna(subset=feat_cols)
    X = ds[feat_cols].to_numpy()
    y = ds["y"].to_numpy()
    sox = ds["^SOX_on"].to_numpy()
    Xdev, ydev = X[:-HOLDOUT_DAYS], y[:-HOLDOUT_DAYS]
    Xh, yh = X[-HOLDOUT_DAYS:], y[-HOLDOUT_DAYS:]
    soxd, soxh = sox[:-HOLDOUT_DAYS], sox[-HOLDOUT_DAYS:]

    no_mono = [0] * len(feat_cols)
    configs = [
        # (라벨, 팩토리, is_lgbm, CV도 수행?)
        ("HGB(기존 실험)", hgb_model, False, True),
        ("LGBM v1 파라미터", lgbm_v1, True, True),
        ("LGBM v2 파라미터", lambda: lgbm_v2(mono), True, True),
        # ── ablation: v2 구성요소를 하나씩 끄기 (홀드아웃만) ──
        ("v2 −huber(→l2)", lambda: lgbm_v2(mono, objective="regression"), True, False),
        ("v2 −단조제약", lambda: lgbm_v2(no_mono), True, False),
        ("v2 −강정규화(v1수준)", lambda: lgbm_v2(mono, leaves=31, min_child=30,
                                            reg_lambda=1.0, reg_alpha=0.0), True, False),
    ]

    rows = [
        ("baseline y=0", metrics(yh, np.zeros_like(yh)), None),
        ("baseline β·SOX", metrics(yh, beta_sox_baseline(soxd, ydev, soxh)), None),
    ]
    for label, make, is_lgbm, do_cv in configs:
        if do_cv:
            rows.append((f"{label} CV", cv_score(make, Xdev, ydev, is_lgbm), None))
        ho, m = holdout_score(make, Xdev, ydev, Xh, yh, is_lgbm)
        it = getattr(m, "best_iteration_", None)
        rows.append((f"{label} 홀드아웃", ho, it))
    return rows, len(ds)


def print_table(name, rows, n_total):
    print(f"\n{'='*84}\n  {name}   (표본 {n_total}일, 홀드아웃 {HOLDOUT_DAYS}일, 측정 프로토콜 = v2 고정)\n{'='*84}")
    print(f"  {'구성':<24}{'RMSE':>10}{'MAE':>10}{'방향적중':>10}{'조건부적중':>13}{'ES반복':>8}")
    print("  " + "-" * 80)
    for label, m, it in rows:
        cond = f"{m['condhit']*100:5.1f}%({m['condn']})" if m["condhit"] == m["condhit"] else "      —"
        hit = f"{m['hit']*100:5.1f}%" if m["hit"] == m["hit"] else "    —"
        itx = f"{it}" if it is not None else "—"
        print(f"  {label:<24}{m['rmse']*100:9.4f}%{m['mae']*100:9.4f}%{hit:>10}{cond:>13}{itx:>8}")
    print("  " + "-" * 80)


def main():
    print("데이터 수집 중(yfinance)…")
    us, kr = fetch()
    us_lr = us_overnight(us)
    names = list(KR)
    closes = {n: kr[n]["Close"] for n in names}

    summary = []
    for i, name in enumerate(names):
        rows, n_total = run_stock(name, kr[name], closes[names[1 - i]], us_lr)
        print_table(name, rows, n_total)
        summary.append((name, rows))

    print(f"\n{'='*84}\n  요약 — 모델링 효과 (홀드아웃 RMSE, 측정 프로토콜 동일)\n{'='*84}")
    for name, rows in summary:
        d = {label: m for label, m, _ in rows}
        bs = d["baseline β·SOX"]["rmse"]
        hgb = d["HGB(기존 실험) 홀드아웃"]["rmse"]
        l1 = d["LGBM v1 파라미터 홀드아웃"]["rmse"]
        l2 = d["LGBM v2 파라미터 홀드아웃"]["rmse"]
        print(f"\n  [{name}]")
        print(f"   β·SOX 베이스라인     {bs*100:.4f}%")
        print(f"   HGB(기존 실험)       {hgb*100:.4f}%  (β·SOX 대비 {(bs-hgb)/bs*100:+.1f}%)")
        print(f"   LGBM v1 파라미터     {l1*100:.4f}%  (β·SOX 대비 {(bs-l1)/bs*100:+.1f}%)")
        print(f"   LGBM v2 파라미터     {l2*100:.4f}%  (β·SOX 대비 {(bs-l2)/bs*100:+.1f}%)")
        gain = (l1 - l2) / l1 * 100
        print(f"   → v2 모델링(huber·단조제약·강정규화) 효과: v1 파라미터 대비 {gain:+.1f}%")
        for ab in ["v2 −huber(→l2)", "v2 −단조제약", "v2 −강정규화(v1수준)"]:
            r = d[f"{ab} 홀드아웃"]["rmse"]
            print(f"   ablation {ab:<18} {r*100:.4f}%  (v2 풀구성 대비 {(l2-r)/l2*100:+.1f}%)")

    print("\n⚠️ 통계 모델 비교 실험이며 투자 권유가 아님. 백테스트 성과는 실거래를 보장하지 않음.")


if __name__ == "__main__":
    main()
