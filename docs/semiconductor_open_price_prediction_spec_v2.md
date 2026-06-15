# 반도체 시초가 예측 모델 — 프로젝트 명세 v2 (for Claude Code)

> 이 문서는 Claude Code가 읽고 코드를 스캐폴딩·구현하기 위한 명세서다.
> v1 대비 변경점: **모델 알고리즘은 그대로(LightGBM + 베이스라인)** 두되,
> 데이터 정합성·정렬·분할·평가의 누수 차단을 강화했다. 목표는 "더 똑똑한 모델"이
> 아니라 **"부풀려지지 않은 정직한 측정"** 이다.
> 라이브러리 API는 버전에 따라 바뀌므로, 구현 시 각 라이브러리의 현재 docs를
> 확인하고 함수 시그니처를 검증할 것.

---

## 0. 목표 (Objective)

- **삼성전자(005930)** 와 **SK하이닉스(000660)** 의 **다음 거래일 시초가(개장가)** 를 예측한다.
- 예측 대상은 시초가 절대가격이 아니라 **갭(gap)** 이다:
  ```
  y = log(open[D] / close[D-1])     # 거래일 D의 시초가 갭 (종목별)
  ```
- 모든 입력 피처는 거래일 D의 장 시작(09:00 KST) **이전에 확정된 정보만** 사용한다.

> **합법적 신호의 한계에 대한 전제(중요).** 한국 시초가 갭은 본질적으로 밤사이
> 미국 반도체·선물 움직임이 대부분을 설명한다. 그런데 그 정보를 08:59 시점에
> 고해상도로 정직하게 쓸 수 없는 경우가 많다(§2 야간선물 참조). 따라서 이 모델의
> 현실적 산출물은 "시초가를 맞춘다"가 아니라 **"랜덤워크 대비 의미 있는 엣지가
> 있는지에 대한 정직한 답 + 불확실성이 표시된 예측"** 이다. 평균적으로 베이스라인을
> 못 이길 수 있으며, 그 결과 자체가 유효한 결론이다(§1-5).

> 참고: 이 프로젝트는 모델링 방법론이며 투자 조언이 아니다. 백테스트 성과가
> 실거래 수익을 보장하지 않는다.

---

## 1. 절대 규칙 (Hard Rules — 위반 금지)

이 규칙들은 성능보다 우선한다. 하나라도 어기면 결과 전체가 무효다.

1. **룩어헤드 금지.** 거래일 D의 시초가 예측에는 D의 08:59 KST 이전에 확정된
   값만 쓴다. 예측일 당일 장중 데이터, 당일 종가, 당일 수급 등은 절대 피처에
   넣지 않는다.
2. **정렬은 `available_at` 타임스탬프(tz-aware UTC) + `merge_asof(direction="backward")` 로만 한다.**
   날짜 단순 join 금지. `available_at` 은 절대 낙관적으로 잡지 말 것(애매하면 늦게).
3. **타깃 정합성: `open[D]` 와 `close[D-1]` 은 반드시 동일한 수정주가 기준으로 맞춘다.**
   액면분할(삼성 2018 50:1)·배당락이 섞이면 갭이 가짜값이 된다. 분할/배당락일은
   별도 검증한다. (§5)
4. **시계열 변환은 정렬 *전에* 각 소스의 네이티브 캘린더에서 계산한다.**
   롤링(MA/RSI/실현변동성)·GARCH를 한국 거래일로 정렬된 프레임 위에서 계산하지
   않는다. GARCH·실현변동성 같은 모델 기반 피처는 매 시점 과거만으로 fit한다
   (전 구간 일괄 fit = 룩어헤드).
5. **Point-in-time 데이터만 사용.** 외국인/기관 순매수의 잠정→확정 수정, 지표
   리비전 등 "나중에 고쳐진 값"을 과거 시점 피처로 쓰지 않는다. 애매하면 lag를 더 준다.
6. **풀링 모델은 날짜 단위로 분할한다.** 종목별 행이 2개이므로 행 단위 분할
   (`TimeSeriesSplit` 기본)은 동시점 누수를 만든다. 날짜로 fold를 먼저 자른 뒤
   두 종목을 같은 쪽에 배정한다. (§6)
