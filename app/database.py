"""数据库引擎、会话与初始化。"""
from __future__ import annotations

import logging
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)

_connect_args = {}
if settings.database_url.startswith("sqlite"):
    # SQLite 在多线程（后台任务线程）下需要关闭同线程检查
    _connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)

Base = declarative_base()


def init_db() -> None:
    """创建所有数据表（幂等）。"""
    from app import models  # noqa: F401  确保模型已注册到 Base.metadata

    settings.ensure_dirs()
    Base.metadata.create_all(bind=engine)
    logger.info("数据库已就绪：%s", settings.database_url)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：按请求提供数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
