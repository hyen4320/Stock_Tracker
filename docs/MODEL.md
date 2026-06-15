# 모델 명세 — 입력 파라미터 · 모델 구성

이 문서는 예측 모델에 **무엇이 입력되고(파라미터), 어떤 모델로 학습/예측하는지(구성)**를
코드 기준으로 정리한다. 관련 코드: `config.py`, `src/features.py`, `src/model.py`,
`src/predict.py`. 전체 데이터→화면 흐름은 [ARCHITECTURE.md](./ARCHITECTURE.md) 참고.

---

## 1. 입력 파라미터 (피처) — 종목당 **9개**

모델은 종목별로 따로 학습되며, 각 모델의 입력 피처는 9개다.

| # | 피처 | 의미 | 실시간 주입 |
|---|------|------|:----------:|
| 1 | `SOX_ret` | SOX 당일(D) 수익률 | ✅ |
| 2 | `SOX_ret_lag1` | SOX 1일 전 수익률 | — |
| 3 | `SOX_ret_lag2` | SOX 2일 전 수익률 | — |
| 4 | `USDKRW_ret` | 원/달러 당일(D) 수익률 | ✅ |
| 5 | `USDKRW_ret_lag1` | 환율 1일 전 수익률 | — |
| 6 | `USDKRW_ret_lag2` | 환율 2일 전 수익률 | — |
| 7 | `{종목}_ret` | 종목 자체 당일 수익률(모멘텀) | — |
| 8 | `{종목}_ret_lag1` | 종목 1일 전 수익률 | — |
| 9 | `{종목}_ret_lag2` | 종목 2일 전 수익률 | — |

- **드라이버(설명변수) 6개**: SOX·환율의 당일 + 1·2일 시차 수익률
- **종목 자체 모멘텀 3개**: 해당 종목 종가 수익률의 당일 + 1·2일 시차

### 피처 개수 공식

```
피처 수 = (1 + len(LAGS)) × (len(DRIVERS) + 1)
        = (1 + 2)        × (2          + 1)   = 9
```

`config.py`로 조절된다:

| 설정 변경 | 결과 |
|-----------|------|
| `LAGS = [1, 2, 3]` | `4 × 3 = 12개` |
| `DRIVERS`에 지수 1개 추가 | `3 × 4 = 12개` |
| 둘 다 | `4 × 4 = 16개` |

> 정의 위치: `src/features.py`의 `build_feature_frame()`. 시차 목록은 `config.LAGS = [1, 2]`,
> 드라이버는 `config.DRIVERS = {"SOX": "^SOX", "USDKRW": "KRW=X"}`.

### 실시간 주입 가능한 건 2개뿐

밤사이 실제 변동을 반영할 때 덮어쓸 수 있는 피처는 **`SOX_ret`, `USDKRW_ret`** 2개다
(`src/features.py`의 `latest_feature_row`). 나머지 7개는 과거 확정값이라 고정.

```python
latest_feature_row(data, "삼성전자", sox_live_ret=0.02, fx_live_ret=-0.003)
#  → SOX_ret 자리를 +2.0%, USDKRW_ret 자리를 -0.3%로 덮어써서 실시간 추정
```

---

## 2. 타깃 (예측 대상 y) — 1개

입력 9개로 **다음날 시초가 갭** 하나를 예측한다 (회귀).

```
target_gap = Open[D+1] / Close[D] - 1      # 종가[D] → 다음날 시초가[D+1] 갭 수익률
```

**시간대 정렬**이 핵심이다 — 한국 마감(D) 이후 같은 날짜의 미국 SOX 세션이 밤새 거래되고,
그 결과가 다음날(D+1) 한국 시초가 갭으로 나타난다. 모든 피처는 D+1 시초가 시점에 알 수
있는 정보만 사용해 **미래 정보 누수를 방지**한다.

---

## 3. 모델 구성

### 알고리즘

**scikit-learn `HistGradientBoostingRegressor`** (그래디언트 부스팅 회귀)
— 추가 의존성 없이 견고하고, 결측치를 자체 처리한다.