7. **스케일러·통계량은 학습 구간에서만 `fit`**, 검증·테스트엔 `transform` 만 적용한다.
   (단조 스케일링에 불변인 트리 모델엔 스케일러 불필요 — 선형/NN에만 적용.)
8. **early-stopping용 셋과 성능 측정용 셋을 분리한다.** 같은 fold로 early stopping을
   하면서 그 fold로 점수를 보고하면 낙관 편향이 생긴다. (§6, §7)
9. **최종 홀드아웃(최근 6~12개월)은 학습·튜닝·early stopping·피처 선택 어디에도
   노출하지 않는다.** SHAP 기반 ○피처 선택도 홀드아웃을 건드리면 안 된다.
10. **나이브 베이스라인을 반드시 구현하고 모든 모델을 이와 비교한다.**
    베이스라인을 못 이기면 피처/설계 문제로 간주한다(이기지 못한다는 결론도 유효하다).

---

## 2. 데이터 수집 (Collection)

무료 소스로 대부분 수집 가능. 각 소스의 **정보 확정 시각(available_at, tz-aware UTC)** 과
**커버리지 시작일** 을 함께 기록한다.

| 데이터 | 소스(라이브러리) | 식별자/메모 | available_at (KST 기준) |
|---|---|---|---|
| 한국 OHLCV | `pykrx` 또는 `FinanceDataReader` | 005930, 000660. **수정주가 정책 확인 필수** | 해당일 장마감(15:30) 후 |
| 한국 투자자별 순매수 | `pykrx` | 외국인/기관/개인. **잠정/확정 여부 확인** | 해당일 장마감 후(잠정), 확정은 +1영업일 가정 |
| 신용잔고/반대매매/미수 | KRX 정보데이터시스템 또는 금투협 freesis | pykrx 커버리지 제한적 | 약 T+2 공시(보수적으로) |
| 美 개별주(공통) | `yfinance` | MU, NVDA, AVGO, AMD, MRVL, ASML, AMAT, LRCX, KLAC | 美 정규장 종가 → 익일 새벽(DST로 06~07시 변동) |
| 美 개별주(하이닉스) | `yfinance` | SNDK(2025.2 WDC서 분사 → **그 이전 결측**), 키오시아 `6600.T`(선택) | 동일 / 일본장 마감 후 |
| 美 개별주(삼성) | `yfinance` | TSM, QCOM, AAPL | 동일 |
| 미국 지수 | `yfinance` | `^SOX`, `^IXIC`, `^GSPC`, `^VIX` | 동일 |
| 야간 선물 | `yfinance` | `NQ=F`, `ES=F` | **§2.1 주의 — 일봉으로는 08:59 스냅샷 불가** |
| 달러인덱스 | `yfinance` | `DX-Y.NYB` | 동일 |
| 환율 USD/KRW | `yfinance` | `KRW=X` (시점 정의 §2.1) | 연속(단, 일봉 tz 모호) |
| 미국 10년물 금리 | FRED (`fredapi`/`pandas_datareader`) | `DGS10` (익영업일 오전 공표·리비전 있음) | 美 영업일 +1 보수적 |
| 한국 금리 | 한국은행 ECOS API | 국고채 3Y/10Y | 해당일 |
| 캘린더 | 룰 생성 + KRX 휴장일 | 선물옵션 만기일=분기 둘째 목요일 등 | 사전 확정 |

### 2.1 야간선물·환율 시점 정의 (갈림길)

`yfinance` 일봉은 08:59 KST 시점 스냅샷을 주지 않는다. D 날짜 선물 일봉은 아직
진행 중인 Globex 세션을 포함하므로 백테스트에서 끌어오면 **미래정보 누수**다.
두 가지 중 하나를 명시적으로 택한다:

- **(기본) 보수 정의:** 야간선물을 "전일 미국 정규장 마감 시점 값"으로 강등.
  08:59의 실시간 갭 신호는 포기한다. 누수 없음, 정보량 낮음.
- **(선택) 인트라데이 소스:** 별도 인트라데이 데이터를 붙여 08:59 KST 직전
  스냅샷을 정직하게 확보. 데이터 인프라 비용 발생. 실거래를 붙일 때 권장.

`KRW=X` 일봉도 tz가 모호하므로 "전일 미국장 마감 시점 환율"로 보수 정의한다.

