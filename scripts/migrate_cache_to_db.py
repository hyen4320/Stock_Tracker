"""로컬 캐시(parquet/CSV)를 DB 정본으로 1회 이관한다 — 전 소스 일괄.

DB 정본 전환 전까지 누적된 캐시가 로컬 파일에만 있으므로, DATABASE_URL 이
가리키는 DB(prod=관리형 Postgres)에 멱등 upsert 한다. yfinance 시간봉(730일)·
네이버 수급 등 일부는 재취득이 어렵거나 불가하니 prod 전환 시 *반드시* 1회 실행.

대상:
  - data/intraday_{slug}.parquet   → intraday_bars (시간봉)
  - data/krx_supply_{code}.csv      → daily_series[krx_supply]
  - data/krx_program_{mkt}.csv      → daily_series[krx_program]
  - data/kofia_{kind}.csv           → daily_series[kofia]
  - data/naver_frgn_{code}.csv      → daily_series[naver_frgn]

사용:
    python -m scripts.migrate_cache_to_db            # DATABASE_URL 대상으로 이관
    python -m scripts.migrate_cache_to_db --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from backend.db import init_db  # noqa: E402
from backend.intraday_store import load_bars, upsert_bars  # noqa: E402
from backend.series_store import load_frame, upsert_frame  # noqa: E402
from experiments.intraday_snapshot import TICKERS  # noqa: E402

DATA_DIR = ROOT / "data"
SLUG2TK = {slug: tk for tk, slug in TICKERS.items()}

# CSV 파일명 prefix → daily_series source
CSV_FAMILIES = {
    "krx_supply_": "krx_supply",
    "krx_program_": "krx_program",
    "kofia_": "kofia",
    "naver_frgn_": "naver_frgn",
}


def _migrate_intraday(dry: bool) -> None:
    for slug, tk in SLUG2TK.items():
        path = DATA_DIR / f"intraday_{slug}.parquet"
        if not path.exists():
            continue
        s = pd.read_parquet(path).iloc[:, 0]
        s.index = pd.DatetimeIndex(s.index)
        if dry:
            print(f"  intraday {tk}: parquet {len(s)}행, 현재 DB {len(load_bars(tk))}행 (dry)")
            continue
        upsert_bars(tk, s)
        print(f"  intraday {tk}: → DB {len(load_bars(tk))}행 "
              f"({s.index.min().date()} ~ {s.index.max().date()})")


def _migrate_csvs(dry: bool) -> None:
    for path in sorted(DATA_DIR.glob("*.csv")):
        fam = next((p for p in CSV_FAMILIES if path.name.startswith(p)), None)
        if fam is None:
            continue
        source = CSV_FAMILIES[fam]
        entity = path.stem[len(fam):]
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if dry:
            have = len(load_frame(source, entity=entity))
            print(f"  {source}[{entity}]: csv {len(df)}행 × {len(df.columns)}col, "
                  f"현재 DB {have}행 (dry)")
            continue
        n = upsert_frame(source, df, entity=entity)
        print(f"  {source}[{entity}]: {n}셀 upsert "
              f"({df.index.min().date()} ~ {df.index.max().date()}, cols={list(df.columns)})")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="쓰지 않고 건수만 출력")
    args = parser.parse_args()

    init_db()
    print("== 인트라데이 시간봉 ==")
    _migrate_intraday(args.dry_run)
    print("== 일별 시계열(수급/프로그램/신용/네이버) ==")
    _migrate_csvs(args.dry_run)
    print("dry-run 완료(쓰기 없음)" if args.dry_run else "이관 완료")


if __name__ == "__main__":
    main()
