# 아키텍처 설명서 — 데이터 · 모델 · 화면

이 문서는 Stock_Tracker가 **① 어떤 데이터를 받아서 → ② 어떤 모델로 예측하고 →
③ 화면에 어떻게 보여주는지**를 코드 기준으로 설명한다.

---

## 전체 흐름 한눈에 보기

```
┌──────────── 백엔드 (Python / FastAPI) ─────────────────┐   ┌─── 프론트 ───┐
│ 원천데이터 ─▶ 피처 ─▶ ML모델 ─▶ 예측 ─▶ DB ─▶ REST API  │──▶│ React + Vite │
│ data_loader  features  model   predict  PG   backend/  │/api│ 4화면 SPA    │
│         ▲ 매일 배치(APScheduler): 예측 저장 → 실제값 기록  │   └──────────────┘
└────────────────────────────────────────────────────────┘
```

| 단계 | 파일 | 역할 |
|------|------|------|
| ① 원천 데이터 | `src/data_loader.py` | yfinance에서 4개 티커 일봉 수집·정렬 |
| ② 피처 | `src/features.py` | 수익률·시차 피처 생성, 타깃 정의(시간대 정렬) |
| ③ 모델 | `src/model.py` | 학습·교차검증·저장·예측 |
| ④ 예측 | `src/predict.py` | 현재 변동 → 추정 시초가로 변환 |
| ⑤ 저장 | `backend/models.py` · `db.py` | 매일 예측을 DB에 저장, 다음날 실제값·오차 기록 |
| ⑥ 배치 | `backend/jobs.py` · `scheduler.py` | 평일 예측 생성/실제값 기록 자동 실행 |
| ⑦ API | `backend/main.py` | 위 기능을 REST로 노출 (+ `cache.py` 시세 TTL 캐시) |
| ⑧ 화면 | `frontend/` | React+Vite 4화면 SPA, `/api/*` 호출로 시각화 |

> 모델 입력 파라미터·하이퍼파라미터의 상세는 [MODEL.md](./MODEL.md) 참고.

---

## ① 원천 데이터 (Source Data)

### 무엇을 받나

`config.py`에 정의된 4개 티커를 **yfinance**(Yahoo Finance, 무료·API 키 불필요)로 받는다.

| 구분 | 이름 | 티커 | 역할 |
|------|------|------|------|
| 드라이버(설명변수) | SOX | `^SOX` | 필라델피아 반도체지수 |
| 드라이버(설명변수) | USDKRW | `KRW=X` | 원/달러 환율 |
| 타깃(예측대상) | 삼성전자 | `005930.KS` | |
| 타깃(예측대상) | SK하이닉스 | `000660.KS` | |

### 어떻게 받나 — `data_loader.fetch_history()`

- 각 티커의 **일봉 OHLC**(시가/고가/저가/종가)를 `HISTORY_PERIOD`(기본 5년)만큼 받는다.
- 모든 티커를 하나의 **와이드 포맷** DataFrame으로 합친다. 컬럼 예시:
  `SOX_Close`, `USDKRW_Close`, `삼성전자_Open`, `삼성전자_Close`, `SK하이닉스_Close` …
- 인덱스는 거래일(`Date`, 시간대 제거).
- 한국·미국 거래일이 다르므로(공휴일 차이) 겹치지 않는 날은 `NaN`이 생기며, 이후
  피처 단계의 `dropna`로 정리된다.

> 실시간(밤중) 시세는 `fetch_latest_quote(ticker)`가 `fast_info`로 현재가/전일종가를
> 받아온다. 이 값으로 "현재 SOX가 전일 대비 몇 %" 같은 실시간 변동을 계산한다.

---

## ② 피처 엔지니어링 + 시간대 정렬 (핵심)

### 왜 시간대 정렬이 핵심인가

```
한국 마감(D, 15:30 KST) ──▶ 밤사이 미국 SOX 세션(같은 날짜 D) ──▶ 한국 시초가(D+1, 09:00)
        │                          │                              │
   삼성 종가[D] 확정          SOX 종가[D] 확정               삼성 시초가[D+1]
```

한국장이 닫힌 뒤 **같은 날짜의 미국 반도체장**이 밤새 거래되고, 그 결과가 다음날
한국 시초가의 **갭**으로 나타난다. 이 인과 순서를 그대로 학습 구조로 옮긴다.

### 타깃(y)과 피처(X) — `features.build_feature_frame()`

- **타깃 `target_gap`**: 한국주식 `종가[D] → 다음날 시초가[D+1]` 갭 수익률
  ```
  target_gap = Open[D+1] / Close[D] - 1
  ```