수집 예시:
```python
import yfinance as yf
import pandas_datareader.data as web
import FinanceDataReader as fdr

US_COMMON   = "MU NVDA AVGO AMD MRVL ASML AMAT LRCX KLAC"
US_HYNIX    = "SNDK"          # 하이닉스 특화(NAND). 2025.2 이전 결측 처리 필요
US_SAMSUNG  = "TSM QCOM AAPL"
US_MACRO    = "^SOX ^VIX DX-Y.NYB NQ=F ES=F"
US_TICKERS  = " ".join([US_COMMON, US_HYNIX, US_SAMSUNG, US_MACRO])

# 주의: yfinance 최신 버전은 auto_adjust 기본값이 바뀌어 ["Close"]가 수정종가일 수 있음.
#       수정 기준을 명시적으로 고정하고 한국·미국 전 종목에 일관 적용할 것.
us  = yf.download(US_TICKERS, start="2016-01-01", auto_adjust=True)["Close"]
fx  = yf.download("KRW=X", start="2016-01-01", auto_adjust=True)["Close"]
dgs10 = web.DataReader("DGS10", "fred", "2016-01-01")

sam = fdr.DataReader("005930", "2016-01-01")   # 삼성전자 — 수정주가 정책 확인
hyx = fdr.DataReader("000660", "2016-01-01")   # SK하이닉스
# 수급: pykrx ... 잠정/확정 여부를 docs로 확인하고 lag 정책 결정
```

> 커버리지 시작일을 `config.py` 에 종목별로 기록한다. 짧은 히스토리 티커(SNDK 등)는
> 백테스트 대부분 구간이 결측이므로 §5의 결측 전략을 따른다.

---

## 3. 피처 카탈로그 (Feature Catalog)

우선순위: **★필수 / ◆보강 / ○실험적(검증 후 채택)**.
구현은 ★ → ◆ → ○ 순서로, 각 단계마다 성능을 기록한다.

> **공선성 주의.** MU·NVDA·AVGO·AMD·SOX는 일간 상관이 매우 높다. LGBM 예측엔
> 무해하나 importance/SHAP가 상관 피처 사이에 임의 분배되어 **○티어 선택을
> 오도한다.** 대응: ① 가능한 한 (개별주−SOX) 상대강도로 변환, ② 채택 판단은
> **grouped permutation importance** 또는 상관 클러스터 단위로. (§8)

