# 반도체 시초가 예측 모델 — 프로젝트 명세 (for Claude Code)

> 이 문서는 Claude Code가 읽고 코드를 스캐폴딩·구현하기 위한 명세서다.
> 목표, 데이터 수집 방법, 피처 정의, **절대 규칙(룩어헤드 차단)**, 파일 구조,
> 구현 순서를 정의한다. 라이브러리 API는 버전에 따라 바뀌므로, 구현 시
> 각 라이브러리의 현재 docs를 확인하고 함수 시그니처를 검증할 것.

---

## 0. 목표 (Objective)

- **삼성전자(005930)** 와 **SK하이닉스(000660)** 의 **다음 거래일 시초가(개장가)** 를 예측한다.
- 예측 대상은 시초가 절대가격이 아니라 **갭(gap)** 이다:
  ```
  y = log(open[D] / close[D-1])     # 거래일 D의 시초가 갭 (종목별)
  ```
- 모든 입력 피처는 거래일 D의 장 시작(09:00 KST) **이전에 확정된 정보만** 사용한다.

> 참고: 이 프로젝트는 모델링 방법론이며 투자 조언이 아니다. 백테스트 성과가
> 실거래 수익을 보장하지 않는다.

---

## 1. 절대 규칙 (Hard Rules — 위반 금지)

이 규칙들은 성능보다 우선한다. 하나라도 어기면 결과 전체가 무효다.

1. **룩어헤드 금지.** 거래일 D의 시초가 예측에는 D의 08:59 KST 이전에 확정된
   값만 쓴다. 예측일 당일 장중 데이터, 당일 종가, 당일 수급 등은 절대 피처에
   넣지 않는다.
2. **정렬은 `available_at` 타임스탬프 + `merge_asof(direction="backward")` 로만 한다.**
   날짜 단순 join 금지 (시차/날짜경계에서 미래정보가 샌다).
3. **스케일러·통계량(평균/표준편차/분위수)은 학습 구간에서만 `fit`,**
   검증·테스트엔 `transform` 만 적용한다.
4. **시계열 분할만 사용.** 무작위 K-fold 금지. Walk-forward + embargo(gap) 사용.
5. **나이브 베이스라인을 반드시 구현하고 모든 모델을 이와 비교한다.**
   베이스라인을 못 이기면 피처/설계 문제로 간주한다.

---

## 2. 데이터 수집 (Collection)

무료 소스로 대부분 수집 가능. 각 소스의 **정보 확정 시각(available_at)** 을
함께 기록해야 한다(§4 정렬에서 사용).

| 데이터 | 소스(라이브러리) | 식별자/메모 | available_at (KST 기준) |
|---|---|---|---|
| 한국 OHLCV | `pykrx` 또는 `FinanceDataReader` | 005930, 000660 | 해당일 장마감(15:30) 후 |
| 한국 투자자별 순매수(외국인/기관/개인) | `pykrx` | 종목별 거래대금/거래량 by investor | 해당일 장마감 후 |
| 신용잔고/반대매매/미수 | KRX 정보데이터시스템(data.krx.co.kr) 또는 금투협 freesis | pykrx 커버리지 제한적 | 약 T+2 공시 (보수적으로 잡을 것) |
| 美 개별주(공통) | `yfinance` | MU, NVDA, AVGO, AMD, MRVL, ASML, AMAT, LRCX, KLAC | 美 정규장 종가 → 익일 새벽 05~06시 |
| 美 개별주(하이닉스) | `yfinance` | SNDK(=구 WDC NAND, 2025.2 분사), 키오시아 `6600.T`(선택) | 동일 / 일본장 마감 후 |
| 美 개별주(삼성) | `yfinance` | TSM, QCOM, AAPL | 동일 |
| 미국 지수 | `yfinance` | `^SOX`, `^IXIC`, `^GSPC`, `^VIX` | 동일 |
| 야간 선물 | `yfinance` | `NQ=F`, `ES=F` | 한국 장 시작 직전까지 갱신 |
| 달러인덱스 | `yfinance` | `DX-Y.NYB` | 동일 |
| 환율 USD/KRW | `yfinance` | `KRW=X` (초기엔 이걸로 충분, 정밀 NDF는 유료) | 연속 |
| 미국 10년물 금리 | FRED (`fredapi`/`pandas_datareader`) | `DGS10` | 美 영업일 |
| 한국 금리 | 한국은행 ECOS API | 국고채 3Y/10Y | 해당일 |
| 캘린더(만기일·실적·휴장) | 룰 생성 + KRX 휴장일 | 선물옵션 만기일=분기 둘째 목요일 등 | 사전 확정 |