### 하이퍼파라미터 (`src/model.py`의 `_new_model()`)

| 파라미터 | 값 | 의미 |
|----------|-----|------|
| `max_iter` | `300` | 부스팅 반복(트리) 수 |
| `learning_rate` | `0.05` | 학습률 |
| `max_depth` | `3` | 트리 최대 깊이 (과적합 억제) |
| `l2_regularization` | `1.0` | L2 정규화 |
| `random_state` | `42` | 재현성 (`config.RANDOM_STATE`) |

> 위 5개는 **모델 하이퍼파라미터**로, 1절의 **입력 피처(9개)**와는 다른 개념이다.
> 피처 = 모델에 들어가는 데이터, 하이퍼파라미터 = 모델 학습 방식 설정.

### 종목별 개별 모델

종목마다 **별도 모델**을 학습해 저장한다.

```
models/삼성전자.joblib      # {"model": <학습된 모델>, "features": [피처 9개 이름]}
models/SK하이닉스.joblib
```

### 학습 데이터

| 항목 | 값 |
|------|-----|
| 데이터 소스 | yfinance (무료·API 키 불필요) |
| 기간 | `HISTORY_PERIOD = "5y"` (5년 일봉) |
| 전처리 | 시차로 인한 앞쪽 결측, 다음날 시초가 없는 끝 행을 `dropna` (`make_xy`) |

### 검증 (`train()`)

시계열이므로 **`TimeSeriesSplit` 5-fold**로 과거→미래 순서를 지키며 검증한다.

- 지표: **MAE**(평균절대오차)
- 베이스라인: **"갭 0%(변동 없음)"** 예측 — 이걸 이겨야 의미 있는 모델

`train()` 반환 예시:

```python
{
  "target": "삼성전자",
  "n_samples": 1158,
  "cv_mae": 0.0091,         # 0.91%
  "baseline_mae": 0.0105,   # 1.05%
  "improvement_pct": 13.0,  # 베이스라인 대비 개선율(%)
}
```

---

## 4. 예측 출력 (`src/predict.py`)

모델은 "갭 수익률"을 내놓고, 이를 사람이 읽는 가격으로 변환한다.

```
estimated_open = last_close × (1 + predicted_gap)
```

`predict_open()` 반환 예시:

```python
{
  "target": "삼성전자",
  "last_close": 319500,        # 최근 종가
  "predicted_gap": 0.0158,     # 예측 갭 +1.58%
  "estimated_open": 324541,    # = 319500 × (1 + 0.0158)
  "change": 5041,              # 예상 변동액
}
```

---

## 5. 요약 한 장

| 구분 | 개수/값 | 설명 |
|------|---------|------|
| **입력 피처** | **9개** | 드라이버 6 (SOX·환율 ×{당일,lag1,lag2}) + 종목 모멘텀 3 |
| 실시간 주입 피처 | 2개 | `SOX_ret`, `USDKRW_ret` |
| 타깃 | 1개 | `target_gap` (종가[D]→시초가[D+1] 갭) |
| 모델 | 종목당 1개 | `HistGradientBoostingRegressor` |
| 하이퍼파라미터 | 5개 | max_iter=300, lr=0.05, max_depth=3, l2=1.0, seed=42 |
| 검증 | 5-fold | TimeSeriesSplit · MAE · zero-gap 베이스라인 |

---

## 참고: 프론트 시뮬레이터의 β는 별개

`frontend/src/lib/meta.js`의 SOX/환율 민감도 **β는 표시용 상수**(예시값)이며, 위 9-피처
모델과 직접 연결돼 있지 않다. 시뮬레이터는 `gap = base + βSOX·sox + βFX·fx`라는 단순
선형식으로 빠른 what-if를 보여줄 뿐이다. 실제 모델 반응도로 바꾸려면 백엔드가 종목별 β
(또는 피처 기여도)를 별도 엔드포인트로 노출해야 한다.