| 분류 | 피처 | 가공 방식 / 메모 | 우선순위 |
|---|---|---|---|
| 기준 | SOX 수익률 | 전일 log return. 개별주와 중복 → 가급적 (MU−SOX) 상대강도 | ★ |
| 기준 | USD/KRW | 전일 변화율(시점 정의 §2.1). 공통 통제변수 | ★ |
| 美 공통 | MU(마이크론) | 전일 log return. DRAM/NAND/HBM 직접 피어 | ★ |
| 美 공통 | NVDA(엔비디아) | HBM 수요 동인 | ★ |
| 美 공통 | AVGO(브로드컴) | AI 가속기 수요·섹터 심리 | ★ |
| 美 공통 | AMD | AI GPU 수요 | ◆ |
| 美 공통 | MRVL(마벨) | 커스텀 실리콘/HBM 인접 | ◆ |
| 美 공통 | 장비군 ASML/AMAT/LRCX/KLAC | 메모리 캐펙스 사이클(인덱스화) | ◆ |
| 美 공통 | (MU − SOX) 상대강도 | 메모리 다이버전스, 공선성↓ | ◆ |
| 美 하이닉스 | SNDK(샌디스크) | NAND 피어. 2025.2 분사 → 그 이전 결측 | ◆ |
| 美 하이닉스 | NVDA 가중↑ | HBM 최대 공급사. 가중 또는 별도 lag 피처 | ★ |
| 美 하이닉스 | 6600.T(키오시아) | NAND 순수, 日 상장. 정렬 번거로우면 생략 | ○ |
| 美 삼성 | TSM(TSMC) | 파운드리 직접 경쟁(삼성 only) | ★ |
| 美 삼성 | QCOM(퀄컴) | 파운드리 고객 + System LSI·모바일 AP 경쟁 | ◆ |
| 美 삼성 | AAPL(애플) | 최대 고객 + 스마트폰 경쟁. 반도체 신호 희석 주의 | ○ |
| 美 매크로 | 나스닥/S&P 종가 + 야간선물(NQ=F,ES=F) | 갭 방향. **시점 정의 §2.1** | ★ |
| 美 매크로 | VIX | 변동성·갭 크기 | ◆ |
| 美 매크로 | DXY(DX-Y.NYB) | 신흥국 자금유출 대리 | ◆ |
| 美 매크로 | 美 10년물(DGS10) | 밸류에이션 | ◆ |
| 한국 수급 | 외국인 순매수(전일/누적) | 대형주 최강 신호. **잠정/확정 + lag 필수** | ★ |
| 한국 수급 | 기관 순매수 | lag | ◆ |
| 한국 수급 | 개인 순매수 | 역추세 보완 | ◆ |
| 한국 수급 | 프로그램 매매 | | ○ |
| 한국 시장 | KOSPI 전일종가 + KOSPI200 야간선물 | 시점 정의 §2.1 | ◆ |
| 한국 시장 | 거래대금(전일·MA 대비 비율) | 유동성/증폭 | ◆ |
| 한국 시장 | 한국 금리(3Y/10Y) | | ○ |
| 자금 로테이션 | 반도체업종 vs KOSPI 상대수익률 | 국면 의존, 노이즈↑ | ○ |
| 자금 로테이션 | vs 경쟁테마(2차전지 등) 상대수익률 | | ○ |
| 자금 로테이션 | 시장 전체 반대매매·미수 금액 | risk-off 대리 | ○ |
| 레버리지 | 신용잔고율(종목별) | 대형주라 효과 제한적, ~T+2 lag | ○ |
| 레버리지 | 신용잔고 증감률 | 취약성·심리 | ○ |
| 자기 시계열 | 전일 종가·갭·고저폭·거래량 | | ★ |
| 자기 시계열 | MA(5/20/60)·RSI·MACD·볼린저 | **네이티브 캘린더에서 계산 후 정렬**(§1-4) | ◆ |
| 자기 시계열 | 실현변동성 / GARCH | **매 시점 과거만으로 fit**(§1-4) | ◆ |
| 자기 시계열 | 교차 종목 신호(삼전↔하이닉스) | **상대 종목은 D-1 종가까지만**(둘 다 09:00 동시 개장) | ◆ |
| 캘린더 | 요일·월 더미 | | ◆ |
| 캘린더 | 선물옵션 만기일(네 마녀의 날) 더미 | | ◆ |
| 캘린더 | 실적발표 전후 더미 | | ◆ |
| 캘린더 | 지수 리밸런싱일 / 연휴직후 갭 더미 | | ○ |
| 신선도 | 美 데이터 staleness(직전 美 종가 경과일수) | 한·미 휴장 엇갈림 대리 | ◆ |

> **종목별 피처 적용 규칙.** (v1 유지)
> SK하이닉스 = 순수 메모리 + HBM 1위 + Solidigm(NAND). 삼성전자 = 메모리 +
> 파운드리 + 시스템LSI + 디스플레이 + 모바일.
> - **옵션 A(종목별 모델 2개):** 하이닉스 = `공통 + 하이닉스 특화`, 삼성 = `공통 + 삼성 특화`.
> - **옵션 B(풀링 단일 모델):** 전체 피처 + 종목 ID(0/1). 특화 피처는 `특화 × 종목ID`
>   교차항으로 해당 종목에서만 활성화. **단 §6의 날짜 단위 분할 필수.**
> - `TSM`은 삼성 특화. 하이닉스 모델엔 ○로만 선택 투입.
> - `NVDA`는 공통이나 하이닉스 민감도가 커 가중↑ 또는 별도 lag 피처.

---

## 4. 정렬 로직 (Alignment — 핵심)

모든 소스를 `(available_at[UTC, tz-aware], value...)` 형태로 만든 뒤, 예측일 D의
08:59 KST 컷오프 기준으로 backward merge 한다.