수집 예시:
```python
import yfinance as yf
import pandas_datareader.data as web
import FinanceDataReader as fdr

US_COMMON   = "MU NVDA AVGO AMD MRVL ASML AMAT LRCX KLAC"          # 둘 다
US_HYNIX    = "SNDK"                                                # 하이닉스 특화(NAND). 키오시아 6600.T는 별도
US_SAMSUNG  = "TSM QCOM AAPL"                                       # 삼성 특화(파운드리/시스템/모바일)
US_MACRO    = "^SOX ^VIX DX-Y.NYB NQ=F ES=F"
US_TICKERS  = " ".join([US_COMMON, US_HYNIX, US_SAMSUNG, US_MACRO])
us  = yf.download(US_TICKERS, start="2016-01-01")["Close"]
fx  = yf.download("KRW=X", start="2016-01-01")["Close"]
dgs10 = web.DataReader("DGS10", "fred", "2016-01-01")

sam = fdr.DataReader("005930", "2016-01-01")   # 삼성전자
hyx = fdr.DataReader("000660", "2016-01-01")   # SK하이닉스
# 수급: pykrx.stock.get_market_trading_value_by_date 등 (현재 docs로 함수명 확인)
```

---

## 3. 피처 카탈로그 (Feature Catalog)

우선순위: **★필수 / ◆보강 / ○실험적(SHAP 검증 후 채택)**.
구현은 ★ → ◆ → ○ 순서로, 각 단계마다 성능을 기록한다.

| 분류 | 피처 | 가공 방식 / 메모 | 우선순위 |
|---|---|---|---|
| 기준 | SOX 수익률 | 전일 log return. 개별주와 중복 → 가급적 (MU−SOX) 상대강도로 | ★ |
| 기준 | USD/KRW | 전일 변화율. A/B 비교 공통 통제변수 | ★ |
| 美 개별주·공통 | MU(마이크론) | 전일 log return. DRAM/NAND/HBM 직접 피어 | ★ |
| 美 개별주·공통 | NVDA(엔비디아) | HBM 수요 동인. 하이닉스에 더 직접적 | ★ |
| 美 개별주·공통 | AVGO(브로드컴) | AI 가속기 수요·섹터 심리 | ★ |
| 美 개별주·공통 | AMD | AI GPU 수요 | ◆ |
| 美 개별주·공통 | MRVL(마벨) | 커스텀 실리콘/HBM 인접 수요 | ◆ |
| 美 개별주·공통 | 장비군 ASML/AMAT/LRCX/KLAC | 메모리 캐펙스 사이클(인덱스화 가능) | ◆ |
| 美 개별주·공통 | (MU − SOX) 상대강도 | 메모리 다이버전스, 공선성↓ | ◆ |
| 美 개별주·하이닉스 | SNDK(샌디스크) | NAND·엔터프라이즈 SSD 피어(Solidigm 대응). 2025.2 WDC서 분사된 순수 NAND社 | ◆ |
| 美 개별주·하이닉스 | NVDA 가중↑ | HBM 최대 공급사라 공통 대비 민감도 큼(가중 또는 별도 피처) | ★ |
| 美 개별주·하이닉스 | 6600.T(키오시아) | NAND 순수, 日 상장. 정렬 번거로우면 생략 | ○ |
| 美 개별주·삼성 | TSM(TSMC) | 파운드리 직접 경쟁(삼성 only). 하이닉스엔 일반 벨웨더 수준 | ★ |
| 美 개별주·삼성 | QCOM(퀄컴) | 파운드리 고객 + System LSI(Exynos)·모바일 AP 경쟁 | ◆ |
| 美 개별주·삼성 | AAPL(애플) | 최대 고객(메모리·OLED)+스마트폰 경쟁. SOX 외, 순수 반도체 신호 희석 주의 | ○ |
| 美 지수·매크로 | 나스닥/S&P 종가 + 야간선물(NQ=F,ES=F) | 갭 방향 | ★ |
| 美 지수·매크로 | VIX | 변동성·갭 크기 | ◆ |
| 美 지수·매크로 | DXY(DX-Y.NYB) | 신흥국 자금유출 대리 | ◆ |
| 美 지수·매크로 | 美 10년물(DGS10) | 밸류에이션 | ◆ |
| 한국 수급 | 외국인 순매수(전일/누적) | 대형주 최강 신호. lag 필수 | ★ |
| 한국 수급 | 기관 순매수 | lag | ◆ |
| 한국 수급 | 개인 순매수 | 역추세 보완 | ◆ |
| 한국 수급 | 프로그램 매매 | | ○ |
| 한국 시장 | KOSPI 전일종가 + KOSPI200 야간선물 | | ◆ |
| 한국 시장 | 거래대금(전일·MA 대비 비율) | 유동성/증폭 | ◆ |
| 한국 시장 | 한국 금리(3Y/10Y) | | ○ |
| 자금 로테이션 | 반도체업종 vs KOSPI 상대수익률 | 국면 의존, 노이즈↑ | ○ |
| 자금 로테이션 | vs 경쟁테마(2차전지 등) 상대수익률 | | ○ |
| 자금 로테이션 | 시장 전체 반대매매·미수 금액 | risk-off 대리(시장 전체값) | ○ |
| 레버리지 | 신용잔고율(종목별) | 대형주라 효과 제한적, ~T+2 lag | ○ |
| 레버리지 | 신용잔고 증감률 | 취약성·심리 | ○ |
| 자기 시계열 | 전일 종가·갭·고저폭·거래량 | | ★ |
| 자기 시계열 | MA(5/20/60)·RSI·MACD·볼린저 | | ◆ |
| 자기 시계열 | 실현변동성 / GARCH | | ◆ |
| 자기 시계열 | 교차 종목 신호(삼전↔하이닉스) | 서로 피처로 투입 | ◆ |
| 캘린더 | 요일·월 더미 | | ◆ |
| 캘린더 | 선물옵션 만기일(네 마녀의 날) 더미 | | ◆ |
| 캘린더 | 실적발표 전후 더미 | | ◆ |
| 캘린더 | 지수 리밸런싱일 / 연휴직후 갭 더미 | | ○ |

