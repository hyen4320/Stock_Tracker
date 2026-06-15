# 페이지 명세 (Pages / Screens)

프론트엔드(React+Vite)의 **화면 구성**을 정리한다. 기능 전체 목록은
[FEATURES.md](./FEATURES.md), 모델 내부는 [MODEL.md](./MODEL.md) 참고.

- 셸/라우팅: `frontend/src/App.jsx`
- 좌측 내비게이션: `frontend/src/components/Sidebar.jsx`
- 화면: `frontend/src/screens/{Dashboard,Detail,Simulator,Model}.jsx`

---

## 네비게이션 구조

```
애프터마켓 (사이드바)
├─ 메뉴
│  ├─ 대시보드     (dashboard)  ← 기본 화면
│  ├─ 종목 분석    (detail)
│  └─ 시나리오     (simulator)
└─ 관리자 [PIN 게이트]
   └─ 모델 상태    (model)      ← 관리자 로그인 후에만 노출
```

- 라우팅은 SPA 상태 기반(`route` state) — URL 경로 없이 화면 전환
- `model` 화면은 `isAdmin`이 아니면 자동으로 `dashboard`로 폴백
- 공통 데이터(`App.jsx`)는 `/api/predict`·`/api/live-drivers`·`/api/accuracy`를
  병렬 로드해 모든 화면에 props로 내려줌

### 공통 상태 처리 (App.jsx)
- **로딩**: 스켈레톤 + "최초 실행은 모델 학습으로 1~2분" 안내
- **데이터 없음**: "예측 생성하기" 버튼(`POST /api/run-prediction`)
- **에러 배너**: 상단에 `⚠️` 표시
- **시각 갱신**: KST 현재 시각·밤사이 진행률 60초마다 갱신

---

## 1. 대시보드 (Dashboard)

`screens/Dashboard.jsx` — 서비스의 첫 화면, 오늘의 예측 한눈에.

| 구역 | 내용 |
|------|------|
| **타임라인** | 한국 마감 → 美 SOX 세션(진행중) → 한국 시초가(예측) 진행률 바 |
| **예상 시초가 히어로** | 종목별 카드 — 예상 시초가, 갭(%), 변동액. 클릭 시 종목 분석으로 이동 |
| **밤사이 드라이버** | SOX·환율 라이브 변동률 행 + 피처 주입 설명 |
| **오늘의 예측 요약** | 추적 종목 수, 평균 예상 갭, 모델 MAE + "종목 분석 열기" 버튼 |
| **유의 고지** | 투자 권유 아님 명시 |

- 데이터: `targets`, `drivers`, `timeline`, `avgMae` (App.jsx에서 주입)
- 액션: `goDetail(key)`, `onRefresh`

---

## 2. 종목 분석 (Detail)

`screens/Detail.jsx` — 선택 종목의 차트·예측 분해. 종목 토글(삼성/하이닉스) 제공.

| 구역 | 내용 |
|------|------|
| **캔들 차트** | 60/120/250일 OHLC, 상승=빨강·하락=파랑 (한국식) |
| **예측 분해 패널** | 예상 시초가 대형 표시 + 피처별 기여도(%p) 워터폴 + 갭 합계 |
| **SOX 동조화 차트** | 종목 vs SOX를 기준=100 정규화한 라인 비교 |

- 데이터: `GET /api/history/{target}?window=` 로 캔들·정규화 시계열 로드
- 구간 변경(`winN`) 시 재요청, 종목 변경 시 재요청
- 기여도(`tg.contrib`)·민감도는 `lib/meta.js`의 표시용 상수 기반
  (실제 9-피처 모델 기여도와는 별개 — [MODEL.md](./MODEL.md) §참고 항목)

---

## 3. 시나리오 시뮬레이터 (Simulator)

`screens/Simulator.jsx` — SOX·환율을 직접 넣어 보는 what-if 실험실.

| 구역 | 내용 |
|------|------|
| **변동 입력** | SOX(−8~+8%)·환율(−3~+3%) 슬라이더 |
| **실시간 자동 토글** | 켜면 현재 라이브 드라이버 값으로 자동 고정 |
| **프리셋** | 급락/약세/보합/현재 라이브/강세/급등 6종 |
| **결과 카드** | 종목별 예상 시초가, 변동액·갭, 라이브 대비 차이(%p), β 표시 |

- 추정식: `gap = sens.base + βSOX·(sox/100) + βFX·(fx/100)`
- β는 `lib/meta.js`의 종목별 민감도 상수 (표시·실험용)
- 데이터: `targets`, `drivers` (App.jsx)

---

## 4. 모델 상태 (Model) — 관리자 전용

`screens/Model.jsx` — PIN 게이트(데모 1234) 통과 후에만 접근.

| 구역 | 내용 |
|------|------|
| **재학습 버튼** | `POST /api/train` 호출, 진행바(6→90%→100%) 표시 |
| **종목별 카드** | 학습 여부 배지, MAE·베이스라인·개선율, 방향 적중률 막대, 학습 표본 수 |
| **모델 구성 표** | 알고리즘·타깃·피처·검증·데이터 소스 요약 |

- 데이터: `GET /api/model-status`, `GET /api/accuracy`, `POST /api/train` 결과
- 방향 적중률은 실제값이 기록된 예측이 있어야 표시 (없으면 안내 문구)
- 진입 게이트: `components/AdminLogin.jsx` (PIN 1234) → `isAdmin` 설정

---

## 컴포넌트 맵 (참고)

| 파일 | 역할 |
|------|------|
| `components/Sidebar.jsx` | 좌측 내비, 관리자 진입/종료 |
| `components/common.jsx` | Topbar, Timeline, HeroCard, DriverRow, LivePill, Pulse |
| `components/Charts.jsx` | Sparkline, CandleChart, SyncChart (SVG) |
| `components/Icon.jsx` | 인라인 SVG 아이콘 |
| `components/AdminLogin.jsx` | PIN 입력 모달 |
| `lib/format.js` | won, signWon, pct, signPct, kstNowLabel |
| `lib/meta.js` | 종목 메타(로고/색/티커/β/기여도) — 표시용 상수 |
| `api.js` | 백엔드 호출 래퍼 |
</content>