```python
import pandas as pd

# kr_dates: 예측 대상 한국 거래일 인덱스 (DatetimeIndex, tz-naive 가정)
cutoff = (kr_dates.tz_localize("Asia/Seoul").normalize()
          + pd.Timedelta(hours=8, minutes=59)).tz_convert("UTC")
cutoff = pd.Series(cutoff, name="asof").to_frame().reset_index(names="kr_date")

def attach(base, source_df):
    # source_df: columns = ["available_at"(UTC, tz-aware), <feature cols...>]
    s = source_df.sort_values("available_at")
    return pd.merge_asof(base.sort_values("asof"), s,
                         left_on="asof", right_on="available_at",
                         direction="backward")
```

### available_at 산정 기준 (tz-aware, 보수적으로)

- **美 정규장 종가:** 미국은 DST가 있고 한국은 없다. 마감은 여름 21:00 UTC,
  겨울 22:00 UTC. **고정값 금지** — 미국 세션 날짜의 마감 시각을 tz-aware로 계산한다.
  (08:59 컷오프보다 한참 앞서므로 누수는 없으나 일관성을 위해 정확히 잡는다.)
- **한국 장마감 데이터(수급/종가):** 해당일 06:30 UTC(15:30 KST). 단 수급
  **확정치는 +1영업일** 로 잡는다(잠정→확정 리비전 회피, §1-5).
- **신용잔고:** 공시 지연 반영해 +2 영업일 시점.
- **FRED DGS10:** 공표·리비전 지연 반영해 +1 영업일 보수.
- **야간선물/환율:** §2.1 보수 정의(전일 미국 마감 시점) 또는 인트라데이 소스.

> 한·미 휴장 엇갈림으로 가장 최근 美 종가가 며칠 stale해질 수 있다. backward merge가
> 자동 처리하나, 그 staleness 자체를 §3의 신선도 피처로 노출한다.

---

## 5. 피처 엔지니어링 & 타깃

- 가격류는 전부 **log return** 으로 변환.
- **롤링 피처(MA/RSI/실현변동성)는 각 소스의 네이티브 캘린더에서 계산한 뒤 정렬한다**
  (§1-4). 한국 거래일 인덱스 위에서 직접 계산 금지.
- **GARCH·실현변동성은 매 시점 과거만으로 fit**(expanding/rolling). 전 구간 일괄 fit 금지.
- 상대강도 = `ret(MU) - ret(SOX)` 식으로 생성(공선성↓).
- 캘린더·신선도 더미 생성.
- **타깃 정합성(§1-3):**
  ```python
  # open 과 prev close 가 동일 수정주가 기준인지 검증한 뒤 계산
  y_sam = np.log(open_sam / close_sam.shift(1))
  y_hyx = np.log(open_hyx / close_hyx.shift(1))
  # 분할/배당락일 플래그로 가짜 갭 검출 → 제외 또는 보정
  ```
- **타깃 팻테일 처리:** 실적·뉴스·상한가성 점프로 극단 갭이 섞인다. 학습 시
  타깃 **winsorize**(예: 1%/99%) 또는 손실함수에 Huber 사용을 기본으로 한다.
- **결측 전략:** LGBM은 NaN을 native 처리하므로 짧은 히스토리 티커는 그대로 NaN
  유지(임의 임퓨테이션은 fit/transform 누수 위험). 커버리지 시작 전 구간은
  해당 피처를 비활성으로 둔다.
- 종목 처리: **(A) 종목별 모델 2개** 또는 **(B) 종목 ID 풀링 단일 모델**.
  공통 피처가 많으므로 (B)를 기본 권장하되 **§6 날짜 단위 분할 필수**, (A)와 비교.

---

## 6. 데이터 분할 (Validation)

**핵심 수정: 행 단위 분할 금지, 날짜 단위 walk-forward.**

- 풀링(옵션 B)은 날짜당 행이 2개이므로 `TimeSeriesSplit` 기본(행 인덱스 분할)은
  같은 날짜의 두 종목을 train/valid로 갈라 **동시점 누수**를 만든다.
  → **날짜로 fold를 먼저 자른 뒤** 그 날짜의 두 종목을 같은 fold에 배정한다.
  embargo(gap)도 **행이 아니라 일(day) 단위**로 적용한다.
- **expanding vs sliding:** 국면 변화(2018 분할, 2022 다운사이클, 2023~ HBM 붐)가
  크므로 **sliding window** 와 expanding 을 모두 돌려 비교한다.