> **종목별 피처 적용 규칙.** 美 개별주는 사업 구조 차이로 종목별 연관도가 다르다.
> SK하이닉스 = 순수 메모리 + HBM 1위 + Solidigm(NAND). 삼성전자 = 메모리 +
> 파운드리 + 시스템LSI + 디스플레이 + 모바일.
> - **옵션 A(종목별 모델 2개):** 하이닉스 모델 = `공통 + 하이닉스 특화`,
>   삼성 모델 = `공통 + 삼성 특화` 로 피처 세트를 분리한다.
> - **옵션 B(풀링 단일 모델):** 전체 피처 + 종목 ID(0/1) 투입. 특화 피처는
>   `특화피처 × 종목ID` 교차항으로 만들어, 해당 종목에서만 활성화되게 한다.
> - `TSM`은 삼성의 파운드리 직접 경쟁사이므로 삼성 특화. 단 섹터 벨웨더 성격이
>   있어 하이닉스 모델엔 낮은 우선순위(○)로만 선택 투입 가능.
> - `NVDA`는 공통이지만 하이닉스(HBM 최대 공급사) 민감도가 더 크므로,
>   하이닉스 모델에서는 가중치를 키우거나 별도 lag 피처를 추가한다.

---

## 4. 정렬 로직 (Alignment — 핵심)

모든 소스를 `(available_at[UTC], value...)` 형태로 만든 뒤, 예측일 D의
08:59 KST 컷오프 기준으로 backward merge 한다. 이것으로 시차·날짜경계
문제와 룩어헤드를 동시에 해결한다.

```python
import pandas as pd

# kr_dates: 예측 대상 한국 거래일 인덱스 (DatetimeIndex)
cutoff = (kr_dates.tz_localize("Asia/Seoul").normalize()
          + pd.Timedelta(hours=8, minutes=59)).tz_convert("UTC")
cutoff = pd.Series(cutoff, name="asof").to_frame().reset_index(names="kr_date")

def attach(base, source_df):
    # source_df: columns = ["available_at"(UTC, tz-aware), <feature cols...>]
    s = source_df.sort_values("available_at")
    return pd.merge_asof(base.sort_values("asof"), s,
                         left_on="asof", right_on="available_at",
                         direction="backward")

# available_at 잡는 기준 (보수적으로):
#  - 美 정규장 종가:  해당 美거래일의 21:00 UTC (≈ 06:00 KST 익일) 근사
#  - 한국 장마감 데이터(수급/종가): 해당일 06:30 UTC (15:30 KST)
#  - 신용잔고: 공시 지연 반영해 +2 영업일 시점으로 설정
```

> 구현 주의: `available_at` 을 절대 낙관적으로 잡지 말 것. 애매하면 늦게 잡는다.

---

## 5. 피처 엔지니어링 & 타깃

- 가격류는 전부 **log return** 으로 변환.
- 롤링 피처(MA/RSI/실현변동성)는 과거 윈도우만 사용(미래 미포함).
- 상대강도 = `ret(MU) - ret(SOX)` 식으로 생성.
- 캘린더 더미 생성.
- 타깃:
  ```python
  y_sam = np.log(open_sam / close_sam.shift(1))
  y_hyx = np.log(open_hyx / close_hyx.shift(1))
  ```
- 종목 처리: **(A) 종목별 모델 2개** 또는 **(B) 종목 ID를 피처로 한 풀링 단일 모델**.
  공통 피처가 많으므로 (B) 풀링을 기본 권장, (A)와 비교.

---

## 6. 데이터 분할 (Validation)

