# 기능 명세 (Features)

반도체 애프터마켓 시초가 예측 서비스가 **무슨 기능을 제공하는지** 정리한다.
화면별 설명은 [PAGES.md](./PAGES.md), 모델 내부는 [MODEL.md](./MODEL.md),
전체 데이터 흐름은 [ARCHITECTURE.md](./ARCHITECTURE.md) 참고.

> 한 줄 요약: **한국 정규장 마감 → 밤사이 미국 SOX·환율 변동 → 다음날 한국 시초가 갭**을
> 예측해 매일 DB에 저장하고, 실제 시초가와 대조해 적중률을 누적 공개하는 서비스.

---

## 1. 핵심 기능

### 1.1 다음날 시초가 예측
- 대상: **삼성전자(005930.KS)**, **SK하이닉스(000660.KS)**
- 산출물: 예상 시초가(원), 예측 갭(%), 전일 종가 대비 변동액
- 원리: 종가[D] → 다음날 시초가[D+1] 갭 수익률을 회귀로 추정
  (`estimated_open = last_close × (1 + predicted_gap)`)

### 1.2 밤사이 드라이버 실시간 반영
- **SOX(필라델피아 반도체지수)** 와 **원/달러 환율**의 전일 종가 대비 수익률을 라이브로 조회
- 이 2개 값이 모델 피처(`SOX_ret`, `USDKRW_ret`)로 주입되어 예측이 밤사이 갱신됨
- 데이터 소스: yfinance (무료, API 키 불필요)

### 1.3 일별 예측 DB 저장 (공개 서비스의 핵심)
- 매일 생성한 예측을 PostgreSQL `predictions` 테이블에 **upsert** 저장
- `(target_date, target_name)` 유니크 제약으로 같은 날 중복 없이 1건 유지
- 온디맨드 in-memory 캐시가 아니라 **DB에서 꺼내 서빙** → 여러 사용자에게 동일 결과 제공

### 1.4 실제값 대조 · 적중률 누적
- 다음 개장 후 실제 시초가(`actual_open`)를 기록하고 오차(`error_pct`) 계산
- 종목별 **MAE(평균절대오차)** 와 **방향 적중률(direction hit rate)** 집계
- "예측 → 실제 → 적중률" 루프가 서비스의 신뢰도 근거

### 1.5 시나리오 시뮬레이터 (what-if)
- SOX·환율 변동률을 슬라이더/프리셋으로 직접 넣어 예상 시초가를 실험
- 종목별 민감도 β로 `gap = base + βSOX·sox + βFX·fx` 선형 추정
- "실시간 자동" 토글로 현재 라이브 드라이버 값 자동 반영

### 1.6 종목 분석 (차트)
- **캔들 차트**: 60/120/250일 구간 OHLC (상승=빨강 / 하락=파랑, 한국식)
- **SOX 동조화 차트**: 종목 vs SOX를 기준=100 정규화해 상관 시각화
- **예측 갭 분해**: 각 피처가 예상 갭에 기여한 정도(%p) 워터폴

### 1.7 예측–실제 괴리율 그래프 _(예정)_
- 예측 시초가와 실제 시초가의 **괴리율(오차)을 시계열 그래프**로 시각화
- 종목별로 날짜축에 따라 예측값·실제값 두 라인을 겹쳐 보여주고,
  그 차이(`error_pct`)를 별도 막대/영역으로 표시
- 데이터 소스: `predictions` 테이블의 `estimated_open`·`actual_open`·`error_pct`
  (`GET /api/predictions/history`)
- 목적: 시간이 지날수록 모델이 얼마나 잘 맞는지(또는 특정 구간에서 빗나가는지)를
  사용자에게 투명하게 공개 → 서비스 신뢰도 근거

---

## 2. 자동화 (스케줄러)

APScheduler가 앱에 내장되어 평일(KST) 자동 실행:

| 작업 | 시각(KST) | 내용 |
|------|-----------|------|
| 예측 생성 | 평일 08:00 | 개장 전 예측 산출 → DB upsert (`run_daily_prediction`) |
| 실제값 기록 | 평일 09:10 | 개장 후 실제 시초가 → `actual_open`/`error_pct` 채움 (`record_actuals`) |

- 시각은 `config.py`의 `PREDICT_HOUR/MINUTE`, `ACTUAL_HOUR/MINUTE`로 조절
- 콜드 스타트: 배치가 아직 안 돈 상태에서 `/api/predict` 호출 시 즉석 1회 생성

---

## 3. 모델 관리 (관리자 전용)

- **모델 재학습**: 두 종목 모델을 yfinance 최신 데이터로 재학습, 진행바 표시
- **모델 상태**: 학습 여부, MAE, 베이스라인 대비 개선율, 학습 표본 수
- **방향 적중률 카드**: 실제값이 쌓인 만큼 종목별 적중률 막대 표시
- 접근 제어: **PIN 게이트**(데모 PIN 1234)로 모델 화면 보호

---

## 4. 사용자 경험

- **시간대 정렬 타임라인**: 한국 마감 → 美 SOX 세션(진행중) → 한국 시초가(예측) 진행률
- **라이브 갱신**: 현재 시각(KST) 분 단위 갱신, 밤사이 진행률 애니메이션
- **그레이스풀 폴백**: 로딩 스켈레톤, 콜드 스타트 안내, 데이터 없을 때 "예측 생성하기" 버튼
- **경량 뱅킹 UI**: Toss 스타일 라이트 테마, 앰버 액센트, 한국식 캔들 색상
- **투자 유의 고지**: 통계 모델 산출물이며 투자 권유가 아님을 명시

---

## 5. API 엔드포인트 요약

| 메서드 | 경로 | 기능 |
|--------|------|------|
| GET | `/api/health` | 헬스 체크 |
| GET | `/api/targets` | 추적 종목 목록 |
| GET | `/api/predict` | 오늘자 최신 예측 (DB, 콜드 스타트 시 즉석 생성) |
| GET | `/api/predictions/history` | 과거 예측 이력 (실제값/오차 포함) |
| GET | `/api/accuracy` | 종목별 적중 통계(MAE·방향 적중률) |
| GET | `/api/live-drivers` | 현재 SOX·환율 라이브 수익률 |
| GET | `/api/model-status` | 종목별 모델 학습 여부 |
| GET | `/api/history/{target}` | 캔들 + SOX 동조화 시계열 |
| POST | `/api/train` | 두 종목 모델 재학습 (관리용) |
| POST | `/api/run-prediction` | 예측 배치 수동 트리거 (관리용) |
| POST | `/api/record-actuals` | 실제 시초가 기록 수동 트리거 (관리용) |
| POST | `/api/refresh` | 시세 캐시 비우기 |

> 응답 스키마·구현은 `backend/main.py`, 쿼리는 `backend/queries.py`,
> 배치는 `backend/jobs.py` 참고.

---

## 6. 기술 스택

| 영역 | 기술 |
|------|------|
| 백엔드 | FastAPI + uvicorn (포트 8000) |
| 프론트 | React 18 + Vite 6 (포트 5173, `/api` 프록시) |
| DB | PostgreSQL (`psycopg` v3) · 미설정 시 SQLite 폴백 |
| ORM | SQLAlchemy 2.0 |
| 스케줄러 | APScheduler (앱 내장, KST 평일) |
| ML | scikit-learn `HistGradientBoostingRegressor` |
| 데이터 | yfinance (무료) |
</content>
</invoke>