- **피처 `X`** (모두 D+1 시초가 시점에 알 수 있는 정보만 사용 → 미래 정보 누수 방지):

  | 피처 | 의미 |
  |------|------|
  | `SOX_ret` | SOX 당일(D) 수익률 |
  | `SOX_ret_lag1`, `SOX_ret_lag2` | SOX 1·2일 전 수익률 |
  | `USDKRW_ret` (+lag1, lag2) | 환율 당일·시차 수익률 |
  | `삼성전자_ret` (+lag1, lag2) | 종목 자체 모멘텀 |

  (시차 목록은 `config.LAGS = [1, 2]`로 조절)

### 학습용 데이터로 변환 — `make_xy()`

맨 앞(시차로 인한 결측)과 맨 뒤(다음날 시초가가 아직 없는 행)를 `dropna`로 제거하고
`(X, y)`를 반환한다.

### 예측용 1행 — `latest_feature_row()`

가장 최근 시점의 피처 한 줄을 만든다. 여기에 **밤중 현재 변동**을 주입할 수 있다:

```python
latest_feature_row(data, "삼성전자", sox_live_ret=0.02, fx_live_ret=-0.003)
#  → SOX_ret 자리를 +2.0%, 환율을 -0.3%로 덮어써서 실시간 추정에 사용
```

---

## ③ 모델 (Model) — `src/model.py`

### 어떤 모델

- **scikit-learn `HistGradientBoostingRegressor`**
  - 추가 의존성 없이 견고한 그래디언트 부스팅, 결측치 자체 처리
  - 설정(`_new_model`): `max_iter=300`, `learning_rate=0.05`, `max_depth=3`,
    `l2_regularization=1.0`
- 종목별로 **별도 모델**을 학습 → `models/삼성전자.joblib`, `models/SK하이닉스.joblib`
  (모델 + 사용한 피처 목록을 함께 저장)

### 어떻게 평가하나 — `train()`

시계열 데이터이므로 **`TimeSeriesSplit`(5-fold)** 로 과거→미래 순서를 지키며 검증한다.
지표는 **MAE**(평균절대오차), 그리고 비교용 **베이스라인**으로 "갭 0%(변동 없음)"를 둔다.

```
반환 metrics 예시:
{
  "target": "삼성전자",
  "n_samples": 1158,
  "cv_mae": 0.0091,        # 0.91%
  "baseline_mae": 0.0105,  # 1.05%
  "improvement_pct": 13.0  # 베이스라인 대비 개선율
}
```

> **현재 성능**: 삼성전자 CV-MAE 0.91%(베이스라인 대비 ↑13%), SK하이닉스 1.32%(↑16%).
> 노이즈가 큰 금융 예측에서 "변동 없음" 베이스라인을 이긴, 합리적인 출발점이다.

### 예측 — `predict_gap()`

저장된 모델을 불러와 피처 1행으로 **갭 수익률**을 예측한다. 모델 파일이 없으면 먼저
학습한다.

---

## ④ 엔드투엔드 예측 — `src/predict.py`

모델이 내놓는 건 "갭 수익률"이므로, 이를 **사람이 읽는 가격**으로 바꾼다.

`predict_open(data, 종목, sox_live_ret, fx_live_ret)` →

```python
{
  "target": "삼성전자",
  "last_close": 295500,        # 최근 종가
  "predicted_gap": 0.0333,     # 예측 갭 +3.33%
  "estimated_open": 305344,    # = last_close × (1 + gap)
  "change": 9844,              # 예상 변동액
}
```

`predict_all()`은 모든 대상 종목에 대해 위를 반복한다. `sox_live_ret`/`fx_live_ret`을
주면 밤중 실시간 변동이 반영되고, 안 주면 데이터의 최신 확정 변동을 쓴다.

---

## ⑤ 저장 — DB (`backend/db.py`, `backend/models.py`)

예측을 매 요청마다 즉석 계산하지 않고 **매일 한 번 계산해 DB에 저장**한다. 공개 서비스에서
모든 사용자가 같은 값을 보고, yfinance 과다 호출을 막고, **과거 예측 vs 실제 결과(적중률)**를
누적하기 위함이다.

- **DB**: prod는 PostgreSQL(`DATABASE_URL` 환경변수). 미설정 시 로컬 SQLite로 자동 폴백.
  같은 SQLAlchemy 코드로 양쪽 동작.
- **테이블 `predictions`** (`models.py`): `(target_date, target_name)` 유니크. 한 종목·하루 1행.

  | 컬럼 | 의미 |
  |------|------|
  | `prediction_date` / `target_date` | 예측 생성일 / 예측 대상 거래일 |
  | `last_close`, `predicted_gap`, `estimated_open` | 예측 결과 |
  | `sox_ret`, `fx_ret` | 예측에 쓴 드라이버 값(재현용) |
  | `actual_open`, `error_pct` | **다음날 개장 후** 채워지는 실제 시초가·오차 |

---

## ⑥ 배치 — 스케줄러 (`backend/jobs.py`, `backend/scheduler.py`)

**APScheduler**(앱 내장)가 평일(월~금, KST) 2개 작업을 자동 실행한다.

