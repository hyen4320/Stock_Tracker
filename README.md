# Stock_Tracker — 반도체 애프터마켓 예측

삼성전자·SK하이닉스의 **정규장 마감 이후 가격 추이**를 예측하는 서비스.

한국 정규장(15:30 KST) 마감 후에는 두 종목 거래가 멈추지만, 밤사이 미국
**필라델피아 반도체지수(SOX)** 와 **원/달러 환율**은 계속 움직인다. 이 변동을
머신러닝 모델에 반영해 **다음날 예상 시초가**를 실시간으로 추정한다.

## 예측 구조 (시간대 정렬)

```
한국 마감(D, 15:30 KST) ──▶ 밤사이 미국 SOX 세션(같은 날짜 D) ──▶ 한국 시초가(D+1, 09:00)
```

- **타깃 y**: 한국주식 종가[D] → 다음 거래일 시초가[D+1] 갭 수익률
- **피처 X**: SOX 수익률[D], 환율 수익률[D], 종목 자체 모멘텀 및 시차들
- 예측 시 **현재(밤중) SOX/환율 변동**을 피처로 주입하면 추정 시초가가 실시간 갱신됨

## 데이터 소스 (yfinance, 무료·키 불필요)

| 데이터 | 티커 |
|--------|------|
| 필라델피아 반도체지수 | `^SOX` |
| 원/달러 환율 | `KRW=X` |
| 삼성전자 | `005930.KS` |
| SK하이닉스 | `000660.KS` |

## 모델

- `scikit-learn` **HistGradientBoostingRegressor** (추가 의존성 없는 그래디언트 부스팅)
- 평가: `TimeSeriesSplit` 5-fold, 지표는 MAE
- 베이스라인("변동 없음" 예측) 대비 개선율로 성능 판단

## 구조

```
config.py            # 티커·경로·하이퍼파라미터
src/data_loader.py   # yfinance 시세 수집 + 정렬
src/features.py      # 피처 엔지니어링 + 시간대 정렬
src/model.py         # 학습/저장/로드/예측
src/predict.py       # 엔드투엔드 예측(현재 변동 → 추정 시초가)
backend/main.py      # FastAPI 백엔드 (src/ 재사용, REST API)
backend/cache.py     # 시세 인메모리 TTL 캐시
frontend/            # React + Vite 대시보드 (API 호출)
```

아키텍처는 **백엔드(FastAPI API) + 프론트엔드(React+Vite)** 분리 구조다.
프론트는 Vite 프록시로 `/api/*` 를 FastAPI(8000)에 전달한다.

## 실행

### 1) 백엔드 (터미널 A)

```bash
pip install -r requirements.txt
python -m src.model                                  # 최초 1회: 모델 학습
python -m uvicorn backend.main:app --reload --port 8000
```

### 2) 프론트엔드 (터미널 B)

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

브라우저에서 `http://localhost:5173` 접속. (백엔드는 8000에서 떠 있어야 함)

### API 주요 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/predict?sox=&fx=` | 예상 시초가(소수 변동률, 미지정 시 최신값) |
| GET | `/api/history/{종목}?window=` | 캔들·동조화 차트 데이터 |
| GET | `/api/live-drivers` | 현재 SOX·환율 변동률 |
| GET | `/api/model-status` | 모델 학습 여부 |
| POST | `/api/train` | 모델 재학습 |
| POST | `/api/refresh` | 시세 캐시 비우기 |

문서: 백엔드 실행 후 `http://localhost:8000/docs` (Swagger UI)

CLI로 빠르게 예측만 보려면:

```bash
python -m src.predict
```

## ⚠️ 주의

본 추정치는 통계 모델의 산출물이며 투자 권유가 아니다. 실제 시초가는 수급·뉴스 등
다양한 요인으로 달라질 수 있다.
