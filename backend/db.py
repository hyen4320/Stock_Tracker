"""데이터베이스 엔진/세션 설정.

prod 는 PostgreSQL(DATABASE_URL), 로컬은 SQLite 폴백.
같은 SQLAlchemy 코드로 양쪽 모두 동작한다.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import DATABASE_URL


class Base(DeclarativeBase):
    pass


# SQLite 는 멀티스레드(스케줄러+요청)에서 같은 커넥션 공유를 막으므로 옵션 필요
_connect_args = (
    {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,      # 끊긴 커넥션 자동 감지 (관리형 PG 권장)
    connect_args=_connect_args,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """테이블 생성(최초 1회). 추후 스키마 변경은 Alembic 도입 권장."""
    from backend import models  # noqa: F401  (모델 등록을 위해 import)

    Base.metadata.create_all(engine)