- `sklearn.model_selection.TimeSeriesSplit(n_splits=5, gap=2)` — `gap` 이 embargo.
- 더 엄격히 하려면 분할 경계 전후로 롤링 윈도우 길이만큼 추가 embargo.
- **최종 테스트셋**: 가장 최근 구간(예: 마지막 6~12개월)을 떼어 절대 학습/튜닝에 쓰지 않는다.

---

## 7. 모델 (Model)

### 7.1 베이스라인 (먼저 구현)
- `y_hat = 0` (랜덤워크)
- `y_hat = beta * ret_SOX[D-1]` (단순 선형)
- 선형회귀(★피처만)

### 7.2 주력: LightGBM (권장)
```python
import lightgbm as lgb
from sklearn.model_selection import TimeSeriesSplit

tscv = TimeSeriesSplit(n_splits=5, gap=2)
for tr, va in tscv.split(X):
    model = lgb.LGBMRegressor(
        n_estimators=2000, learning_rate=0.02, num_leaves=31,
        subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0, min_child_samples=30,
    )
    model.fit(X.iloc[tr], y.iloc[tr],
              eval_set=[(X.iloc[va], y.iloc[va])],
              callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)])
```

### 7.3 (선택) 시계열 NN
LSTM/TFT는 데이터가 충분(수천 행+)하고 시퀀스 구조를 직접 학습시키고 싶을 때만.
일별·lag피처 기준으론 GBM 대비 이득이 작고 과적합 관리가 어려움 → 후순위.

---

## 8. 평가 (Evaluation)

- 회귀 지표: RMSE/MAE(갭 기준), R².
- 실용 지표: **방향 적중률(상승/하락 hit rate)** — 트레이딩 관점에서 더 중요.
- **모든 지표를 §7.1 베이스라인과 비교** (표로 출력).
- 백테스트 시 거래비용·슬리피지 반영(미반영 시 성과 과대평가).
- SHAP/permutation importance 로 ○티어 피처 기여도 확인 후 채택/제거.

---

## 9. 권장 프로젝트 구조

```
semiconductor-open-predict/
├── README.md                  # 이 명세
├── requirements.txt
├── config.py                  # 티커/종목코드/기간/경로/우선순위 토글
├── src/
│   ├── collect.py             # §2 수집 (pykrx/fdr/yfinance/fred)
│   ├── align.py               # §4 available_at + merge_asof 정렬
│   ├── features.py            # §3,§5 피처 생성 (★/◆/○ 토글)
│   ├── dataset.py             # §5 타깃 생성 + 학습셋 조립 + (fold별)스케일링
│   ├── model.py               # §7 baseline + LightGBM walk-forward
│   └── evaluate.py            # §8 지표/베이스라인 비교/SHAP
├── data/                      # 원천·중간 캐시 (gitignore)
└── notebooks/                 # (선택) 탐색용
```

`requirements.txt` 초안:
```
pandas
numpy
scikit-learn
lightgbm
shap
yfinance
finance-datareader
pykrx
pandas-datareader
```

---

## 10. 구현 순서 (Task Checklist for Claude Code)

1. [ ] `config.py` 작성: 티커/종목코드/기간/출력경로/피처 우선순위 플래그.
2. [ ] `collect.py`: 각 소스 수집 함수 + `available_at` 컬럼 부여 + 캐시 저장.
3. [ ] `align.py`: §4 컷오프 생성 + `attach()` 로 전 소스 backward merge.
4. [ ] `features.py`: ★피처부터 구현 (log return, 자기시계열, 외국인수급, 美 핵심 4종목, 환율).
5. [ ] `dataset.py`: 타깃 생성 + 종목 풀링/분리 옵션 + fold 내부 스케일링 훅.
6. [ ] `model.py`: §7.1 베이스라인 → §7.2 LightGBM walk-forward.
7. [ ] `evaluate.py`: 지표·베이스라인 비교·SHAP 출력.
8. [ ] ★ 결과 기록 후 ◆ 피처 추가 → 재평가. (성능 꺾이는 지점 탐색)
9. [ ] ○ 피처는 SHAP 검증 후 선택적 채택.
10. [ ] 누수 점검(§1)을 매 단계 반복: 스케일러 fit 범위, available_at, embargo.

---

## 11. 검증용 안전장치 (구현 시 자가점검)

- [ ] 어떤 피처도 예측일 당일(09:00 이후) 정보를 포함하지 않는가?
- [ ] `merge_asof` 가 `direction="backward"` 인가? 단순 date join을 쓰지 않았는가?
- [ ] 스케일러/통계량을 전체 데이터가 아니라 학습 fold에서만 fit 했는가?
- [ ] 분할이 시계열 순서를 지키고 embargo(gap)가 있는가?
- [ ] 모델이 나이브 베이스라인을 실제로 이기는가? (방향 적중률·RMSE)