- **튜닝 누수 차단:**
  - early-stopping용 셋과 성능 측정용 셋을 분리(§1-8).
  - 하이퍼파라미터 튜닝은 **nested**(외부 fold=평가, 내부 fold=튜닝)로 한다.
- **최종 테스트셋:** 가장 최근 6~12개월을 떼어 학습·튜닝·early stopping·**피처 선택**
  어디에도 쓰지 않는다(§1-9).

```python
# 날짜 단위 walk-forward 스케치 (풀링 안전)
uniq_dates = np.sort(df["kr_date"].unique())
# uniq_dates 를 시간순 fold로 분할 → 각 fold 경계에 embargo(일 단위) 부여 →
# 날짜→행 매핑으로 X,y 인덱스 추출. (행 인덱스 직접 분할 금지)
```

---

## 7. 모델 (Model)

### 7.1 베이스라인 (먼저 구현)
- `y_hat = 0` (랜덤워크)
- `y_hat = rolling_mean(gap)` (과거 평균 갭 — 드리프트 포착)
- `y_hat = sign/beta * ret_SOX[D-1]` (단순 선형, 방향 베이스라인)
- 선형회귀(★피처만)

### 7.2 주력: LightGBM (권장)
```python
import lightgbm as lgb

# 표본(≈4,800행) 대비 피처가 많으므로 정규화를 강화하고 단조 제약을 건다.
model = lgb.LGBMRegressor(
    objective="huber",            # 팻테일 대응 (또는 quantile, §7.4)
    n_estimators=3000, learning_rate=0.02,
    num_leaves=15,                # v1(31)보다 보수적
    min_child_samples=50,         # v1(30)보다 강화
    subsample=0.8, colsample_bytree=0.8,
    reg_lambda=5.0, reg_alpha=1.0,
    monotone_constraints=[...],   # 예: SOX↑→갭↑ 등 경제적 사전지식 반영
)
# fit 시 early-stopping 셋은 성능 측정 셋과 분리 (§6)
```

- **단조 제약**: SOX·MU 상승 → 갭 상승 등 명백한 방향만 건다(표본 효율↑, 과적합↓).

### 7.3 (선택) 시계열 NN
LSTM/TFT는 데이터가 충분하고 시퀀스 구조를 직접 학습시키고 싶을 때만. 일별·lag
피처 기준으론 GBM 대비 이득이 작고 과적합 관리가 어려움 → 후순위.

### 7.4 불확실성 출력 (권장 부가가치)
LGBM **분위수 회귀**(예: 0.1/0.5/0.9)로 예측 구간을 낸다. "언제 모델이 자신
없는가"는 점추정 정확도보다 트레이딩에서 중요하며, §8의 임계치 평가와 맞물린다.

---

## 8. 평가 (Evaluation)

- 회귀 지표: RMSE/MAE(갭 기준), R². **추가로 Huber loss·winsorized RMSE** 병기.
- **방향 적중률은 작은 갭에서 무의미**하므로 `|예측| > 임계치` 구간으로 **조건부
  hit rate** 를 보고한다(전체 평균 적중률은 착시).
- **국면별 평가**: 전체뿐 아니라 연도/사이클 구간별로 베이스라인 대비 성능을 쪼갠다.
- **모든 지표를 §7.1 베이스라인과 비교**(표로 출력). 베이스라인을 못 이기면
  그 사실을 결론으로 보고한다.
- **거래 정의 명시**: "이 예측으로 무슨 주문을 내는가"를 먼저 정의한다. 시초가에
  체결하면 체결가가 곧 open이므로 갭 자체는 직접 못 먹는다. 따라서 손익 백테스트는
  체결 모델(예: 전일 종가 진입 → 시가 청산)과 **거래비용·슬리피지**를 명시해야
  hit rate와 손익이 따로 놀지 않는다.
- **피처 중요도**: 단일 SHAP는 공선성 하에서 신뢰도가 낮으므로 **grouped
  permutation importance**(상관 클러스터 단위)로 ○티어 채택/제거를 판단한다.
  이 판단 과정은 홀드아웃을 건드리지 않는다(§1-9).

---

## 9. 권장 프로젝트 구조

