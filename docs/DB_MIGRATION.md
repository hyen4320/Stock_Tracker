# 캐시 DB 정본 전환 & prod 컷오버 가이드

피처 캐시를 로컬 파일(parquet/CSV)에서 **DB 정본**으로 옮긴 작업의 운영 문서다.
durability(머신 손실 시 복구 불가한 과거 보존)와 단일 백업 지점 확보가 목적이다.

> **핵심.** prod를 관리형 Postgres로 띄울 때는 `DATABASE_URL`을 Postgres로 건 뒤
> **`python -m scripts.migrate_cache_to_db` 를 딱 1회 실행**한다. 안 하면 로컬
> 파일에만 있는 과거(yfinance 시간봉 730일·네이버 수급 등 재취득 불가/제한분)가
> prod DB에 들어가지 않는다. 기존 CSV/parquet는 백업으로 남겨둔다 — 코드는 더 이상
> 읽지 않지만 컷오버 검증 전까지 안전망이다.

---

## 1. 무엇이 어디에 저장되나

| 데이터 | 테이블 | 키 | 소스 재취득 |
|---|---|---|---|
| 예측/실제값 | `predictions` | (target_date, target_name) | — |
| 인트라데이 시간봉 | `intraday_bars` | (ticker, ts) | ❌ 불가 (yfinance 730일 롤링 소거) |
| KRX 투자자별 순매수 | `daily_series` [krx_supply] | (source, entity, date, metric) | ✅ KRX 로그인 |
| KRX 프로그램매매 | `daily_series` [krx_program] | 〃 | ✅ KRX 로그인 |
| 금투협 신용/증시자금 | `daily_series` [kofia] | 〃 | ✅ 무인증 |
| 네이버 외국인 수급 | `daily_series` [naver_frgn] | 〃 | △ 제한적 |

- `intraday_bars`: 단일 지표(close)라 전용 typed 테이블. ts = 봉 *종료* 시각(UTC).
- `daily_series`: 소스마다 컬럼이 달라(가변) 테이블 4개·ALTER를 피하려 **long-format
  1개**로 흡수. 한 셀 = `(source, entity, date, metric) → value`, 읽을 때 wide로 pivot.
  - `source` = 'krx_supply' | 'krx_program' | 'kofia' | 'naver_frgn'
  - `entity` = 종목코드('005930')·시장('STK')·종류('credit'/'funds')
  - `metric` = 컬럼명('frgn_net' 등)

DB는 prod=관리형 Postgres(`DATABASE_URL`), 로컬=SQLite(`data/app.db`) 폴백. 같은
SQLAlchemy 코드로 양쪽 동작하며, upsert는 방언별 `ON CONFLICT`로 멱등 처리한다.

---

## 2. prod 컷오버 절차

```bash
# 1) Postgres 연결 문자열 주입 (.env 또는 환경변수)
#    예) postgresql+psycopg://user:password@host:5432/dbname
export DATABASE_URL=postgresql+psycopg://...

# 2) 테이블 생성 + 로컬 캐시 → DB 1회 이관 (멱등 — 재실행 무해)
python -m scripts.migrate_cache_to_db

#    먼저 건수만 확인하려면:
python -m scripts.migrate_cache_to_db --dry-run
```

`migrate_cache_to_db`가 이관하는 대상:

| 로컬 파일 | → DB |
|---|---|
| `data/intraday_{slug}.parquet` | `intraday_bars` |
| `data/krx_supply_{code}.csv` | `daily_series[krx_supply]` |
| `data/krx_program_{mkt}.csv` | `daily_series[krx_program]` |
| `data/kofia_{kind}.csv` | `daily_series[kofia]` |
| `data/naver_frgn_{code}.csv` | `daily_series[naver_frgn]` |

> ⚠️ 이관은 로컬 파일을 읽으므로 **컷오버를 수행하는 머신에 그 파일들이 있어야**
> 한다. 인트라데이 parquet은 yfinance가 730일만 보관하니, 다른 머신에서 처음
> 적립을 시작하면 그만큼 과거가 비어 시작한다 — 가능하면 *적립을 해온 머신에서*
> 한 번에 이관한다.

### 검증 (선택)

```bash
# 이관 후 건수가 채워졌는지 dry-run으로 재확인 (DB 행 수 표시)
python -m scripts.migrate_cache_to_db --dry-run
```

---

## 3. 적립 스케줄 (인트라데이)

인트라데이 시간봉은 yfinance가 730일 넘은 봉을 **영구 삭제**하므로 주기 적립이
필수다. 앱(FastAPI) 내장 APScheduler가 평일 처리한다.

- 잡 id `accrue_intraday` — 평일 **08:10 KST**(08:00 스냅샷 봉 게시 직후)에
  `accrue_intraday_cache()` 실행 → DB upsert(멱등).
- 시각 변경: `.env`의 `INTRADAY_ACCRUE_HOUR` / `INTRADAY_ACCRUE_MINUTE`.
- **앱이 24/7 떠 있어야** 적립이 돈다. 안 떠 있는 환경이면 OS 스케줄러로
  적립 진입점을 별도 호출해야 한다(현재는 APScheduler 경로만 구성).

커버리지는 시간이 지나며 저절로 오른다(문서 기준 ~1년 후 60%). 그 시점에 LGBM
인트라데이 피처 직접 학습으로 재검정한다([EXPERIMENT_RESULTS §6](./EXPERIMENT_RESULTS.md)).

---

## 4. 롤백 / 백업

- 기존 `data/*.parquet`·`data/*.csv`는 **삭제하지 않았다**. 코드는 더 이상 읽지
  않지만, 컷오버 검증이 끝날 때까지 안전망으로 남긴다.
- 문제 발생 시 `DATABASE_URL`을 비워 로컬 SQLite로 되돌리고 마이그레이션을
  재실행하면 동일 상태로 복원된다(upsert 멱등).
- 검증 완료 후 로컬 파일 정리는 선택. 단 **인트라데이 parquet은 prod DB 백업이
  확인되기 전까지 보관**을 권장(재취득 불가 과거 포함).

---

## 5. 관련 코드

- `backend/models.py` — `IntradayBar`, `DailySeries`
- `backend/intraday_store.py` — `load_bars` / `upsert_bars`
- `backend/series_store.py` — `load_frame` / `upsert_frame` (long↔wide pivot)
- `backend/jobs.py::accrue_intraday_cache`, `backend/scheduler.py` — 적립 잡
- `scripts/migrate_cache_to_db.py` — 전 소스 1회 이관
- 콜렉터: `experiments/{krx_supply,krx_program,kofia_credit}.py`,
  `experiments/improvements_compare.py::fetch_naver_flows`,
  `experiments/intraday_snapshot.py`