```
08:00 KST  run_daily_prediction()  → 데이터 수집 → 예측 → DB upsert (멱등)
09:10 KST  record_actuals()        → 실제 시초가 기록 → 오차 계산
```

- 시각은 `config.py`(`PREDICT_HOUR` 등)로 조절. 모델이 없으면 예측 전 자동 학습.
- 앱 없이 단독 실행도 가능: `python -m scripts.run_daily_prediction [--force|--actuals]`
  (OS cron 백업용).

---

## ⑦ API — `backend/main.py` (FastAPI)

위 기능을 REST로 노출한다. 프론트는 이 API만 호출한다. 예측 엔드포인트는 **즉석 계산이
아니라 DB를 조회**한다.

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/predict` | 오늘자(최신) 예측 — DB 조회 (비어있으면 1회 즉석 생성) |
| GET | `/api/predictions/history?target=&limit=` | 과거 예측 + 실제값 이력(적중 기록) |
| GET | `/api/accuracy` | 종목별 MAE·방향 적중률 |
| GET | `/api/history/{종목}?window=` | 캔들·동조화 차트용 시계열 |
| GET | `/api/live-drivers` | 현재(밤중) SOX·환율 변동률 |
| GET | `/api/model-status` · `/api/targets` | 모델 학습 여부 · 대상 종목 목록 |
| POST | `/api/train` | 두 종목 모델 재학습(평가지표 반환) |
| POST | `/api/run-prediction` · `/api/record-actuals` | 배치 수동 트리거(관리용) |
| POST | `/api/refresh` | 시세 캐시 비우기 |

- **시작 시(lifespan)**: 테이블 생성 + 스케줄러 기동.
- **캐시**: `backend/cache.py`가 시세를 15분 TTL로 인메모리 캐싱.
- **CORS/프록시**: 개발 시 Vite(5173)가 `/api/*`를 FastAPI(8000)로 프록시
  (Windows IPv6 이슈로 타깃을 `127.0.0.1`로 고정).
- 실행: `python -m uvicorn backend.main:app --reload --port 8000`, Swagger `http://localhost:8000/docs`.

---

## ⑧ 화면 — `frontend/` (React + Vite, 4화면 SPA)

`npm run dev`(→ `http://localhost:5173`). 라이트 뱅킹 테마의 사이드바 전환형 4화면.

| 화면 | 파일 | 내용 |
|------|------|------|
| 대시보드 | `screens/Dashboard.jsx` | 시간대 타임라인 + 예상 시초가 히어로 카드 + 밤사이 드라이버 |
| 종목 분석 | `screens/Detail.jsx` | 한국식 캔들(상승=빨강) + 예측 갭 분해 + SOX 동조화 |
| 시나리오 | `screens/Simulator.jsx` | SOX·환율 슬라이더로 예상 시초가 what-if (클라이언트 계산) |
| 모델 상태 🔒 | `screens/Model.jsx` | **관리자 PIN** 후 노출. MAE·적중률·재학습 |

| 공통 파일 | 역할 |
|-----------|------|
| `src/App.jsx` | 셸·라우팅·데이터 오케스트레이션·관리자 게이트 |
| `src/api.js` | `/api/*` 호출 래퍼 |
| `src/lib/` | `format.js`(포맷), `meta.js`(종목 표시 메타·β 상수) |
| `src/components/` | `Icon` · `Charts`(SVG) · `common` · `Sidebar` · `AdminLogin` |

### 데이터 흐름 (화면 ↔ API)

```
[App.jsx 마운트] ─▶ GET /api/predict, /api/live-drivers, /api/accuracy ─▶ 대시보드 렌더
종목/기간 선택 ────▶ GET /api/history/{종목} ─────────────────────────▶ 차트 갱신
🔒 관리자(PIN 1234) ─▶ 모델 화면 → POST /api/train, GET /api/accuracy
🔄 새로고침 ────────▶ POST /api/refresh → 위 재조회
```

- **관리자 게이트**: 사이드바 🔒 → PIN 모달(데모 1234). 미인증 시 모델 화면 차단.
- 시뮬레이터 β는 표시용 상수(`lib/meta.js`)이며 모델과 별개 — [MODEL.md](./MODEL.md) §참고.

---

## 한 줄 요약

> **yfinance로 SOX·환율·삼성·하이닉스 일봉을 받아**(①) **한국 마감→미국 밤장→다음날
> 시초가의 시간 순서로 피처·타깃을 정렬하고**(②) **그래디언트 부스팅으로 갭을 예측해**(③)
> **종가에 곱해 추정 시초가로 변환한 뒤**(④) **매일 배치가 DB에 저장하고 다음날 실제값으로
> 적중률을 채운다**(⑤⑥). **FastAPI가 이를 REST로 노출하면**(⑦) **React 4화면 SPA가
> 카드·차트로 보여준다**(⑧).