```
semiconductor-open-predict/
├── README.md                  # 이 명세
├── requirements.txt
├── config.py                  # 티커/종목코드/기간/경로/우선순위 토글/커버리지 시작일/수정주가 정책
├── src/
│   ├── collect.py             # §2 수집 + available_at(tz-aware) + 잠정/확정 정책 + 캐시
│   ├── align.py               # §4 컷오프 + merge_asof + staleness 피처
│   ├── features.py            # §3,§5 네이티브 캘린더 변환 → 정렬, ★/◆/○ 토글, 상대강도
│   ├── target.py              # §5 수정주가 정합성 검증 + 분할/배당락 플래그 + winsorize
│   ├── dataset.py             # 타깃·학습셋 조립 + 풀링/분리 + (fold 내부)스케일링 훅
│   ├── split.py               # §6 날짜 단위 walk-forward + embargo(일) + nested 튜닝
│   ├── model.py               # §7 baseline + LightGBM(단조제약/Huber/분위수) walk-forward
│   └── evaluate.py            # §8 지표/조건부 hit rate/국면별/거래모델/grouped importance
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
arch            # GARCH (point-in-time fit)
yfinance
finance-datareader
pykrx
pandas-datareader
```

---

## 10. 구현 순서 (Task Checklist for Claude Code)

1. [ ] `config.py`: 티커/종목코드/기간/출력경로/우선순위 플래그/**커버리지 시작일/수정주가 정책**.
2. [ ] `collect.py`: 소스별 수집 + `available_at`(tz-aware) + **잠정/확정 정책** + 캐시.
3. [ ] `target.py`: **수정주가 정합성 검증** + 분할/배당락 플래그 + 타깃 생성 + winsorize.
4. [ ] `align.py`: §4 컷오프 + `attach()` backward merge + **staleness 피처**.
5. [ ] `features.py`: ★피처부터. **네이티브 캘린더에서 변환 후 정렬**, 상대강도, 교차종목은 D-1까지만.
6. [ ] `split.py`: **날짜 단위 walk-forward** + 일 단위 embargo + early-stop/점수 셋 분리 + nested 튜닝.
7. [ ] `dataset.py`: 풀링/분리 옵션 + fold 내부 스케일링 훅(트리엔 생략 가능).
8. [ ] `model.py`: §7.1 베이스라인 → §7.2 LightGBM(단조제약/Huber) → §7.4 분위수(선택).
9. [ ] `evaluate.py`: 지표·조건부 hit rate·국면별·거래모델·grouped importance.
10. [ ] ★ 결과 기록 후 ◆ 추가 → 재평가. ○는 **홀드아웃 비노출** 하에 grouped importance로 선택.
11. [ ] 누수 점검(§11)을 매 단계 반복.

---

## 11. 검증용 안전장치 (구현 시 자가점검)

- [ ] 어떤 피처도 예측일 당일(09:00 이후) 정보를 포함하지 않는가?
- [ ] `open[D]` 와 `close[D-1]` 이 동일 수정주가 기준인가? 분할/배당락 갭을 걸러냈는가?
- [ ] 롤링·GARCH를 **정렬 전 네이티브 캘린더**에서, **과거만으로** 계산했는가?
- [ ] 외국인 순매수 등 수급에 **잠정→확정 리비전 누수**가 없는가? lag가 충분한가?
- [ ] 야간선물/환율을 §2.1 보수 정의(또는 정직한 인트라데이)로 잡았는가? 진행 중 세션을 끌어오지 않았는가?
- [ ] `available_at` 이 tz-aware이고 DST를 반영했는가? `merge_asof(direction="backward")` 인가?
- [ ] **풀링 시 행 단위가 아니라 날짜 단위로 분할**했는가? embargo가 일 단위인가?
- [ ] early-stopping 셋과 성능 측정 셋이 분리되었는가? 튜닝이 nested인가?
- [ ] 최종 홀드아웃이 학습·튜닝·early stopping·**피처 선택** 어디에도 노출되지 않았는가?
- [ ] 스케일러/통계량을 학습 fold에서만 fit했는가? (트리 모델엔 스케일러가 불필요함을 인지했는가?)
- [ ] 평가에 **조건부 hit rate·국면별 분해·거래비용 반영 손익**이 포함됐는가?
- [ ] 모델이 나이브 베이스라인을 실제로 이기는가? (못 이기면 그 결론을 보고)
