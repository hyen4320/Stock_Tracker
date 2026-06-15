"""예측 배치 수동 실행 스크립트.

OS cron / 작업 스케줄러 / 수동 트리거 어디서든 쓸 수 있다.
앱(FastAPI)을 띄우지 않아도 단독으로 DB에 예측을 기록한다.

사용:
    python -m scripts.run_daily_prediction            # 오늘 예측 생성
    python -m scripts.run_daily_prediction --force    # 기존 행 덮어쓰기
    python -m scripts.run_daily_prediction --actuals  # 실제 시초가 기록
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.db import init_db  # noqa: E402
from backend.jobs import record_actuals, run_daily_prediction  # noqa: E402


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="기존 예측 덮어쓰기")
    parser.add_argument("--actuals", action="store_true", help="실제 시초가 기록")
    args = parser.parse_args()

    init_db()
    if args.actuals:
        record_actuals()
    else:
        run_daily_prediction(force=args.force)


if __name__ == "__main__":
    main()
